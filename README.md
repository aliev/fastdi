# FastDI — Rust‑powered Dependency Injection for Python

FastDI is a FastAPI-style DI library for Python with a Rust core (PyO3) for speed and safety. It supports sync and async providers, singleton and request scopes, layered overrides, and plan compilation with topological sorting.

## Features
- Fast provider resolution via Rust + caching
- Sync and async providers (`@inject` / `@ainject`)
- Scopes: transient, singleton, request (per-async-task)
- Layered overrides for tests
- Plan compilation: cycle detection at decoration time
- Observability hooks: provider timings and cache hits

## Requirements
- Python 3.8+
- Rust toolchain (stable)
- maturin (installed into your virtualenv via uv)

## Local Development (uv + maturin)

1) Create and activate a virtualenv with uv

```
uv venv .venv
. .venv/bin/activate
```

2) Install dev dependencies (declared in pyproject)

```
uv sync --dev
```

3) Build and install the Rust extension in editable mode

```
uv run maturin develop -q
```

4) Run examples

```
uv run python -m examples.basic
uv run python -m examples.async_basic
uv run python -m examples.request_scope_async
```

5) Run tests

```
python -m pytest -q -s
```

## Typing Recommendations
To keep static type checkers like Pyright/Mypy happy:
- Annotate provider return types (Protocols or concrete classes).
- Prefer either:
  - Explicit type + `Depends` in default:
    ```python
    @inject(container)
    def handler(service: Service = Depends(get_service)):
        ...
    ```
  - `Annotated[Type, Depends(...)]` in the annotation:
    ```python
    from typing import Annotated

    @inject(container)
    def handler(service: Annotated[Service, Depends(get_service)]):
        ...
    ```
- Avoid using `Annotated[...]` as a runtime default value (e.g. `param = Annotated[...]`).

## Minimal Example (sync)
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
def get_service(db=Depends(get_db)) -> Service:
    class ServiceImpl:
        def __init__(self, db):
            self.db = db
        def ping(self) -> dict:
            return {"ok": True, "via": self.db["db"]}
    return ServiceImpl(db)

@inject(container)
def handler(service: Annotated[Service, Depends(get_service)]):
    return service.ping()

print(handler())
```

## Quick Start

1) Create a virtualenv and install dev dependencies

```
uv venv .venv
. .venv/bin/activate
uv sync --dev
```

2) Build the Rust core in release mode and install in editable form

```
uv run maturin develop -r -q
```

3) Run an example

```
uv run python -m examples.basic
```

## Scopes
- `singleton`: cached globally in Rust once computed.
- `request`: cached per async task (using `WeakKeyDictionary`), handy for web requests.
- `transient`: default; no caching.

Choose scope via `@provide(container, scope="request")` or `singleton=True`.

## Observability Hooks
Register hooks to receive provider lifecycle events:
```
from fastdi import Container
c = Container()

c.add_hook(lambda event, payload: print(event, payload))
```
Events:
- `provider_start`: `{key, async}`
- `provider_end`: `{key, async, duration_s}`
- `cache_hit`: `{key, scope}`

Examples:

1) Print simple timings per provider

```
from fastdi import Container, provide, inject, Depends

c = Container()
timeline = []

def hook(event, payload):
    if event in ("provider_start", "provider_end"):
        timeline.append((event, payload["key"], payload.get("duration_s", 0.0)))

c.add_hook(hook)

@provide(c, singleton=True)
def conf():
    return {"url": "db://"}

@provide(c)
def db(cfg=Depends(conf)):
    return object()

@inject(c)
def handler(conn=Depends(db)):
    return True

handler()
print("timeline:")
for e, k, d in timeline:
    print(e, k, d)
```

2) Count cache hits (singleton / request)

```
hits = {"singleton": 0, "request": 0}

def stats(event, payload):
    if event == "cache_hit":
        hits[payload["scope"]] = hits.get(payload["scope"], 0) + 1

c.add_hook(stats)
# run your workload ...
print(hits)
```

3) Integrate with logging or metrics

```
import logging
log = logging.getLogger("fastdi")

def metrics(event, payload):
    if event == "provider_end":
        log.info("provider %s took %.3fms", payload["key"], payload["duration_s"]*1000)

c.add_hook(metrics)
```

## Async Usage
Use `@ainject` for async handlers. Async providers are awaited automatically; sync paths will raise if they encounter an async provider.

## Notes
- The sync `@inject` path compiles and validates a plan and executes via the Rust plan executor (topological, non-recursive). Async plans are executed in Python iteratively with awaits.
- Wheels are not published yet. Use `maturin develop -r` for local development.

## Managing Dev Dependencies

To add a new dev tool (e.g., ruff), use uv’s dev group:

```
uv add --dev ruff
```

Then install/update your environment:

```
uv sync --dev
```

## License
TBD.
