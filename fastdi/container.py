"""FastDI Container and execution utilities.

This module wraps the PyO3 Rust core with a maintainable, typed Python API.
It provides scopes, overrides, observability hooks, async resolution, and
topological plan compilation for async execution.
"""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Literal, cast

from .types import Key, Scope, Hook, CoreContainerProto, extract_dep_keys, make_key

_core = importlib.import_module("_fastdi_core")


@dataclass(frozen=True)
class _Plan:
    """Compiled resolution plan for a set of roots.

    Attributes:
        order: Topologically sorted keys; dependencies appear before dependents.
        deps: Mapping of key -> list of dependency keys.
        has_async: Whether any provider in the plan is async.
    """

    order: List[Key]
    deps: Dict[Key, List[Key]]
    has_async: bool


class Container:
    """User-facing DI container.

    Provides registration, overrides, scopes, hooks, and resolution helpers.
    The heavy lifting (caching, provider invocation, overrides storage) happens
    in the Rust core. This Python wrapper adds ergonomics and async tooling.
    """

    def __init__(self) -> None:
        # Typed reference to the PyO3 core container.
        self._core: CoreContainerProto = cast(CoreContainerProto, _core.Container())

        # Request-scope cache per asyncio Task; GC-friendly via WeakKeyDictionary.
        self._task_caches: "weakref.WeakKeyDictionary[asyncio.Task, Dict[str, Any]]" = (
            weakref.WeakKeyDictionary()
        )
        # Fallback ContextVar for non-async contexts.
        self._fallback_cache: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
            "fastdi_request_cache_fallback"
        )

        # Python-managed scope registry: key -> scope
        self._scopes: Dict[Key, Scope] = {}

        # Observability hooks
        self._hooks: List[Hook] = []

        # Container epoch: increments on graph mutations (register/override).
        self._epoch: int = 0

    # ---- Epoch management ------------------------------------------------------
    def _bump_epoch(self) -> None:
        """Increment the container epoch to invalidate compiled plans."""
        self._epoch += 1

    # ---- Hooks -----------------------------------------------------------------
    def add_hook(self, hook: Hook) -> None:
        """Register an observability hook.

        The hook is called as ``hook(event: str, payload: dict)`` for events
        like ``provider_start``, ``provider_end``, and ``cache_hit``.
        """

        self._hooks.append(hook)

    def remove_hook(self, hook: Hook) -> None:
        """Unregister a previously added hook.

        It is safe to call even if the hook is not currently registered.
        """

        try:
            self._hooks.remove(hook)
        except ValueError:
            pass

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        for h in list(self._hooks):
            try:
                h(event, payload)
            except Exception:
                # Hooks must never break resolution
                pass

    # ---- Registration & overrides ---------------------------------------------
    def register(
        self,
        key: Key,
        func: Callable[..., Any],
        *,
        singleton: bool,
        dep_keys: Optional[List[Key]] = None,
        scope: Optional[Scope] = None,
    ) -> None:
        """Register a provider function under a given key.

        Args:
            key: Unique provider identifier.
            func: Provider callable (sync or async).
            singleton: Cache result globally in Rust if True.
            dep_keys: Optional explicit dependency keys; inferred from signature otherwise.
            scope: Python-side scope: ``"transient"``, ``"request"``, or ``"singleton"``.
        """

        if dep_keys is None:
            dep_keys = extract_dep_keys(func)
        is_async = asyncio.iscoroutinefunction(func)
        self._core.register_provider(key, func, bool(singleton), bool(is_async), list(dep_keys))
        self._scopes[key] = "singleton" if singleton else (scope or "transient")
        self._bump_epoch()

    @contextmanager
    def override(self, key_or_callable: Any, replacement: Callable[..., Any], *, singleton: bool = False):
        """Temporarily override a provider within the context block.

        Args:
            key_or_callable: Provider key or original callable.
            replacement: Replacement provider (sync or async).
            singleton: Treat replacement as a singleton in Rust cache.
        """

        key = make_key(key_or_callable)
        dep_keys = extract_dep_keys(replacement)
        self._core.begin_override_layer()
        self._bump_epoch()
        try:
            is_async = asyncio.iscoroutinefunction(replacement)
            self._core.set_override(key, replacement, bool(singleton), bool(is_async), dep_keys)
            yield
        finally:
            self._core.end_override_layer()
            self._bump_epoch()

    # ---- Sync resolution (Rust core) -------------------------------------------
    def resolve(self, key: Key) -> Any:
        """Resolve a single key synchronously via the Rust core.

        Raises:
            KeyError: If no provider is registered for the key.
            RuntimeError: On dependency cycles or invalid graph for sync.
        """

        return self._core.resolve(key)

    def resolve_many(self, keys: Iterable[Key]) -> List[Any]:
        """Resolve multiple keys synchronously via the Rust core."""

        return list(self._core.resolve_many(list(keys)))

    # ---- Async resolution (Python executor) ------------------------------------
    async def resolve_async(self, key: Key) -> Any:
        """Resolve a single key in async mode.

        This path supports async providers, request scope, and hooks.
        """

        seen: set = set()
        return await self._resolve_key_async(key, seen)

    async def resolve_many_async(self, keys: Iterable[Key]) -> List[Any]:
        """Resolve multiple keys in async mode."""

        seen: set = set()
        return [await self._resolve_key_async(k, seen) for k in keys]

    def _get_or_create_request_cache(self) -> Dict[str, Any]:
        task = asyncio.current_task()
        if task is not None:
            cache = self._task_caches.get(task)
            if cache is None:
                cache = {}
                self._task_caches[task] = cache
            return cache
        try:
            return self._fallback_cache.get()
        except LookupError:
            cache = {}
            self._fallback_cache.set(cache)
            return cache

    async def _resolve_key_async(self, key: Key, seen: set) -> Any:
        if key in seen:
            raise RuntimeError(f"Dependency cycle detected at key: {key}")
        seen.add(key)

        # Request-scope cache lookup
        scope = self._scopes.get(key, "transient")
        if scope == "request":
            cache = self._get_or_create_request_cache()
            if key in cache:
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
        args = [await self._resolve_key_async(dep, seen) for dep in dep_keys]

        # Call provider
        start = time.perf_counter()
        self._emit("provider_start", {"key": key, "async": is_async})
        res = callable_obj(*args)
        if is_async:
            res = await res
        self._emit("provider_end", {"key": key, "async": is_async, "duration_s": time.perf_counter() - start})

        # Cache
        if singleton:
            self._core.set_cached(key, res)
        elif scope == "request":
            cache = self._get_or_create_request_cache()
            cache[key] = res

        seen.remove(key)
        return res

    # ---- Plan compilation (topological) ----------------------------------------
    def _build_plan(self, root_keys: List[Key], *, allow_async: bool) -> _Plan:
        """Compile a dependency plan for the given root keys.

        Uses an iterative DFS to avoid Python recursion limits on deep graphs.
        Returns a topologically sorted order and dependency map. Fails early on
        cycles or the presence of async providers in a sync-only plan.
        """

        deps: Dict[Key, List[Key]] = {}
        state: Dict[Key, int] = {}
        order: List[Key] = []
        has_async = False

        for root in root_keys:
            if state.get(root, 0) == 2:
                continue
            stack: List[Tuple[Key, int]] = [(root, 0)]  # (key, phase 0=enter,1=exit)
            while stack:
                k, phase = stack.pop()
                st = state.get(k, 0)
                if phase == 0:
                    if st == 1:
                        raise RuntimeError(f"Dependency cycle detected at key: {k}")
                    if st == 2:
                        continue
                    state[k] = 1
                    _, _, is_async, dep_keys = self._core.get_provider_info(k)
                    dlist = list(dep_keys)
                    deps[k] = dlist
                    if is_async:
                        has_async = True
                    stack.append((k, 1))
                    for d in reversed(dlist):
                        if state.get(d, 0) != 2:
                            stack.append((d, 0))
                else:
                    state[k] = 2
                    order.append(k)

        if not allow_async and has_async:
            raise RuntimeError("Async provider found in sync plan; use @ainject")
        return _Plan(order=order, deps=deps, has_async=has_async)

    async def _run_plan_async(self, plan: _Plan) -> Dict[Key, Any]:
        """Execute a compiled plan in async mode.

        Computes each node once, honoring singleton/request caches and emitting
        observability events.
        """

        computed: Dict[Key, Any] = {}
        for key in plan.order:
            scope = self._scopes.get(key, "transient")
            if scope == "request":
                cache = self._get_or_create_request_cache()
                if key in cache:
                    self._emit("cache_hit", {"key": key, "scope": "request"})
                    computed[key] = cache[key]
                    continue

            callable_obj, singleton, is_async, _ = self._core.get_provider_info(key)
            if singleton:
                cached = self._core.get_cached(key)
                if cached is not None:
                    self._emit("cache_hit", {"key": key, "scope": "singleton"})
                    computed[key] = cached
                    continue

            args = [computed[d] for d in plan.deps.get(key, [])]
            start = time.perf_counter()
            self._emit("provider_start", {"key": key, "async": is_async})
            res = callable_obj(*args)
            if is_async:
                res = await res
            self._emit("provider_end", {"key": key, "async": is_async, "duration_s": time.perf_counter() - start})

            if singleton:
                self._core.set_cached(key, res)
            elif scope == "request":
                cache = self._get_or_create_request_cache()
                cache[key] = res

            computed[key] = res

        return computed
