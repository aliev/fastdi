# Quick Start

## Install and build (local)

```
uv sync --dev
uv run maturin develop -r -q
```

## Minimal sync example

```
from typing import Annotated, Protocol
from fastdi import Container, Depends, provide, inject

c = Container()

class Service(Protocol):
    def ping(self) -> dict: ...

@provide(c, singleton=True)
def get_db() -> dict:
    return {"db": "connection"}

@provide(c)
def get_service(db=Depends(get_db)) -> Service:
    class ServiceImpl:
        def __init__(self, db):
            self.db = db
        def ping(self) -> dict:
            return {"ok": True, "via": self.db["db"]}
    return ServiceImpl(db)

@inject(c)
def handler(svc: Annotated[Service, Depends(get_service)]):
    return svc.ping()

print(handler())
```

## Minimal async example

```
import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject

c = Container()

@provide(c, singleton=True)
async def get_db() -> dict:
    return {"db": "conn"}

@provide(c)
async def get_number(db=Depends(get_db)) -> int:
    return 41 if db else 0

@ainject(c)
async def handler(n: Annotated[int, Depends(get_number)]):
    return n + 1

print(asyncio.run(handler()))
```

## Request scope

```
import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject

c = Container()

@provide(c, scope="request")
async def request_id() -> object:
    return object()

@ainject(c)
async def read_twice(a: Annotated[object, Depends(request_id)],
                     b: Annotated[object, Depends(request_id)]):
    return a is b

print(asyncio.run(read_twice()))  # True within one task
```

