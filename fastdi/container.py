"""FastDI Container and execution utilities.

The default container delegates to the pure-Python core implementation so that
users can run without compiling the optional Rust extension. The API remains
compatible with the previous wrapper while leaning on ``PythonContainerCore``
for provider registration, overrides, hooks, scopes, and plan execution.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from typing import Any, Protocol

from ._python_core import Plan, PythonContainerCore
from .types import Hook, Key, Scope, extract_dep_keys, make_key


class ContainerCore(Protocol):
    """Protocol describing the functionality required by ``Container``."""

    def add_hook(self, hook: Hook) -> None: ...
    def remove_hook(self, hook: Hook) -> None: ...

    def register_provider(
        self,
        key: Key,
        func: Callable[..., Any],
        singleton: bool,
        is_async: bool,
        dep_keys: Iterable[Key],
        *,
        scope: Scope | None = None,
    ) -> None: ...

    def begin_override_layer(self) -> None: ...
    def set_override(
        self,
        key: Key,
        func: Callable[..., Any],
        singleton: bool,
        is_async: bool,
        dep_keys: Iterable[Key],
        *,
        scope: Scope | None = None,
    ) -> None: ...
    def end_override_layer(self) -> None: ...

    def resolve(self, key: Key) -> Any: ...
    def resolve_many(self, keys: Iterable[Key]) -> list[Any]: ...
    def resolve_many_plan(self, keys: Iterable[Key]) -> list[Any]: ...

    async def resolve_async(self, key: Key) -> Any: ...
    async def resolve_many_async(self, keys: Iterable[Key]) -> list[Any]: ...

    def compile_plan(self, root_keys: Iterable[Key]) -> Plan: ...
    async def run_plan_async(self, plan: Plan) -> dict[Key, Any]: ...

    @property
    def epoch(self) -> int: ...


class Container:
    """User-facing dependency injection container backed by Python primitives."""

    def __init__(self, *, core: ContainerCore | None = None) -> None:
        self._core: ContainerCore = core or PythonContainerCore()

    # ---- Hooks -----------------------------------------------------------------
    def add_hook(self, hook: Hook) -> None:
        """Register an observability hook."""

        self._core.add_hook(hook)

    def remove_hook(self, hook: Hook) -> None:
        """Unregister a previously added hook."""

        self._core.remove_hook(hook)

    # ---- Registration & overrides ---------------------------------------------
    def register(
        self,
        key: Key,
        func: Callable[..., Any],
        *,
        singleton: bool,
        dep_keys: list[Key] | None = None,
        scope: Scope | None = None,
    ) -> None:
        if dep_keys is None:
            dep_keys = extract_dep_keys(func)
        is_async = inspect.iscoroutinefunction(func)
        self._core.register_provider(
            key,
            func,
            bool(singleton),
            bool(is_async),
            dep_keys,
            scope=scope,
        )

    @contextmanager
    def override(self, key_or_callable: Any, replacement: Callable[..., Any], *, singleton: bool = False):
        key = make_key(key_or_callable)
        dep_keys = extract_dep_keys(replacement)
        self._core.begin_override_layer()
        try:
            is_async = inspect.iscoroutinefunction(replacement)
            self._core.set_override(
                key,
                replacement,
                bool(singleton),
                bool(is_async),
                dep_keys,
            )
            yield
        finally:
            self._core.end_override_layer()

    # ---- Sync resolution -------------------------------------------------------
    def resolve(self, key: Key) -> Any:
        return self._core.resolve(key)

    def resolve_many(self, keys: Iterable[Key]) -> list[Any]:
        return list(self._core.resolve_many(list(keys)))

    # ---- Async resolution ------------------------------------------------------
    async def resolve_async(self, key: Key) -> Any:
        return await self._core.resolve_async(key)

    async def resolve_many_async(self, keys: Iterable[Key]) -> list[Any]:
        return await self._core.resolve_many_async(list(keys))

    # ---- Plan compilation helpers ---------------------------------------------
    def _build_plan(self, root_keys: Iterable[Key], *, allow_async: bool) -> Plan:
        plan = self._core.compile_plan(list(root_keys))
        if not allow_async and plan.has_async:
            raise RuntimeError("Async provider found in sync plan; use @ainject")
        return plan

    async def _run_plan_async(self, plan: Plan) -> dict[Key, Any]:
        return await self._core.run_plan_async(plan)

    # ---- Epoch proxy -----------------------------------------------------------
    @property
    def _epoch(self) -> int:  # pragma: no cover - convenience bridge
        return self._core.epoch
