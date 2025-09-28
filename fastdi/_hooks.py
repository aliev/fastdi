"""Shared hook utilities for FastDI cores."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress

from .types import Hook


def emit_hooks(hooks: Iterable[Hook], event: str, payload: dict[str, object]) -> None:
    """Invoke hooks defensively, ignoring hook failures."""

    for hook in list(hooks):
        with suppress(Exception):
            hook(event, payload)
