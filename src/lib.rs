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

fn clone_py(py: Python<'_>, value: &Py<PyAny>) -> Py<PyAny> {
    value.clone_ref(py)
}

fn clone_cache(py: Python<'_>, cache: &Option<Py<PyAny>>) -> Option<Py<PyAny>> {
    cache.as_ref().map(|v| v.clone_ref(py))
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
                    if let Some(cached) = clone_cache(py, &p.cache) {
                        seen.remove(key);
                        return Ok(cached);
                    }
                }
                maybe_meta = Some((clone_py(py, &p.callable), p.meta.clone()));
                break;
            }
        }

        if maybe_meta.is_none() {
            if let Some(p) = self.providers.get_mut(key) {
                if p.meta.singleton {
                    if let Some(cached) = clone_cache(py, &p.cache) {
                        seen.remove(key);
                        return Ok(cached);
                    }
                }
                maybe_meta = Some((clone_py(py, &p.callable), p.meta.clone()));
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
        let bound_args: Vec<_> = args.iter().map(|a| a.bind(py)).collect();
        let arg_tuple = PyTuple::new(py, &bound_args)?;
        let produced = callable.bind(py).call1(arg_tuple)?;
        let produced_owned: Py<PyAny> = produced.into();

        // Store in cache if singleton
        if meta.singleton {
            let cache_value = produced_owned.clone_ref(py);
            // Assign cache into the appropriate map
            // Try overrides first
            for layer in self.overrides.iter_mut().rev() {
                if let Some(p) = layer.get_mut(key) {
                    if p.meta.singleton {
                        p.cache = Some(cache_value.clone_ref(py));
                        seen.remove(key);
                        return Ok(produced_owned);
                    }
                }
            }
            if let Some(p) = self.providers.get_mut(key) {
                if p.meta.singleton {
                    p.cache = Some(cache_value);
                }
            }
        }

        seen.remove(key);
        Ok(produced_owned)
    }

    fn get_provider_meta(&mut self, py: Python<'_>, key: &str) -> Option<(Py<PyAny>, ProviderMeta)> {
        // search overrides topmost first
        for layer in self.overrides.iter_mut().rev() {
            if let Some(p) = layer.get_mut(key) {
                return Some((clone_py(py, &p.callable), p.meta.clone()));
            }
        }
        if let Some(p) = self.providers.get_mut(key) {
            return Some((clone_py(py, &p.callable), p.meta.clone()));
        }
        None
    }

    fn compile_order(&mut self, py: Python<'_>, roots: &[String]) -> PyResult<Vec<String>> {
        // DFS for topological order
        let mut state: HashMap<String, u8> = HashMap::new();
        let mut order: Vec<String> = Vec::new();

        fn visit(
            me: &mut ContainerInner,
            py: Python<'_>,
            k: &str,
            state: &mut HashMap<String, u8>,
            order: &mut Vec<String>,
        ) -> PyResult<()> {
            match state.get(k).copied() {
                Some(1) => {
                    return Err(PyRuntimeError::new_err(format!(
                        "Dependency cycle detected at key: {}",
                        k
                    )))
                }
                Some(2) => return Ok(()),
                _ => {}
            }
            state.insert(k.to_string(), 1);
            let (_, meta) = me
                .get_provider_meta(py, k)
                .ok_or_else(|| PyKeyError::new_err(format!("No provider registered for key: {}", k)))?;
            if meta.is_async {
                return Err(PyRuntimeError::new_err(format!(
                    "Provider for key '{}' is async and requires async resolution",
                    k
                )));
            }
            for dep in &meta.dep_keys {
                visit(me, py, dep, state, order)?;
            }
            state.insert(k.to_string(), 2);
            order.push(k.to_string());
            Ok(())
        }

        for r in roots {
            visit(self, py, r, &mut state, &mut order)?;
        }
        Ok(order)
    }

    fn execute_order(
        &mut self,
        py: Python<'_>,
        order: &[String],
    ) -> PyResult<HashMap<String, Py<PyAny>>> {
        let mut computed: HashMap<String, Py<PyAny>> = HashMap::new();
        for key in order {
            // Check singleton caches first
            // Determine provider location and metadata again (may have changed)
            // Also capture deps for current key
            let mut provider_loc_is_override = false;
            let mut deps: Vec<String> = Vec::new();
            let mut is_singleton = false;
            let mut callable: Option<Py<PyAny>> = None;

            // check overrides
            for layer in self.overrides.iter_mut().rev() {
                if let Some(p) = layer.get_mut(key.as_str()) {
                    if p.meta.singleton {
                        if let Some(cached) = clone_cache(py, &p.cache) {
                            computed.insert(key.clone(), cached);
                            callable = None;
                            is_singleton = true; // irrelevant now
                            deps.clear();
                            break;
                        }
                    }
                    callable = Some(clone_py(py, &p.callable));
                    deps = p.meta.dep_keys.clone();
                    is_singleton = p.meta.singleton;
                    provider_loc_is_override = true;
                    break;
                }
            }
            if computed.contains_key(key) {
                continue;
            }
            if callable.is_none() {
                if let Some(p) = self.providers.get_mut(key.as_str()) {
                    if p.meta.singleton {
                        if let Some(cached) = clone_cache(py, &p.cache) {
                            computed.insert(key.clone(), cached);
                            continue;
                        }
                    }
                    callable = Some(clone_py(py, &p.callable));
                    deps = p.meta.dep_keys.clone();
                    is_singleton = p.meta.singleton;
                } else {
                    return Err(PyKeyError::new_err(format!(
                        "No provider registered for key: {}",
                        key
                    )));
                }
            }

            // build args from computed deps
            let mut args_vec: Vec<Py<PyAny>> = Vec::with_capacity(deps.len());
            for d in &deps {
                if let Some(v) = computed.get(d) {
                    args_vec.push(clone_py(py, v));
                } else {
                    // Should not happen if order includes deps first
                    let mut seen = HashSet::new();
                    let v = self.resolve_key(py, d, &mut seen)?;
                    args_vec.push(v);
                }
            }
            let bound_args: Vec<_> = args_vec.iter().map(|a| a.bind(py)).collect();
            let arg_tuple = PyTuple::new(py, &bound_args)?;
            let produced = callable.unwrap().bind(py).call1(arg_tuple)?;
            let produced_owned: Py<PyAny> = produced.into();

            // cache if singleton
            if is_singleton {
                let cache_value = produced_owned.clone_ref(py);
                if provider_loc_is_override {
                    for layer in self.overrides.iter_mut().rev() {
                        if let Some(p) = layer.get_mut(key.as_str()) {
                            if p.meta.singleton {
                                p.cache = Some(cache_value.clone_ref(py));
                                break;
                            }
                        }
                    }
                } else if let Some(p) = self.providers.get_mut(key.as_str()) {
                    if p.meta.singleton {
                        p.cache = Some(cache_value);
                    }
                }
            }

            computed.insert(key.clone(), produced_owned);
        }
        Ok(computed)
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
        callable: Py<PyAny>,
        singleton: bool,
        is_async: bool,
        dep_keys: Vec<String>,
    ) -> PyResult<()> {
        let provider = Provider::new(callable, singleton, is_async, dep_keys);
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

    fn resolve_many_plan(&self, py: Python<'_>, keys: Vec<String>) -> PyResult<Vec<Py<PyAny>>> {
        let mut g = self.inner.lock().unwrap();
        let order = g.compile_order(py, &keys)?;
        let computed = g.execute_order(py, &order)?;
        let mut out = Vec::with_capacity(keys.len());
        for k in keys.iter() {
            if let Some(v) = computed.get(k) {
                out.push(clone_py(py, v));
            } else {
                return Err(PyRuntimeError::new_err(format!(
                    "Internal error: key {} missing after plan execution",
                    k
                )));
            }
        }
        Ok(out)
    }

    fn begin_override_layer(&self) {
        let mut g = self.inner.lock().unwrap();
        g.push_layer();
    }

    fn set_override(
        &self,
        key: String,
        callable: Py<PyAny>,
        singleton: bool,
        is_async: bool,
        dep_keys: Vec<String>,
    ) -> PyResult<()> {
        let provider = Provider::new(callable, singleton, is_async, dep_keys);
        let mut g = self.inner.lock().unwrap();
        g.set_override(key, provider);
        Ok(())
    }

    fn get_provider_info(
        &self,
        py: Python<'_>,
        key: String,
    ) -> PyResult<(Py<PyAny>, bool, bool, Vec<String>)> {
        let mut g = self.inner.lock().unwrap();
        for layer in g.overrides.iter_mut().rev() {
            if let Some(p) = layer.get_mut(&key) {
                return Ok((
                    clone_py(py, &p.callable),
                    p.meta.singleton,
                    p.meta.is_async,
                    p.meta.dep_keys.clone(),
                ));
            }
        }
        if let Some(p) = g.providers.get_mut(&key) {
            return Ok((
                clone_py(py, &p.callable),
                p.meta.singleton,
                p.meta.is_async,
                p.meta.dep_keys.clone(),
            ));
        }
        Err(PyKeyError::new_err(format!("No provider registered for key: {}", key)))
    }

    fn get_cached(&self, py: Python<'_>, key: String) -> Option<Py<PyAny>> {
        let mut g = self.inner.lock().unwrap();
        for layer in g.overrides.iter_mut().rev() {
            if let Some(p) = layer.get_mut(&key) {
                if let Some(v) = clone_cache(py, &p.cache) {
                    return Some(v);
                }
            }
        }
        if let Some(p) = g.providers.get_mut(&key) {
            if let Some(v) = clone_cache(py, &p.cache) {
                return Some(v);
            }
        }
        None
    }

    fn set_cached(&self, py: Python<'_>, key: String, value: Py<PyAny>) -> PyResult<()> {
        let mut g = self.inner.lock().unwrap();
        for layer in g.overrides.iter_mut().rev() {
            if let Some(p) = layer.get_mut(&key) {
                if p.meta.singleton {
                    p.cache = Some(clone_py(py, &value));
                    return Ok(());
                }
            }
        }
        if let Some(p) = g.providers.get_mut(&key) {
            if p.meta.singleton {
                p.cache = Some(value);
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
fn _fastdi_core(_py: Python, m: &pyo3::prelude::Bound<PyModule>) -> PyResult<()> {
    m.add_class::<Container>()?;
    Ok(())
}
