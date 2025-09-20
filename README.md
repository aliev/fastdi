# FastDI — Rust-powered Dependency Injection for Python

FastDI wraps a Rust core (PyO3) in a friendly Python API so you can wire services quickly without sacrificing performance. It supports sync and async providers, request-scoped caches, layered overrides, and observability hooks.

Project homepage: https://aliev.me/fastdi

## Highlights

- Rust-backed plan compilation with cycle detection
- Sync (`@inject`) and async (`@ainject`) decorators with minimal boilerplate
- Caching scopes: transient, singleton, and per-request (async task)
- Overrides for tests and temporary wiring changes
- Hooks that report provider timings and cache hits

## Quick Start

```bash
pip install fastdi-core
# or set up a dev env with uv
uv venv .venv
. .venv/bin/activate
uv sync --dev
uv run maturin develop -r -q
uv run python -m examples.basic
```

## Minimal Usage

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
    class ServiceImpl:
        def __init__(self, db):
            self._db = db
        def ping(self) -> dict:
            return {"ok": True, "via": self._db["db"]}
    return ServiceImpl(db)

@inject(container)
def handler(service: Annotated[Service, Depends(get_service)]):
    return service.ping()

print(handler())
```

### Async + Request Scope

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

print(asyncio.run(within_task()))  # True: value is cached within a task
```

### Observability Hooks

```python
from fastdi import Container

container = Container()
container.add_hook(lambda event, payload: print(event, payload))
```

## Development Tasks

```bash
uv run python -m pytest -q    # tests
uv run ruff check .           # lint
uv run mypy .                 # type check
uv run python -m mkdocs serve # docs preview
```

## Documentation

Full guides live under `docs/` and the published site (see `mkdocs.yml`). Key entries:
- Getting started walkthrough
- Usage guide covering providers, scopes, and overrides
- Observability hooks and performance notes

## License
MIT
