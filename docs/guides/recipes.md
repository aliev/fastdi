# Recipes

Practical patterns and snippets for common use cases.

## Testing with overrides

Replace a provider with a fake during a test:

```
from fastdi import Container, provide, inject, Depends, make_key

c = Container()

class Real: pass
class Fake: pass

@provide(c)
def get_service() -> Real:
    return Real()

@inject(c)
def handler(svc = Depends(get_service)):
    return type(svc).__name__

def test_handler_uses_fake():
    with c.override(get_service, lambda: Fake()):
        assert handler() == 'Fake'
    assert handler() == 'Real'
```

## Module layout

Register providers close to where they are defined, but export the shared container from a central module:

```
# app/di.py
from fastdi import Container
c = Container()

# app/providers.py
from .di import c
from fastdi import provide

@provide(c)
def config():
    return {"env": "dev"}

# app/handlers.py
from .di import c
from .providers import config
from fastdi import inject, Depends

@inject(c)
def ping(cfg = Depends(config)):
    return cfg["env"]
```

## String keys for indirection

Use string keys to avoid import cycles or choose implementation at runtime:

```
from fastdi import provide, Depends

@provide(c, key='db')
def get_db(): ...

@provide(c)
def repo(db = Depends('db')): ...
```

## FastAPI integration (simple)

Call your injected function from a FastAPI route. Request scope works naturally as each request runs in its own asyncio task:

```
from fastapi import FastAPI
from fastdi import Container, provide, inject, Depends

app = FastAPI()
c = Container()

@provide(c, scope='request')
async def request_id():
    return object()

@inject(c)
def ping(rid = Depends(request_id)):
    return {"ok": True, "rid": id(rid)}

@app.get("/ping")
async def route_ping():
    return ping()
```

## Singletons vs request scope

- Use `singleton=True` for heavy or global resources (config, DB clients).
- Use `scope='request'` for per-request data (IDs, auth context), cached within the task.

## Async graphs

Prefer `@ainject` for async handlers and async providers; sync `@inject` rejects async nodes.

```
@provide(c)
async def token(): ...

@ainject(c)
async def secured(tok = Depends(token)): ...
```

## Multiple containers in one project

You can have more than one `Container` in a project. Typical reasons:
- Modularization: each feature/package owns its container and providers.
- Testing: isolated containers per test to avoid global state.

Cross-container dependencies are not resolved automatically by `Depends`. If a function in one container needs a value from another, create an adapter provider that calls into the other container explicitly.

```
from fastdi import Container, provide, inject, Depends

c_auth = Container()
c_orders = Container()

@provide(c_auth)
def current_user_id():
    return 42

# Adapter provider in the orders container that calls the auth container
@provide(c_orders)
def user_id_from_auth():
    return c_auth.resolve(make_key(current_user_id))

@provide(c_orders)
def orders_repo(uid = Depends(user_id_from_auth)):
    return {"uid": uid}

@inject(c_orders)
def handler(repo = Depends(orders_repo)):
    return repo["uid"]

assert handler() == 42
```

Notes:
- Prefer one app-level `Container` when possible; multiple containers are fine for isolation, but cross-container calls should be explicit.
- You can also register the same callable in multiple containers if you need independent override/caching behaviors.
