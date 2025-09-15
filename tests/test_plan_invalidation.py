import asyncio
import pytest

from fastdi import Container, Depends, provide, ainject


@pytest.mark.asyncio
async def test_plan_rebuild_on_override_changes_graph():
    c = Container()

    @provide(c)
    async def leaf():
        return 1

    @provide(c)
    async def mid(x=Depends(leaf)):
        return x + 2

    @provide(c)
    async def top(y=Depends(mid)):
        return y + 3

    @ainject(c)
    async def handler(v=Depends(top)):
        return v

    # Initial graph: leaf(1) -> mid(3) -> top(6)
    assert await handler() == 6

    # Override 'mid' to change its dependencies shape (no deps now)
    async def mid_override():
        return 10

    with c.override(mid, mid_override):
        # Plan should rebuild when epoch changes, now top = 10 + 3
        assert await handler() == 13

    # After override ends, plan should rebuild again to the original shape
    assert await handler() == 6
