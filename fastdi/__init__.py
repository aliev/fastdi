"""Public FastDI API.

This module re-exports the main classes and decorators for convenience:

    from fastdi import Container, Depends, provide, inject, ainject
"""

from .types import Depends
from .container import Container
from .decorators import provide, inject, ainject

__all__ = ["Container", "Depends", "provide", "inject", "ainject"]
