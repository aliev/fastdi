import asyncio
from typing import Annotated

import pytest

from fastdi import Container, Depends, ainject, provide


@pytest.mark.asyncio
async def test_async_inject_and_request_scope():
    c = Container()

    @provide(c, singleton=True)
    async def base():
        await asyncio.sleep(0)
        return 40

    @provide(c)
    async def inc(x: Annotated[int, Depends(base)]):
        await asyncio.sleep(0)
        return x + 2

    @ainject(c)
    async def handler(v: Annotated[int, Depends(inc)]):
        return v

    assert await handler() == 42

    # request scope consistency within one task
    @provide(c, scope="request")
    async def token():
        await asyncio.sleep(0)
        return object()

    @ainject(c)
    async def pair(a: Annotated[object, Depends(token)], b: Annotated[object, Depends(token)]):
        return a, b

    a, b = await pair()
    assert a is b  # same within task

    async def get_id():
        a, _ = await pair()
        return id(a)

    id1, id2 = await asyncio.gather(get_id(), get_id())
    assert id1 != id2  # different across tasks


@pytest.mark.asyncio
async def test_ainject_preserves_call_arguments():
    c = Container()

    @provide(c)
    async def provide_value() -> int:
        await asyncio.sleep(0)
        return 5

    @ainject(c)
    async def endpoint(
        width: int,
        injected: Annotated[int, Depends(provide_value)],
        height: int,
    ) -> tuple[int, int, int]:
        return width, height, injected

    assert await endpoint(3, height=4) == (3, 4, 5)

    # Explicit argument should bypass DI resolution for that parameter.
    assert await endpoint(3, height=4, injected=9) == (3, 4, 9)
