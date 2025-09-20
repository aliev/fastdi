# Usage Guide

Understand the core building blocks—containers, providers, decorators, scopes, and overrides—and how to apply them in real projects.

## Container

```python
from fastdi import Container


container = Container()
```

The container stores providers, manages scopes, emits hooks, and tracks overrides. Pass it to decorators to register and resolve dependencies.

## Providers (`@provide`)

```python

from typing import Annotated
from fastdi import Depends, provide


@provide(container, singleton=True)
def settings() -> dict:
    return {"dsn": "postgres://..."}


@provide(container)
def repo(cfg: Annotated[dict, Depends(settings)]) -> object:
    return object()
```

Key options:

- `singleton=True`: cache the result in Rust after the first computation.
- `scope="request"`: cache per async task when using async resolution.
- `key="custom"`: register under a specific string key.

## Injection Decorators

```python
from fastdi import inject


@inject(container)
def handler(repo: Annotated[object, Depends(repo)]):
    return repo
```

- `@inject` compiles a plan once, then executes it via the Rust core.
- `@ainject` mirrors the behavior for async functions, awaiting async providers and honoring request scope.
- Method variants (`@inject_method`, `@ainject_method`) apply the same rules to instance methods while preserving `self`.

## Scopes

- `transient` *(default)*: recompute on every resolution.
- `singleton`: global cache stored in Rust; overrides create isolated caches.
- `request`: async-task cache stored in Python (`WeakKeyDictionary`).

```python
@provide(container, scope="request")
async def request_id() -> object:
    return object()
```

## Overrides

```python
from fastdi import Depends

class Real: ...
class Fake: ...

@provide(container)
def service() -> Real:
    return Real()

@inject(container)
def use_service(value: Annotated[Real, Depends(service)]):
    return type(value).__name__

with container.override(service, lambda: Fake()):
    assert use_service() == "Fake"

assert use_service() == "Real"
```

Overrides stack and bump the container epoch so compiled plans rebuild safely when wiring changes.

## String Keys

```python
@provide(container, key="db")
def get_db():
    ...

@provide(container)
def repo(db: Annotated[object, Depends("db")]):
    ...
```

String keys help avoid import cycles or choose implementations dynamically.

## Module Layout

Keep the container in one module and register providers close to their definitions.

```python
# app/di.py
from fastdi import Container
container = Container()

# app/providers.py
from fastdi import provide
from .di import container


@provide(container)
def config():
    return {"env": "dev"}

# app/handlers.py
from typing import Annotated
from fastdi import Depends, inject
from .di import container
from .providers import config

@inject(container)
def ping(cfg: Annotated[dict, Depends(config)]):
    return cfg["env"]
```

## Typing Tips

- Prefer `Annotated[T, Depends(...)]` to keep static type checkers happy.
- Protocols are a good fit for injected interfaces.
- The decorators return zero-argument callables with the same return type as the original function, so editors see accurate signatures.
