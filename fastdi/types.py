"""Common types and helpers for FastDI.

Defines shared type aliases, the `Depends` marker, and helpers to extract
dependency metadata from callables.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Annotated, Any, Protocol, get_args, get_origin

# Public type aliases
Key = str
Scope = str  # one of: "transient", "request", "singleton"
Hook = Callable[[str, dict[str, Any]], None]


class CoreContainerProto(Protocol):
    """Protocol describing the Rust core container interface.

    This enables static typing for the PyO3-backed `_fastdi_core.Container`.
    """

    def register_provider(
        self,
        key: str,
        callable: Callable[..., Any],
        singleton: bool,
        is_async: bool,
        dep_keys: list[str],
    ) -> None: ...
    def resolve(self, key: str) -> Any: ...
    def resolve_many(self, keys: list[str]) -> list[Any]: ...
    def resolve_many_plan(self, keys: list[str]) -> list[Any]: ...
    def begin_override_layer(self) -> None: ...
    def set_override(
        self,
        key: str,
        callable: Callable[..., Any],
        singleton: bool,
        is_async: bool,
        dep_keys: list[str],
    ) -> None: ...
    def end_override_layer(self) -> None: ...
    def get_provider_info(self, key: str) -> tuple[Callable[..., Any], bool, bool, list[str]]: ...
    def get_cached(self, key: str) -> Any | None: ...
    def set_cached(self, key: str, value: Any) -> None: ...


def make_key(obj: Any) -> Key:
    """Return a stable string key for a dependency target.

    - Strings are used as-is.
    - Callables are qualified as "module:qualname".
    - Other objects fall back to ``str(obj)``.
    """
    if isinstance(obj, str):
        return obj
    if callable(obj):
        mod = getattr(obj, "__module__", "__unknown__")
        qn = getattr(obj, "__qualname__", getattr(obj, "__name__", str(obj)))
        return f"{mod}:{qn}"
    return str(obj)


class Depends:
    """Marker for declaring a dependency in a function signature.

    Prefer the Annotated-only style for clarity and static typing:

        def handler(svc: Annotated[Service, Depends(get_service)]): ...
    """

    __slots__ = ("key",)

    def __init__(self, target: Any):
        self.key = make_key(target)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Depends({self.key})"


def _extract_dep_key(annotation: Any) -> Key | None:
    """Return the dependency key encoded in an annotation, if present."""

    if annotation is inspect._empty:
        return None
    origin = get_origin(annotation)
    if origin is Annotated:
        for meta in get_args(annotation)[1:]:
            if isinstance(meta, Depends):
                return meta.key
    return None


def extract_dep_params(func: Callable[..., Any]) -> list[tuple[str, Key]]:
    """Return ``(parameter_name, dependency_key)`` pairs for ``func``."""

    sig = inspect.signature(func)
    out: list[tuple[str, Key]] = []
    for param in sig.parameters.values():
        key = _extract_dep_key(param.annotation)
        if key is not None:
            out.append((param.name, key))
    return out


def extract_dep_keys(func: Callable[..., Any]) -> list[Key]:
    """Extract dependency keys from a callable's parameters."""

    return [key for _, key in extract_dep_params(func)]
