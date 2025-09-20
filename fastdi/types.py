"""Common types and helpers for FastDI.

Defines shared type aliases, the `Depends` marker, and helpers to extract
dependency metadata from callables.
"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Protocol,
    get_args,
    get_origin,
    Annotated,
)
import inspect

# Public type aliases
Key = str
Scope = str  # one of: "transient", "request", "singleton"
Hook = Callable[[str, Dict[str, Any]], None]


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
        dep_keys: List[str],
    ) -> None: ...
    def resolve(self, key: str) -> Any: ...
    def resolve_many(self, keys: List[str]) -> List[Any]: ...
    def resolve_many_plan(self, keys: List[str]) -> List[Any]: ...
    def begin_override_layer(self) -> None: ...
    def set_override(
        self,
        key: str,
        callable: Callable[..., Any],
        singleton: bool,
        is_async: bool,
        dep_keys: List[str],
    ) -> None: ...
    def end_override_layer(self) -> None: ...
    def get_provider_info(self, key: str) -> Tuple[Callable[..., Any], bool, bool, List[str]]: ...
    def get_cached(self, key: str) -> Optional[Any]: ...
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

    def __init__(self, target: Any):
        self.key = make_key(target)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Depends({self.key})"


def extract_dep_keys(func: Callable[..., Any]) -> List[Key]:
    """Extract dependency keys from a callable's parameters.

    Supported (and enforced) form:
    - Annotated-only: ``param: Annotated[T, Depends(callable_or_key)]``

    The default-value style (``param=Depends(...)``) is not supported.
    """
    sig = inspect.signature(func)
    out: List[Key] = []

    def _from_annotated(obj: Any) -> Optional[Key]:
        org = get_origin(obj)
        if org is Annotated:
            for meta in get_args(obj)[1:]:
                if isinstance(meta, Depends):
                    return meta.key
        return None

    for p in sig.parameters.values():
        if p.annotation is not inspect._empty:
            k = _from_annotated(p.annotation)
            if k is not None:
                out.append(k)

    return out
