"""Public decorators: provide, inject, ainject.

These decorators form the main user-facing API for FastDI and are documented so
they render well under MkDocs.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from .container import Container
from .types import Key, Scope, extract_dep_keys, extract_dep_params, make_key

P = ParamSpec("P")
R = TypeVar("R")


def provide(
    container: Container,
    *,
    singleton: bool = False,
    key: Key | None = None,
    scope: Scope | None = None,
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
    the Rust core resolver. The resulting wrapper preserves the original
    signature, filling ``Annotated[..., Depends(...)]`` parameters when they
    are not provided explicitly.
    """

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        dep_params = extract_dep_params(func)
        dep_keys = [key for _, key in dep_params]
        sig = inspect.signature(func)
        # compile/validate now and capture epoch
        plan = container._build_plan(dep_keys, allow_async=False)
        validated_epoch = container._epoch

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> R:
            nonlocal validated_epoch, plan
            # Re-validate on epoch change
            if container._epoch != validated_epoch:
                plan = container._build_plan(dep_keys, allow_async=False)
                validated_epoch = container._epoch

            if not dep_params:
                return func(*args, **kwargs)

            bound = sig.bind_partial(*args, **kwargs)
            missing = [(name, key) for name, key in dep_params if name not in bound.arguments]
            if missing:
                keys_to_resolve = [key for _, key in missing]
                resolved = container._core.resolve_many_plan(keys_to_resolve)
                for (name, _), value in zip(missing, resolved, strict=False):
                    bound.arguments[name] = value
            return func(*bound.args, **bound.kwargs)

        return wrapper

    return decorator


def ainject(container: Container):
    """Decorator for async call sites.

    Compiles a plan and executes it iteratively in topological order. The
    resulting wrapper preserves the original signature, resolving
    ``Annotated[..., Depends(...)]`` parameters when missing before awaiting
    the original function.
    """

    def decorator(func: Callable[..., Awaitable[R]]) -> Callable[..., Coroutine[Any, Any, R]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@ainject can only wrap async functions")
        dep_params = extract_dep_params(func)
        dep_keys = [key for _, key in dep_params]
        sig = inspect.signature(func)
        plan = container._build_plan(dep_keys, allow_async=True)
        plan_epoch = container._epoch

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> R:
            nonlocal plan, plan_epoch
            if container._epoch != plan_epoch:
                plan = container._build_plan(dep_keys, allow_async=True)
                plan_epoch = container._epoch

            if not dep_params:
                return await func(*args, **kwargs)

            bound = sig.bind_partial(*args, **kwargs)
            missing = [(name, key) for name, key in dep_params if name not in bound.arguments]
            if missing:
                computed = await container._run_plan_async(plan)
                for name, key in missing:
                    bound.arguments[name] = computed[key]
            return await func(*bound.args, **bound.kwargs)

        return wrapper

    return decorator


def inject_method(container: Container):
    """Decorator for sync instance methods that need injection.

    The resulting wrapper expects to be called as a bound method (i.e., with
    ``self``). Dependencies declared with ``Depends`` are injected and passed
    positionally after ``self``.
    """

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        dep_params = extract_dep_params(func)
        dep_keys = [key for _, key in dep_params]
        sig = inspect.signature(func)
        plan = container._build_plan(dep_keys, allow_async=False)
        validated_epoch = container._epoch

        @wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> R:
            nonlocal plan, validated_epoch
            if container._epoch != validated_epoch:
                plan = container._build_plan(dep_keys, allow_async=False)
                validated_epoch = container._epoch

            if not dep_params:
                return func(self, *args, **kwargs)

            bound = sig.bind_partial(self, *args, **kwargs)
            missing = [(name, key) for name, key in dep_params if name not in bound.arguments]
            if missing:
                keys_to_resolve = [key for _, key in missing]
                resolved = container._core.resolve_many_plan(keys_to_resolve)
                for (name, _), value in zip(missing, resolved, strict=False):
                    bound.arguments[name] = value
            return func(*bound.args, **bound.kwargs)

        return wrapper

    return decorator


def ainject_method(container: Container):
    """Decorator for async instance methods that need injection.

    The resulting wrapper expects to be called as a bound method (i.e., with
    ``self``). Dependencies declared with ``Depends`` are injected and passed
    positionally after ``self``.
    """

    def decorator(func: Callable[..., Awaitable[R]]) -> Callable[..., Coroutine[Any, Any, R]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@ainject_method can only wrap async methods")
        dep_params = extract_dep_params(func)
        dep_keys = [key for _, key in dep_params]
        sig = inspect.signature(func)
        plan = container._build_plan(dep_keys, allow_async=True)
        plan_epoch = container._epoch

        @wraps(func)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> R:
            nonlocal plan, plan_epoch
            if container._epoch != plan_epoch:
                plan = container._build_plan(dep_keys, allow_async=True)
                plan_epoch = container._epoch

            if not dep_params:
                return await func(self, *args, **kwargs)

            bound = sig.bind_partial(self, *args, **kwargs)
            missing = [(name, key) for name, key in dep_params if name not in bound.arguments]
            if missing:
                computed = await container._run_plan_async(plan)
                for name, key in missing:
                    bound.arguments[name] = computed[key]
            return await func(*bound.args, **bound.kwargs)

        return wrapper

    return decorator
