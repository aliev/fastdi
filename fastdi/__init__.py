"""Public FastDI API.

This module re-exports the main classes and decorators for convenience:

    from fastdi import Container, Depends, provide, inject, ainject
"""

from typing import TYPE_CHECKING

from .container import Container
from .decorators import ainject, ainject_method, inject, inject_method, provide
from .rust_adapter import is_available as is_rust_available
from .types import Depends, make_key

__all__ = [
    "Container",
    "Depends",
    "provide",
    "inject",
    "ainject",
    "inject_method",
    "ainject_method",
    "make_key",
    "is_rust_available",
]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .rust_adapter import RustContainer

if is_rust_available():
    from .rust_adapter import RustContainer

    __all__.append("RustContainer")
