import inspect
from contextlib import contextmanager
from typing import Any, Callable, Iterable, List, Optional, Dict
from typing import get_origin, get_args, Annotated as _Annotated
import asyncio
import contextvars
import weakref

import importlib
import time
_core = importlib.import_module("_fastdi_core")


def _make_key(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if callable(obj):
        mod = getattr(obj, "__module__", "__unknown__")
        qn = getattr(obj, "__qualname__", getattr(obj, "__name__", str(obj)))
        return f"{mod}:{qn}"
    return str(obj)


class Depends:
    def __init__(self, target: Any):
        self.key = _make_key(target)

    def __repr__(self) -> str:
        return f"Depends({self.key})"


def _extract_dep_keys(func: Callable[..., Any]) -> List[str]:
    sig = inspect.signature(func)
    dep_keys: List[str] = []
    for p in sig.parameters.values():
        default = p.default
        if isinstance(default, Depends):
            dep_keys.append(default.key)
            continue
        # Default is Annotated[..., Depends(...)]
        if default is not inspect._empty:
            org = get_origin(default)
            if org is _Annotated:
                meta = get_args(default)[1:]
                for m in meta:
                    if isinstance(m, Depends):
                        dep_keys.append(m.key)
                        break
                continue
        # Annotation is Annotated[..., Depends(...)]
        ann = p.annotation
        if ann is not inspect._empty:
            org = get_origin(ann)
            if org is _Annotated:
                meta = get_args(ann)[1:]
                for m in meta:
                    if isinstance(m, Depends):
                        dep_keys.append(m.key)
                        break
    return dep_keys


def _resolve_keys_for_call(container: "Container", keys: Iterable[str]) -> List[Any]:
    key_list = list(keys)
    return [container._core.resolve(k) for k in key_list]


class Container:
    def __init__(self) -> None:
        self._core = _core.Container()
        # request-scope cache per task using WeakKeyDictionary for GC
        self._request_task_caches: "weakref.WeakKeyDictionary[asyncio.Task, Dict[str, Any]]" = weakref.WeakKeyDictionary()
        # Fallback context var (non-async contexts)
        self._request_cache_var: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
            "fastdi_request_cache_fallback"
        )
        # Track Python-managed scopes: key -> scope string ("transient"|"request"|"singleton")
        self._scopes: Dict[str, str] = {}
        # Observability hooks: each hook(event: str, payload: dict) -> None
        self._hooks: list[Callable[[str, Dict[str, Any]], None]] = []

    # ---------- Observability ----------
    def add_hook(self, hook: Callable[[str, Dict[str, Any]], None]) -> None:
        self._hooks.append(hook)

    def remove_hook(self, hook: Callable[[str, Dict[str, Any]], None]) -> None:
        try:
            self._hooks.remove(hook)
        except ValueError:
            pass

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        for h in list(self._hooks):
            try:
                h(event, payload)
            except Exception:
                # Hooks must not break resolution
                pass

    def register(
        self,
        key: str,
        func: Callable[..., Any],
        *,
        singleton: bool,
        dep_keys: Optional[List[str]] = None,
        scope: Optional[str] = None,
    ) -> None:
        if dep_keys is None:
            dep_keys = _extract_dep_keys(func)
        is_async = inspect.iscoroutinefunction(func)
        self._core.register_provider(key, func, bool(singleton), bool(is_async), list(dep_keys))
        if singleton:
            self._scopes[key] = "singleton"
        else:
            self._scopes[key] = scope or "transient"

    def resolve(self, key: str) -> Any:
        return self._core.resolve(key)

    def resolve_many(self, keys: Iterable[str]) -> List[Any]:
        return list(self._core.resolve_many(list(keys)))

    @contextmanager
    def override(self, key_or_callable: Any, replacement: Callable[..., Any], *, singleton: bool = False):
        key = _make_key(key_or_callable)
        dep_keys = _extract_dep_keys(replacement)
        self._core.begin_override_layer()
        try:
            is_async = inspect.iscoroutinefunction(replacement)
            self._core.set_override(key, replacement, bool(singleton), bool(is_async), dep_keys)
            yield
        finally:
            self._core.end_override_layer()

    # ---------- Async resolution path ----------
    async def resolve_async(self, key: str) -> Any:
        seen: set = set()
        return await self._resolve_key_async(key, seen)

    async def resolve_many_async(self, keys: Iterable[str]) -> List[Any]:
        out = []
        seen: set = set()
        for k in keys:
            out.append(await self._resolve_key_async(k, seen))
        return out

    async def _resolve_key_async(self, key: str, seen: set) -> Any:
        if key in seen:
            raise RuntimeError(f"Dependency cycle detected at key: {key}")
        seen.add(key)

        # Request-scope cache lookup
        scope = self._scopes.get(key, "transient")
        if scope == "request":
            cache = None
            task = asyncio.current_task()
            if task is not None:
                cache = self._request_task_caches.get(task)
                if cache is None:
                    cache = {}
                    self._request_task_caches[task] = cache
            else:
                try:
                    cache = self._request_cache_var.get()
                except LookupError:
                    cache = {}
                    self._request_cache_var.set(cache)
            if cache is not None and key in cache:
                seen.remove(key)
                return cache[key]

        callable_obj, singleton, is_async, dep_keys = self._core.get_provider_info(key)

        # Singleton cache check (Rust-managed)
        if singleton:
            cached = self._core.get_cached(key)
            if cached is not None:
                seen.remove(key)
                return cached

        # Resolve dependencies first
        args = []
        for dep in dep_keys:
            args.append(await self._resolve_key_async(dep, seen))

        # Call provider
        start = time.perf_counter()
        self._emit("provider_start", {"key": key, "async": is_async})
        res = callable_obj(*args)
        if is_async:
            res = await res
        dur = time.perf_counter() - start
        self._emit("provider_end", {"key": key, "async": is_async, "duration_s": dur})

        # Cache
        if singleton:
            self._core.set_cached(key, res)
        elif scope == "request":
            task = asyncio.current_task()
            if task is not None:
                cache = self._request_task_caches.get(task)
                if cache is None:
                    cache = {}
                    self._request_task_caches[task] = cache
            else:
                try:
                    cache = self._request_cache_var.get()
                except LookupError:
                    cache = {}
                    self._request_cache_var.set(cache)
            cache[key] = res

        seen.remove(key)
        return res

    # ---------- Plan compilation (topological) ----------
    def _build_plan(self, root_keys: List[str], *, allow_async: bool) -> tuple[List[str], Dict[str, List[str]], bool]:
        # Returns (order, deps_map, has_async)
        deps_map: Dict[str, List[str]] = {}
        state: Dict[str, int] = {}  # 0=unseen,1=visiting,2=done
        order: list[str] = []
        has_async = False

        def visit(k: str):
            nonlocal has_async
            st = state.get(k, 0)
            if st == 1:
                raise RuntimeError(f"Dependency cycle detected at key: {k}")
            if st == 2:
                return
            state[k] = 1

            callable_obj, singleton, is_async, dep_keys = self._core.get_provider_info(k)
            # store deps
            deps = list(dep_keys)
            deps_map[k] = deps
            if is_async:
                has_async = True
            for d in deps:
                visit(d)
            state[k] = 2
            order.append(k)

        for rk in root_keys:
            visit(rk)

        if not allow_async and has_async:
            raise RuntimeError("Async provider found in sync plan; use @ainject")
        # order is postorder; ensure dependencies come before dependents already
        # but we built it as postorder appends after visiting children, so it is valid
        return order, deps_map, has_async

    async def _run_plan_async(self, order: List[str], deps_map: Dict[str, List[str]]) -> Dict[str, Any]:
        computed: Dict[str, Any] = {}
        for key in order:
            # Check caches
            scope = self._scopes.get(key, "transient")
            if scope == "request":
                task = asyncio.current_task()
                cache = None
                if task is not None:
                    cache = self._request_task_caches.get(task)
                if cache and key in cache:
                    self._emit("cache_hit", {"key": key, "scope": "request"})
                    computed[key] = cache[key]
                    continue

            # provider info
            callable_obj, singleton, is_async, dep_keys = self._core.get_provider_info(key)
            if singleton:
                cached = self._core.get_cached(key)
                if cached is not None:
                    self._emit("cache_hit", {"key": key, "scope": "singleton"})
                    computed[key] = cached
                    continue

            # Resolve deps from computed
            args = [computed[d] for d in deps_map.get(key, [])]

            start = time.perf_counter()
            self._emit("provider_start", {"key": key, "async": is_async})
            res = callable_obj(*args)
            if is_async:
                res = await res
            dur = time.perf_counter() - start
            self._emit("provider_end", {"key": key, "async": is_async, "duration_s": dur})

            if singleton:
                self._core.set_cached(key, res)
            elif scope == "request":
                task = asyncio.current_task()
                if task is not None:
                    cache = self._request_task_caches.get(task)
                    if cache is None:
                        cache = {}
                        self._request_task_caches[task] = cache
                    cache[key] = res
                else:
                    # fallback
                    try:
                        cache = self._request_cache_var.get()
                    except LookupError:
                        cache = {}
                        self._request_cache_var.set(cache)
                    cache[key] = res
            computed[key] = res
        return computed


def provide(
    container: Container,
    *,
    singleton: bool = False,
    key: Optional[str] = None,
    scope: Optional[str] = None,
):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        k = key or _make_key(func)
        dep_keys = _extract_dep_keys(func)
        container.register(k, func, singleton=singleton, dep_keys=dep_keys, scope=scope)
        return func
    return decorator


def inject(container: Container):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        dep_keys = _extract_dep_keys(func)
        # compile plan now to detect cycles and lock order
        order, deps_map, has_async = container._build_plan(dep_keys, allow_async=False)

        def wrapper(*args: Any, **kwargs: Any):
            # For sync path, still use core recursion for now, but pre-validated
            values = container.resolve_many(dep_keys)
            return func(*values)

        # Copy metadata
        try:
            wrapper.__name__ = func.__name__  # type: ignore[attr-defined]
            wrapper.__doc__ = func.__doc__
            wrapper.__module__ = func.__module__
        except Exception:
            pass
        return wrapper
    return decorator


def ainject(container: Container):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@ainject can only wrap async functions")
        dep_keys = _extract_dep_keys(func)
        order, deps_map, _ = container._build_plan(dep_keys, allow_async=True)

        async def wrapper(*args: Any, **kwargs: Any):
            computed = await container._run_plan_async(order, deps_map)
            values = [computed[k] for k in dep_keys]
            return await func(*values)

        try:
            wrapper.__name__ = func.__name__  # type: ignore[attr-defined]
            wrapper.__doc__ = func.__doc__
            wrapper.__module__ = func.__module__
        except Exception:
            pass
        return wrapper
    return decorator
