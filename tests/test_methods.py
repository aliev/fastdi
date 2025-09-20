from typing import Annotated

from fastdi import Container, Depends, provide, inject_method, ainject_method
import asyncio


def test_inject_method_sync():
    c = Container()

    @provide(c)
    def get_num():
        return 41

    class Foo:
        def __init__(self, base: int):
            self.base = base

        @inject_method(c)
        def calc(self, n: Annotated[int, Depends(get_num)]):
            return self.base + n

    f = Foo(1)
    assert f.calc() == 42


def test_ainject_method_async():
    c = Container()

    @provide(c)
    async def get_num():
        return 40

    class Bar:
        def __init__(self, base: int):
            self.base = base

        @ainject_method(c)
        async def calc(self, n: Annotated[int, Depends(get_num)]):
            return self.base + n + 1

    async def run():
        b = Bar(1)
        return await b.calc()

    assert asyncio.run(run()) == 42
