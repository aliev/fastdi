from typing import Annotated
from fastdi import Container, Depends, provide, inject


def test_basic_sync():
    c = Container()

    @provide(c, singleton=True)
    def get_a():
        return {"a": 1}

    @provide(c)
    def get_b(a: Annotated[dict, Depends(get_a)]):
        return a["a"] + 1

    @inject(c)
    def handler(b: Annotated[int, Depends(get_b)]):
        return b

    assert handler() == 2

    # Override get_b
    with c.override(get_b, lambda: 42, singleton=True):
        assert handler() == 42
