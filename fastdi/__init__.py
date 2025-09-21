"""Public FastDI API.

This module re-exports the main classes and decorators for convenience:

    from fastdi import Container, Depends, provide, inject, ainject
"""

from .container import Container
from .decorators import ainject, ainject_method, inject, inject_method, provide
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
]
