"""Optional Rust backend adapter for FastDI containers.

This module exposes ``RustContainer`` which mirrors the Python default but
backs execution with the compiled ``_fastdi_core`` extension when it is
installed. Importing the module is safe even if the extension is missing; use
``is_available()`` to probe availability before instantiating the adapter.
"""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import importlib.util
import time
import weakref
from collections.abc import Callable, Iterable
from contextlib import suppress
from typing import Any

from ._hooks import emit_hooks
from ._python_core import Plan
from .container import Container
from .types import Hook, Key, Scope

__all__ = ["RustContainer", "is_available"]


_MISSING_BACKEND_MSG = (
    "Rust backend not available. Install with `pip install fastdi-core[rust]` to enable the compiled implementation."
)


def is_available() -> bool:
    """Return ``True`` if the optional Rust extension is importable."""

    return importlib.util.find_spec("_fastdi_core") is not None


def _load_rust_module():
    try:
        return importlib.import_module("_fastdi_core")
    except ModuleNotFoundError as exc:  # pragma: no cover - defensive
        raise RuntimeError(_MISSING_BACKEND_MSG) from exc


class RustContainerCore:
    """Core adapter that forwards to the compiled `_fastdi_core` module."""

    def __init__(self) -> None:
        module = _load_rust_module()
        self._inner = module.Container()
        self._hooks: list[Hook] = []
        self._scopes: dict[Key, Scope] = {}
        self._task_caches: weakref.WeakKeyDictionary[asyncio.Task[Any], dict[Key, Any]] = weakref.WeakKeyDictionary()
        self._fallback_cache: contextvars.ContextVar[dict[Key, Any]] = contextvars.ContextVar(
            "fastdi_rust_request_cache"
        )
        self._epoch: int = 0

    # ------------------------------------------------------------------ helpers --
    def _bump_epoch(self) -> None:
        self._epoch += 1

    # HUMAN: Duplicated in the _python_core.py:69
    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        emit_hooks(self._hooks, event, payload)

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

    def _resolve_record(self, key: Key) -> tuple[Callable[..., Any], bool, bool, list[Key]]:
        try:
            return self._inner.get_provider_info(key)
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"No provider registered for key: {key}") from exc

    def _build_plan(self, root_keys: Iterable[Key]) -> Plan:
        roots = tuple(root_keys)
        if not roots:
            return Plan(order=(), deps={}, has_async=False, roots=())

        deps: dict[Key, list[Key]] = {}
        state: dict[Key, int] = {}
        order: list[Key] = []
        has_async = False

        for root in roots:
            if state.get(root, 0) == 2:
                continue
            stack: list[tuple[Key, int]] = [(root, 0)]
            while stack:
                key, phase = stack.pop()
                seen = state.get(key, 0)
                if phase == 0:
                    if seen == 1:
                        raise RuntimeError(f"Dependency cycle detected at key: {key}")
                    if seen == 2:
                        continue
                    state[key] = 1
                    _func, _singleton, is_async, dep_keys = self._resolve_record(key)
                    deps[key] = list(dep_keys)
                    if is_async:
                        has_async = True
                    stack.append((key, 1))
                    for dep in reversed(dep_keys):
                        if state.get(dep, 0) != 2:
                            stack.append((dep, 0))
                else:
                    state[key] = 2
                    order.append(key)

        return Plan(order=tuple(order), deps={k: tuple(v) for k, v in deps.items()}, has_async=has_async, roots=roots)

    # --------------------------------------------------------------------- hooks --
    def add_hook(self, hook: Hook) -> None:
        self._hooks.append(hook)

    def remove_hook(self, hook: Hook) -> None:
        with suppress(ValueError):
            self._hooks.remove(hook)

    # ---------------------------------------------------------- registration ----
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
        self._inner.register_provider(key, func, bool(singleton), bool(is_async), list(dep_keys))
        self._scopes[key] = "singleton" if singleton else (scope or "transient")
        self._invalidate_request_cache(key)
        self._bump_epoch()

    def begin_override_layer(self) -> None:
        self._inner.begin_override_layer()
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
        self._inner.set_override(key, func, bool(singleton), bool(is_async), list(dep_keys))
        self._invalidate_request_cache(key)
        self._bump_epoch()

    def end_override_layer(self) -> None:
        self._inner.end_override_layer()
        self._bump_epoch()

    # -------------------------------------------------------------- resolution --
    def resolve(self, key: Key) -> Any:
        return self._inner.resolve(key)

    def resolve_many(self, keys: Iterable[Key]) -> list[Any]:
        return list(self._inner.resolve_many(list(keys)))

    def resolve_many_plan(self, keys: Iterable[Key]) -> list[Any]:
        return list(self._inner.resolve_many_plan(list(keys)))

    async def resolve_async(self, key: Key) -> Any:
        results = await self.resolve_many_async([key])
        return results[0]

    async def resolve_many_async(self, keys: Iterable[Key]) -> list[Any]:
        plan = self._build_plan(keys)
        computed = await self.run_plan_async(plan)
        return [computed[root] for root in plan.roots]

    # -------------------------------------------------------------- plan ops ----
    def compile_plan(self, root_keys: Iterable[Key]) -> Plan:
        return self._build_plan(root_keys)

    async def run_plan_async(self, plan: Plan) -> dict[Key, Any]:
        computed: dict[Key, Any] = {}
        for key in plan.order:
            scope = self._scopes.get(key, "transient")
            if scope == "request":
                cache = self._get_request_cache()
                if key in cache:
                    self._emit("cache_hit", {"key": key, "scope": "request"})
                    computed[key] = cache[key]
                    continue

            func, singleton, is_async, _ = self._resolve_record(key)
            if singleton:
                cached = self._inner.get_cached(key)
                if cached is not None:
                    self._emit("cache_hit", {"key": key, "scope": "singleton"})
                    computed[key] = cached
                    continue

            args = [computed[d] for d in plan.deps.get(key, ())]
            start = time.perf_counter()
            self._emit("provider_start", {"key": key, "async": is_async})
            result = func(*args)
            if is_async:
                result = await result
            self._emit(
                "provider_end",
                {"key": key, "async": is_async, "duration_s": time.perf_counter() - start},
            )

            if singleton:
                self._inner.set_cached(key, result)
            elif scope == "request":
                cache = self._get_request_cache()
                cache[key] = result

            computed[key] = result

        return computed

    # ------------------------------------------------------------------ metadata --
    @property
    def epoch(self) -> int:
        return self._epoch


class RustContainer(Container):
    """Container that opts into the experimental Rust backend."""

    def __init__(self) -> None:
        if not is_available():
            raise RuntimeError(_MISSING_BACKEND_MSG)
        super().__init__(core=RustContainerCore())
