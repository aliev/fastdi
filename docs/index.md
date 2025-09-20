# FastDI Documentation

FastDI pairs a Rust core with a lightweight Python API to provide fast, explicit dependency injection. Use it to wire sync or async providers, apply scopes, and observe resolution without ceremony.

## What You Get

- Plan compilation with cycle detection and cached execution
- Decorators for sync/async functions and methods
- Scopes for transient, singleton, and per-request lifetimes
- Layered overrides to swap providers safely
- Hooks that report timings and cache hits

## Quick Start

```bash
uv sync --dev
uv run maturin develop -r -q
uv run python -m examples.basic
```

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
        def __init__(self, source):
            self._source = source
        def ping(self) -> dict:
            return {"ok": True, "via": self._source["db"]}
    return Impl(db)


@inject(container)
def handler(service: Annotated[Service, Depends(get_service)]):
    return service.ping()


print(handler())
```

## Where to Go Next
- [Getting started](getting-started.md): environment setup, sync/async basics, request scope
- [Usage guide](usage.md): containers, providers, overrides, and typing tips
- [Observability](observability.md): hooks for metrics, logging, and cache stats
- [Performance](performance.md): how to run benchmarks and what results to expect
- [API reference](reference/container.md): detailed signatures for public APIs
