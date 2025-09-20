# Getting Started

Set up a development environment, register providers, and run your first calls with FastDI.

## 1. Install Dependencies

```bash
pip install fastdi-core
# or set up a local dev environment:
uv sync --dev
uv run maturin develop -r -q
```

## 2. Minimal Sync Flow

```python
from typing import Annotated, Protocol
from fastdi import Container, Depends, provide, inject


container = Container()

class Service(Protocol):
    def ping(self) -> dict: ...

@provide(container, singleton=True)
def get_db() -> dict:
    return {"db": "connection"}

@provide(container)
def get_service(db: Annotated[dict, Depends(get_db)]) -> Service:
    class Impl:
        def __init__(self, db):
            self._db = db
        def ping(self) -> dict:
            return {"ok": True, "via": self._db["db"]}
    return Impl(db)

@inject(container)
def handler(service: Annotated[Service, Depends(get_service)]):
    return service.ping()

print(handler())
```

## 3. Minimal Async Flow

```python
import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject


container = Container()

@provide(container)
async def get_number() -> int:
    return 41

@ainject(container)
async def handler(value: Annotated[int, Depends(get_number)]) -> int:
    return value + 1

print(asyncio.run(handler()))
```

## 4. Request Scope (per async task)

```python
import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject


container = Container()

@provide(container, scope="request")
async def request_id() -> object:
    return object()

@ainject(container)
async def within_task(
    first: Annotated[object, Depends(request_id)],
    second: Annotated[object, Depends(request_id)],
) -> bool:
    return first is second

print(asyncio.run(within_task()))  # True
```

## Next Steps
- Learn about provider metadata, overrides, and typing in the [usage guide](usage.md)
- Add logging or metrics with the [observability hooks](observability.md)
- Measure runtime behavior in [performance](performance.md)
