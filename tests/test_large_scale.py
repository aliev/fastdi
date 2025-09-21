import os
from typing import Annotated

import pytest

from fastdi import Container, Depends, ainject, inject, provide

RUN_LARGE = os.getenv("FASTDI_RUN_LARGE", "0") == "1"
SIZE = int(os.getenv("FASTDI_LARGE_N", "3000"))


pytestmark = pytest.mark.skipif(not RUN_LARGE, reason="Set FASTDI_RUN_LARGE=1 to enable large-scale tests")


def test_large_chain_sync():
    c = Container()

    @provide(c, key="p_0")
    def p0():
        return 0

    for i in range(1, SIZE + 1):
        key = f"p_{i}"
        dep_key = f"p_{i - 1}"

        @provide(c, key=key)
        def _f(prev: Annotated[int, Depends(dep_key)], _inc=i):  # bind i by default arg
            return prev + 1

    @inject(c)
    def handler(v: Annotated[int, Depends(f"p_{SIZE}")]):
        return v

    assert handler() == SIZE


@pytest.mark.asyncio
async def test_large_chain_async():
    c = Container()

    @provide(c, key="ap_0")
    async def p0():
        return 0

    limit = max(1000, min(SIZE, 3000))
    for i in range(1, limit + 1):
        key = f"ap_{i}"
        dep_key = f"ap_{i - 1}"

        @provide(c, key=key)
        async def _f(prev: Annotated[int, Depends(dep_key)], _inc=i):  # bind i by default arg
            return prev + 1

    @ainject(c)
    async def handler(v: Annotated[int, Depends(f"ap_{limit}")]):
        return v

    assert await handler() == limit
