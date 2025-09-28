import asyncio
from typing import Annotated

import pytest

from fastdi import Depends, inject, provide
from fastdi.rust_adapter import RustContainer, is_available

pytestmark = pytest.mark.skipif(not is_available(), reason="Rust backend not installed")


def test_rust_container_sync_resolution_and_override():
    container = RustContainer()

    @provide(container, singleton=True)
    def get_base() -> dict[str, int]:
        return {"value": 1}

    @provide(container)
    def get_value(base: Annotated[dict[str, int], Depends(get_base)]) -> int:
        return base["value"] + 1

    @inject(container)
    def handler(value: Annotated[int, Depends(get_value)]) -> int:
        return value

    assert handler() == 2

    with container.override(get_value, lambda: 5, singleton=True):
        assert handler() == 5


@pytest.mark.asyncio
async def test_rust_container_request_scope_and_hooks():
    container = RustContainer()
    events: list[str] = []
    container.add_hook(lambda event, payload: events.append(event))

    counter = 0

    async def request_id() -> int:
        nonlocal counter
        counter += 1
        return counter

    container.register("request_id", request_id, singleton=False, dep_keys=[], scope="request")

    async def _collect() -> tuple[int, int]:
        first = await container.resolve_async("request_id")
        second = await container.resolve_async("request_id")
        return first, second

    (first_a, first_b), (second_a, second_b) = await asyncio.gather(
        _collect(),
        _collect(),
    )

    assert first_a == first_b
    assert second_a == second_b
    assert first_a != second_a
    assert "provider_start" in events
    assert "cache_hit" in events
