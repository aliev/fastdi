use std::collections::{HashMap, HashSet};
use pyo3::prelude::*;
use pyo3::exceptions::{PyKeyError, PyRuntimeError};
use pyo3::types::PyTuple;

#[derive(Clone)]
struct ProviderMeta {
    singleton: bool,
    is_async: bool,
    dep_keys: Vec<String>,
}

struct Provider {
    callable: Py<PyAny>,
    meta: ProviderMeta,
    cache: Option<Py<PyAny>>, // only used when singleton=true
}

impl Provider {
    fn new(callable: Py<PyAny>, singleton: bool, is_async: bool, dep_keys: Vec<String>) -> Self {
        Self { callable, meta: ProviderMeta { singleton, is_async, dep_keys }, cache: None }
    }
}

struct ContainerInner {
    providers: HashMap<String, Provider>,
    // Stack of override layers; last is topmost
    overrides: Vec<HashMap<String, Provider>>,
}

impl ContainerInner {
    fn new() -> Self {
        Self { providers: HashMap::new(), overrides: Vec::new() }
    }

    fn push_layer(&mut self) {
        self.overrides.push(HashMap::new());
    }

    fn pop_layer(&mut self) {
        self.overrides.pop();
    }

    fn set_override(&mut self, key: String, provider: Provider) {
        if let Some(top) = self.overrides.last_mut() {
            top.insert(key, provider);
        }
    }

    fn register(&mut self, key: String, provider: Provider) {
        self.providers.insert(key, provider);
    }

    fn resolve_many(&mut self, py: Python<'_>, keys: &[String]) -> PyResult<Vec<Py<PyAny>>> {
        let mut out = Vec::with_capacity(keys.len());
        for k in keys {
            let mut seen = HashSet::new();
            out.push(self.resolve_key(py, k, &mut seen)?);
        }
        Ok(out)
    }

    fn resolve_key(
        &mut self,
        py: Python<'_>,
        key: &str,
        seen: &mut HashSet<String>,
    ) -> PyResult<Py<PyAny>> {
        if !seen.insert(key.to_string()) {
            return Err(PyRuntimeError::new_err(format!(
                "Dependency cycle detected at key: {}",
                key
            )));
        }

        // Find provider in overrides (topmost first) or base providers
        // Extract call metadata without holding the mutable borrow across recursion
        let mut maybe_meta: Option<(Py<PyAny>, ProviderMeta)> = None;

        // search overrides
        for layer in self.overrides.iter_mut().rev() {
            if let Some(p) = layer.get_mut(key) {
                // If singleton and cached -> return immediately
                if p.meta.singleton {
                    if let Some(cached) = p.cache.clone() {
                        seen.remove(key);
                        return Ok(cached);
                    }
                }
                maybe_meta = Some((p.callable.clone(), p.meta.clone()));
                break;
            }
        }

        if maybe_meta.is_none() {
            if let Some(p) = self.providers.get_mut(key) {
                if p.meta.singleton {
                    if let Some(cached) = p.cache.clone() {
                        seen.remove(key);
                        return Ok(cached);
                    }
                }
                maybe_meta = Some((p.callable.clone(), p.meta.clone()));
            }
        }

        let (callable, meta) = maybe_meta.ok_or_else(|| {
            PyKeyError::new_err(format!("No provider registered for key: {}", key))
        })?;

        // Disallow async provider in sync resolution path
        if meta.is_async {
            return Err(PyRuntimeError::new_err(format!(
                "Provider for key '{}' is async and requires async resolution",
                key
            )));
        }

        // Resolve dependencies recursively
        let mut args: Vec<Py<PyAny>> = Vec::with_capacity(meta.dep_keys.len());
        for dep_key in &meta.dep_keys {
            let v = self.resolve_key(py, dep_key, seen)?;
            args.push(v);
        }

        // Call provider
        let arg_tuple = PyTuple::new(py, args.iter().map(|a| a.as_ref(py)));
        let produced = callable.call1(py, arg_tuple)?;
        let produced_owned: Py<PyAny> = produced.into();

        // Store in cache if singleton
        if meta.singleton {
            // Assign cache into the appropriate map
            // Try overrides first
            for layer in self.overrides.iter_mut().rev() {
                if let Some(p) = layer.get_mut(key) {
                    if p.meta.singleton {
                        p.cache = Some(produced_owned.clone());
                        seen.remove(key);
                        return Ok(produced_owned);
                    }
                }
            }
            if let Some(p) = self.providers.get_mut(key) {
                if p.meta.singleton {
                    p.cache = Some(produced_owned.clone());
                }
            }
        }

        seen.remove(key);
        Ok(produced_owned)
    }
}

#[pyclass]
struct Container {
    inner: std::sync::Mutex<ContainerInner>,
}

#[pymethods]
impl Container {
    #[new]
    fn new() -> Self {
        Self { inner: std::sync::Mutex::new(ContainerInner::new()) }
    }

    fn register_provider(
        &self,
        key: String,
        callable: PyObject,
        singleton: bool,
        is_async: bool,
        dep_keys: Vec<String>,
    ) -> PyResult<()> {
        let provider = Provider::new(callable.into(), singleton, is_async, dep_keys);
        let mut g = self.inner.lock().unwrap();
        g.register(key, provider);
        Ok(())
    }

    fn resolve(&self, py: Python<'_>, key: String) -> PyResult<Py<PyAny>> {
        let mut g = self.inner.lock().unwrap();
        let mut seen = HashSet::new();
        g.resolve_key(py, &key, &mut seen)
    }

    fn resolve_many(&self, py: Python<'_>, keys: Vec<String>) -> PyResult<Vec<Py<PyAny>>> {
        let mut g = self.inner.lock().unwrap();
        g.resolve_many(py, &keys)
    }

    fn begin_override_layer(&self) {
        let mut g = self.inner.lock().unwrap();
        g.push_layer();
    }

    fn set_override(
        &self,
        key: String,
        callable: PyObject,
        singleton: bool,
        is_async: bool,
        dep_keys: Vec<String>,
    ) -> PyResult<()> {
        let provider = Provider::new(callable.into(), singleton, is_async, dep_keys);
        let mut g = self.inner.lock().unwrap();
        g.set_override(key, provider);
        Ok(())
    }

    fn get_provider_info(
        &self,
        key: String,
    ) -> PyResult<(Py<PyAny>, bool, bool, Vec<String>)> {
        let mut g = self.inner.lock().unwrap();
        for layer in g.overrides.iter_mut().rev() {
            if let Some(p) = layer.get_mut(&key) {
                return Ok((
                    p.callable.clone(),
                    p.meta.singleton,
                    p.meta.is_async,
                    p.meta.dep_keys.clone(),
                ));
            }
        }
        if let Some(p) = g.providers.get_mut(&key) {
            return Ok((
                p.callable.clone(),
                p.meta.singleton,
                p.meta.is_async,
                p.meta.dep_keys.clone(),
            ));
        }
        Err(PyKeyError::new_err(format!("No provider registered for key: {}", key)))
    }

    fn get_cached(&self, key: String) -> Option<Py<PyAny>> {
        let mut g = self.inner.lock().unwrap();
        for layer in g.overrides.iter_mut().rev() {
            if let Some(p) = layer.get_mut(&key) {
                if let Some(v) = p.cache.clone() {
                    return Some(v);
                }
            }
        }
        if let Some(p) = g.providers.get_mut(&key) {
            if let Some(v) = p.cache.clone() {
                return Some(v);
            }
        }
        None
    }

    fn set_cached(&self, key: String, value: PyObject) -> PyResult<()> {
        let mut g = self.inner.lock().unwrap();
        for layer in g.overrides.iter_mut().rev() {
            if let Some(p) = layer.get_mut(&key) {
                if p.meta.singleton {
                    p.cache = Some(value.clone().into());
                    return Ok(());
                }
            }
        }
        if let Some(p) = g.providers.get_mut(&key) {
            if p.meta.singleton {
                p.cache = Some(value.into());
                return Ok(());
            }
        }
        Err(PyRuntimeError::new_err(format!(
            "Cannot set cache for non-singleton or unknown key: {}",
            key
        )))
    }

    fn end_override_layer(&self) {
        let mut g = self.inner.lock().unwrap();
        g.pop_layer();
    }
}

#[pymodule]
fn _fastdi_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<Container>()?;
    Ok(())
}
