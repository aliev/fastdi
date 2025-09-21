from typing import Annotated

from fastdi import Container, Depends, inject, provide


def test_depends_annotated_only():
    c = Container()

    class Service:
        def __init__(self, v: int):
            self.v = v

        def ping(self) -> int:
            return self.v

    @provide(c)
    def get_service():
        return Service(7)

    @inject(c)
    def handler(service: Annotated[Service, Depends(get_service)]):
        return service.ping()

    assert handler() == 7


def test_annotated_in_annotation():
    c = Container()

    class Service:
        def __init__(self, v: int):
            self.v = v

        def ping(self) -> int:
            return self.v

    @provide(c)
    def get_service():
        return Service(9)

    @inject(c)
    def handler(service: Annotated[Service, Depends(get_service)]):
        return service.ping()

    assert handler() == 9
