from typing import Annotated, Any, Protocol

from fastdi import Container, Depends, inject, provide


def main():
    container = Container()

    @provide(container, singleton=True)
    def get_db():
        return {"db": "connection"}

    class Service(Protocol):
        def ping(self) -> dict[str, Any]: ...

    @provide(container)
    def get_service(db: Annotated[dict, Depends(get_db)]) -> Service:
        class ServiceImpl:
            def __init__(self, db):
                self.db = db

            def ping(self):
                return {"ok": True, "via": self.db["db"]}

        return ServiceImpl(db)

    @inject(container)
    def handler(service: Annotated[Service, Depends(get_service)]):
        return service.ping()

    print(handler())

    class FakeService:
        def ping(self):
            return {"ok": True, "via": "fake"}

    # Overrides example
    with container.override(get_service, lambda: FakeService(), singleton=True):
        print(handler())


if __name__ == "__main__":
    main()
