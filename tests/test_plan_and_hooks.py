import asyncio
from typing import Annotated
import pytest

from fastdi import Container, Depends, provide, inject, ainject


def test_cycle_detected_at_decoration_sync():
    c = Container()

    @provide(c, key="a")
    def a(b: Annotated[int, Depends("b")]):
        return 1

    @provide(c, key="b")
    def b(a_: Annotated[int, Depends("a")]):
        return 2

    # Decoration should raise due to cycle
    with pytest.raises(RuntimeError):

        @inject(c)
        def h(x: Annotated[int, Depends("a")]):
            return x


@pytest.mark.asyncio
async def test_hooks_and_topo_async():
    c = Container()

    events = []
    c.add_hook(lambda e, p: events.append((e, p.get("key"), p.get("scope"))))

    @provide(c)
    async def leaf():
        await asyncio.sleep(0)
        return 1

    @provide(c)
    async def mid(x: Annotated[int, Depends(leaf)]):
        await asyncio.sleep(0)
        return x + 2

    @provide(c, singleton=True)
    async def top(y: Annotated[int, Depends(mid)]):
        await asyncio.sleep(0)
        return y + 3

    @ainject(c)
    async def handler(v: Annotated[int, Depends(top)]):
        return v

    v1 = await handler()
    v2 = await handler()
    assert v1 == v2 == 6

    # Expect some provider_start/provider_end events and at least one cache_hit for singleton on second call
    kinds = [e for e, _, _ in events]
    assert "provider_start" in kinds and "provider_end" in kinds
    assert any(k == "cache_hit" for k in kinds)
