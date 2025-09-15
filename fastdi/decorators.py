"""Public decorators: provide, inject, ainject.

These decorators form the main user-facing API for FastDI and are documented so
they render well under MkDocs.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, List, Optional, TypeVar, ParamSpec

from .container import Container
from .types import Key, Scope, extract_dep_keys, make_key


P = ParamSpec("P")
R = TypeVar("R")


def provide(
    container: Container,
    *,
    singleton: bool = False,
    key: Optional[Key] = None,
    scope: Optional[Scope] = None,
):
    """Register a function as a provider.

    The decorated function is returned unchanged, allowing direct invocation in
    tests if desired.

    Args:
        container: Target DI container where the provider will be registered.
        singleton: Cache result globally (Rust cache) on first computation.
        key: Optional explicit registration key; by default derived from the function.
        scope: Optional Python-managed scope ("transient" or "request").
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        k = key or make_key(func)
        dep_keys = extract_dep_keys(func)
        container.register(k, func, singleton=singleton, dep_keys=dep_keys, scope=scope)
        return func

    return decorator


def inject(container: Container):
    """Decorator for sync call sites.

    Compiles and validates a plan at decoration time and executes the call via
    the Rust core resolver. The resulting wrapper takes no arguments; it will
    resolve dependencies and pass them positionally to the original function.
    """

    def decorator(func: Callable[..., R]) -> Callable[[], R]:
        dep_keys = extract_dep_keys(func)
        # compile/validate now and capture epoch
        plan = container._build_plan(dep_keys, allow_async=False)
        validated_epoch = container._epoch

        def wrapper() -> R:
            nonlocal validated_epoch, plan
            # Re-validate on epoch change
            if container._epoch != validated_epoch:
                plan = container._build_plan(dep_keys, allow_async=False)
                validated_epoch = container._epoch
            # Use Rust plan executor for sync path
            values = list(container._core.resolve_many_plan(list(dep_keys)))
            return func(*values)  # type: ignore[misc]

        try:
            wrapper.__name__ = func.__name__  # type: ignore[attr-defined]
            wrapper.__doc__ = func.__doc__
            wrapper.__module__ = func.__module__
        except Exception:
            pass
        return wrapper

    return decorator


def ainject(container: Container):
    """Decorator for async call sites.

    Compiles a plan and executes it iteratively in topological order. The
    resulting wrapper takes no arguments; it will resolve dependencies, then
    await the original function with injected values.
    """

    def decorator(func: Callable[..., Awaitable[R]]) -> Callable[[], Awaitable[R]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@ainject can only wrap async functions")
        dep_keys = extract_dep_keys(func)
        plan = container._build_plan(dep_keys, allow_async=True)
        plan_epoch = container._epoch

        async def wrapper() -> R:
            nonlocal plan, plan_epoch
            if container._epoch != plan_epoch:
                plan = container._build_plan(dep_keys, allow_async=True)
                plan_epoch = container._epoch
            computed = await container._run_plan_async(plan)
            values = [computed[k] for k in dep_keys]
            return await func(*values)  # type: ignore[misc]

        try:
            wrapper.__name__ = func.__name__  # type: ignore[attr-defined]
            wrapper.__doc__ = func.__doc__
            wrapper.__module__ = func.__module__
        except Exception:
            pass
        return wrapper

    return decorator


def inject_method(container: Container):
    """Decorator for sync instance methods that need injection.

    The resulting wrapper expects to be called as a bound method (i.e., with
    ``self``). Dependencies declared with ``Depends`` are injected and passed
    positionally after ``self``.
    """

    def decorator(func: Callable[..., R]) -> Callable[[Any], R]:
        dep_keys = extract_dep_keys(func)
        plan = container._build_plan(dep_keys, allow_async=False)
        validated_epoch = container._epoch

        def wrapper(self: Any) -> R:
            nonlocal plan, validated_epoch
            if container._epoch != validated_epoch:
                plan = container._build_plan(dep_keys, allow_async=False)
                validated_epoch = container._epoch
            values = list(container._core.resolve_many_plan(list(dep_keys)))
            return func(self, *values)  # type: ignore[misc]

        try:
            wrapper.__name__ = func.__name__  # type: ignore[attr-defined]
            wrapper.__doc__ = func.__doc__
            wrapper.__module__ = func.__module__
        except Exception:
            pass
        return wrapper

    return decorator


def ainject_method(container: Container):
    """Decorator for async instance methods that need injection.

    The resulting wrapper expects to be called as a bound method (i.e., with
    ``self``). Dependencies declared with ``Depends`` are injected and passed
    positionally after ``self``.
    """

    def decorator(func: Callable[..., Awaitable[R]]) -> Callable[[Any], Awaitable[R]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@ainject_method can only wrap async methods")
        dep_keys = extract_dep_keys(func)
        plan = container._build_plan(dep_keys, allow_async=True)
        plan_epoch = container._epoch

        async def wrapper(self: Any) -> R:
            nonlocal plan, plan_epoch
            if container._epoch != plan_epoch:
                plan = container._build_plan(dep_keys, allow_async=True)
                plan_epoch = container._epoch
            computed = await container._run_plan_async(plan)
            values = [computed[k] for k in dep_keys]
            return await func(self, *values)  # type: ignore[misc]

        try:
            wrapper.__name__ = func.__name__  # type: ignore[attr-defined]
            wrapper.__doc__ = func.__doc__
            wrapper.__module__ = func.__module__
        except Exception:
            pass
        return wrapper

    return decorator
