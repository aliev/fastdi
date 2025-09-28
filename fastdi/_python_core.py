"""Pure-Python execution engine for FastDI containers.

This module mirrors the behavior of the Rust extension so the default
installation can operate without compiled code. It manages provider
registration, override layers, singleton/request caches, observability hooks,
and graph compilation powered by ``graphlib.TopologicalSorter``.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
import weakref
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from typing import Any

from ._hooks import emit_hooks
from .types import Hook, Key, Scope

__all__ = ["PythonContainerCore", "Plan"]


@dataclass(slots=True)
class _ProviderRecord:
    """Book-keeping for a registered provider."""

    func: Callable[..., Any]
    singleton: bool
    is_async: bool
    scope: Scope
    dep_keys: tuple[Key, ...]


@dataclass(slots=True)
class Plan:
    """Compiled plan describing dependency execution order."""

    order: tuple[Key, ...]
    deps: dict[Key, tuple[Key, ...]]
    has_async: bool
    roots: tuple[Key, ...]


class PythonContainerCore:
    """In-memory provider engine with parity to the Rust backend."""

    def __init__(self) -> None:
        self._providers: dict[Key, _ProviderRecord] = {}
        self._override_stack: list[dict[Key, _ProviderRecord]] = []
        self._singleton_cache: dict[Key, Any] = {}
        self._task_caches: weakref.WeakKeyDictionary[asyncio.Task[Any], dict[Key, Any]] = weakref.WeakKeyDictionary()
        self._fallback_cache: contextvars.ContextVar[dict[Key, Any]] = contextvars.ContextVar(
            "fastdi_python_core_request_cache"
        )
        self._hooks: list[Hook] = []
        self._epoch: int = 0

    # ------------------------------------------------------------------ hooks --
    def add_hook(self, hook: Hook) -> None:
        self._hooks.append(hook)

    def remove_hook(self, hook: Hook) -> None:
        with suppress(ValueError):
            self._hooks.remove(hook)

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        emit_hooks(self._hooks, event, payload)

    # ---------------------------------------------------------- registration --
    def register_provider(
        self,
        key: Key,
        func: Callable[..., Any],
        singleton: bool,
        is_async: bool,
        dep_keys: Iterable[Key],
        *,
        scope: Scope | None = None,
    ) -> None:
        """Register or replace a provider under ``key``."""

        normalized_scope = "singleton" if singleton else (scope or "transient")
        record = _ProviderRecord(
            func=func,
            singleton=bool(singleton),
            is_async=bool(is_async),
            scope=normalized_scope,
            dep_keys=tuple(dep_keys),
        )
        self._providers[key] = record
        self._invalidate_caches(key)
        self._bump_epoch()

    # -------------------------------------------------------------- overrides --
    def begin_override_layer(self) -> None:
        self._override_stack.append({})
        self._bump_epoch()

    def set_override(
        self,
        key: Key,
        func: Callable[..., Any],
        singleton: bool,
        is_async: bool,
        dep_keys: Iterable[Key],
        *,
        scope: Scope | None = None,
    ) -> None:
        """Set an override in the current layer."""

        if not self._override_stack:
            raise RuntimeError("begin_override_layer must be called before set_override")
        normalized_scope = "singleton" if singleton else (scope or "transient")
        record = _ProviderRecord(
            func=func,
            singleton=bool(singleton),
            is_async=bool(is_async),
            scope=normalized_scope,
            dep_keys=tuple(dep_keys),
        )
        self._override_stack[-1][key] = record
        self._invalidate_caches(key)
        self._bump_epoch()

    def end_override_layer(self) -> None:
        if not self._override_stack:
            raise RuntimeError("No override layer to end")
        layer = self._override_stack.pop()
        for key in layer:
            self._invalidate_caches(key)
        self._bump_epoch()

    # ------------------------------------------------------------ cache utils --
    def _invalidate_caches(self, key: Key | None = None) -> None:
        if key is None:
            self._singleton_cache.clear()
            self._invalidate_request_cache()
            return
        self._singleton_cache.pop(key, None)
        self._invalidate_request_cache(key)

    def _invalidate_request_cache(self, key: Key | None = None) -> None:
        caches = list(self._task_caches.values())
        for cache in caches:
            if key is None:
                cache.clear()
            else:
                cache.pop(key, None)
        try:
            fallback = self._fallback_cache.get()
        except LookupError:
            return
        if key is None:
            fallback.clear()
        else:
            fallback.pop(key, None)

    @staticmethod
    def _create_cache() -> dict[Key, Any]:
        return {}

    def _get_request_cache(self) -> dict[Key, Any]:
        task = asyncio.current_task()
        if task is not None:
            existing = self._task_caches.get(task)
            if existing is None:
                created_cache = self._create_cache()
                self._task_caches[task] = created_cache
                return created_cache
            return existing
        try:
            return self._fallback_cache.get()
        except LookupError:
            created_cache = self._create_cache()
            self._fallback_cache.set(created_cache)
            return created_cache

    def _bump_epoch(self) -> None:
        self._epoch += 1

    # ----------------------------------------------------------- plan helpers --
    def _resolve_record(self, key: Key) -> _ProviderRecord:
        for layer in reversed(self._override_stack):
            if key in layer:
                return layer[key]
        try:
            return self._providers[key]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"No provider registered for key: {key}") from exc

    def _compile_plan(self, root_keys: Iterable[Key]) -> Plan:
        roots = tuple(root_keys)
        if not roots:
            return Plan(order=(), deps={}, has_async=False, roots=())

        sorter: TopologicalSorter[Key] = TopologicalSorter()
        deps: dict[Key, tuple[Key, ...]] = {}
        visited: set[Key] = set()
        has_async = False

        def visit(key: Key) -> None:
            nonlocal has_async
            if key in visited:
                return
            record = self._resolve_record(key)
            deps[key] = record.dep_keys
            sorter.add(key, *record.dep_keys)
            visited.add(key)
            if record.is_async:
                has_async = True
            for dep in record.dep_keys:
                visit(dep)

        for root in roots:
            visit(root)

        try:
            order = tuple(sorter.static_order())
        except CycleError as exc:
            cycle = " -> ".join(exc.args[1]) if len(exc.args) > 1 else "cycle detected"
            raise RuntimeError(f"Dependency cycle detected: {cycle}") from exc

        filtered_order = tuple(k for k in order if k in deps)
        return Plan(order=filtered_order, deps=deps, has_async=has_async, roots=roots)

    # --------------------------------------------------------- sync resolve --
    def resolve(self, key: Key) -> Any:
        return self.resolve_many([key])[0]

    def resolve_many(self, keys: Iterable[Key]) -> list[Any]:
        plan = self._compile_plan(keys)
        if plan.has_async:
            raise RuntimeError("Async provider found in sync plan; use resolve_many_async")
        computed = self._execute_plan_sync(plan)
        return [computed[root] for root in plan.roots]

    def resolve_many_plan(self, keys: Iterable[Key]) -> list[Any]:
        return self.resolve_many(keys)

    def _execute_plan_sync(self, plan: Plan) -> dict[Key, Any]:
        computed: dict[Key, Any] = {}
        for key in plan.order:
            result = self._compute_key_sync(plan, key, computed)
            computed[key] = result
        return computed

    def _compute_key_sync(self, plan: Plan, key: Key, computed: dict[Key, Any]) -> Any:
        record = self._resolve_record(key)

        if record.singleton and key in self._singleton_cache:
            value = self._singleton_cache[key]
            self._emit("cache_hit", {"key": key, "scope": "singleton"})
            return value

        if record.scope == "request":
            cache = self._get_request_cache()
            if key in cache:
                value = cache[key]
                self._emit("cache_hit", {"key": key, "scope": "request"})
                return value

        args = [computed[dep] for dep in plan.deps.get(key, ())]
        if record.is_async:
            raise RuntimeError("Async provider found in sync execution")

        start = time.perf_counter()
        self._emit("provider_start", {"key": key, "async": False})
        value = record.func(*args)
        self._emit("provider_end", {"key": key, "async": False, "duration_s": time.perf_counter() - start})

        if record.singleton:
            self._singleton_cache[key] = value
        elif record.scope == "request":
            cache = self._get_request_cache()
            cache[key] = value

        return value

    # --------------------------------------------------------- async resolve --
    async def resolve_async(self, key: Key) -> Any:
        results = await self.resolve_many_async([key])
        return results[0]

    async def resolve_many_async(self, keys: Iterable[Key]) -> list[Any]:
        plan = self._compile_plan(keys)
        computed = await self._execute_plan_async(plan)
        return [computed[root] for root in plan.roots]

    async def _execute_plan_async(self, plan: Plan) -> dict[Key, Any]:
        computed: dict[Key, Any] = {}
        for key in plan.order:
            value = await self._compute_key_async(plan, key, computed)
            computed[key] = value
        return computed

    async def _compute_key_async(self, plan: Plan, key: Key, computed: dict[Key, Any]) -> Any:
        record = self._resolve_record(key)

        if record.singleton and key in self._singleton_cache:
            value = self._singleton_cache[key]
            self._emit("cache_hit", {"key": key, "scope": "singleton"})
            return value

        if record.scope == "request":
            cache = self._get_request_cache()
            if key in cache:
                value = cache[key]
                self._emit("cache_hit", {"key": key, "scope": "request"})
                return value

        args = [computed[dep] for dep in plan.deps.get(key, ())]

        start = time.perf_counter()
        self._emit("provider_start", {"key": key, "async": record.is_async})
        value = record.func(*args)
        if record.is_async:
            value = await value
        self._emit(
            "provider_end",
            {"key": key, "async": record.is_async, "duration_s": time.perf_counter() - start},
        )

        if record.singleton:
            self._singleton_cache[key] = value
        elif record.scope == "request":
            cache = self._get_request_cache()
            cache[key] = value

        return value

    # ------------------------------------------------------------------ utils --
    def get_provider_info(self, key: Key) -> tuple[Callable[..., Any], bool, bool, list[Key]]:
        record = self._resolve_record(key)
        return record.func, record.singleton, record.is_async, list(record.dep_keys)

    def get_cached(self, key: Key) -> Any | None:
        return self._singleton_cache.get(key)

    def set_cached(self, key: Key, value: Any) -> None:
        self._singleton_cache[key] = value

    @property
    def epoch(self) -> int:
        return self._epoch

    # ----------------------------------------------------------- public plans --
    def compile_plan(self, root_keys: Iterable[Key]) -> Plan:
        return self._compile_plan(root_keys)

    def run_plan_sync(self, plan: Plan) -> dict[Key, Any]:
        return self._execute_plan_sync(plan)

    async def run_plan_async(self, plan: Plan) -> dict[Key, Any]:
        return await self._execute_plan_async(plan)
