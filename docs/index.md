# FastDI

FastDI is a FastAPI-style DI library for Python with a Rust core (PyO3).

- Sync and async providers
- Scopes: transient, singleton, request
- Overrides, plan compilation, observability hooks

See the API reference for details.

## Quick Start

```
uv sync --dev
uv run maturin develop -r -q

python - << 'PY'
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
PY
```

## Hooks (Observability)

```
from fastdi import Container
c = Container()

c.add_hook(lambda e, p: print(e, p))
```

Events:
- `provider_start`: `{key, async}`
- `provider_end`: `{key, async, duration_s}`
- `cache_hit`: `{key, scope}`

Common use cases:
- Print simple per-provider timings.
- Count singleton/request cache hits.
- Forward to logging/metrics systems.
