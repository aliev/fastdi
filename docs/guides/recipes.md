# Recipes

Practical patterns and snippets for common use cases.

## Testing with overrides

Replace a provider with a fake during a test:

```python
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

```python
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

```python
from fastdi import provide, Depends

@provide(c, key='db')
def get_db(): ...

@provide(c)
def repo(db = Depends('db')): ...
```

## FastAPI integration (simple)

Call your injected function from a FastAPI route. Request scope works naturally as each request runs in its own asyncio task:

```python
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

```python
@provide(c)
async def token(): ...

@ainject(c)
async def secured(tok = Depends(token)): ...
```

### Async dependency chaining

An async provider can depend on another async (or sync) provider:

```python
import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject

async def main():
    c = Container()

    @provide(c, singleton=True)
    async def get_db():
        await asyncio.sleep(0)
        return {"db": "conn"}

    @provide(c)
    async def get_num(db=Depends(get_db)) -> int:
        await asyncio.sleep(0)
        return 41 if db else 0

    @ainject(c)
    async def handler(n: Annotated[int, Depends(get_num)]):
        return n + 1

    print(await handler())

asyncio.run(main())
```

### Request scope in async chains

Use `scope="request"` to cache values per-async-task. Within one task the same
value is reused; different tasks receive different values.

```python
import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject

async def main():
    c = Container()

    # Per-task value (e.g., request ID, auth context)
    @provide(c, scope="request")
    async def request_id() -> object:
        return object()

    # Downstream provider depends on request_id
    @provide(c)
    async def current_user(rid = Depends(request_id)) -> dict:
        return {"rid": rid}

    # Same-task reuse: both deps read the same cached rid
    @ainject(c)
    async def same_task(a: Annotated[dict, Depends(current_user)],
                        b: Annotated[dict, Depends(current_user)]) -> bool:
        return a["rid"] is b["rid"]

    same = await same_task()        # True within a single task

    # Different tasks get different values
    @ainject(c)
    async def get_rid(r: Annotated[object, Depends(request_id)]) -> int:
        return id(r)

    rid1, rid2 = await asyncio.gather(get_rid(), get_rid())
    print({
        "same_task_same": same,
        "different_tasks_different": rid1 != rid2,
    })

asyncio.run(main())
```

### Note: sync path and request scope

The `request` scope applies only to the async path (`@ainject`, async plan execution). In the
sync path (`@inject`), request caching is not used, so values are recomputed within a call unless
they are singletons.

```python
from fastdi import Container, Depends, provide, inject

c = Container()

@provide(c, scope="request")
def request_id():
    return object()

@inject(c)
def read_twice(a = Depends(request_id), b = Depends(request_id)):
    return a is b

print(read_twice())  # False — no request caching on sync path
```

## Class-based usage

FastDI works well with classes. Common patterns:

At a glance:

```
from typing import Annotated
from fastdi import Container, Depends, provide, inject_method, ainject_method

c = Container()

@provide(c)
def get_num() -> int: return 41

class Foo:
    def __init__(self, base: int): self.base = base
    @inject_method(c)
    def calc(self, n: Annotated[int, Depends(get_num)]) -> int: return self.base + n

print(Foo(1).calc())  # 42
```

### 1) Construct class instances via providers (sync)

```
from typing import Annotated, Protocol
from fastdi import Container, Depends, provide, inject

c = Container()

class DB: ...

@provide(c, singleton=True)
def get_db() -> DB:
    return DB()

class Service(Protocol):
    def ping(self) -> str: ...

class ServiceImpl:
    def __init__(self, db: DB):
        self.db = db
    def ping(self) -> str:
        return "ok"

@provide(c, singleton=True)
def get_service(db: Annotated[DB, Depends(get_db)]) -> Service:
    return ServiceImpl(db)

@inject(c)
def handler(svc: Annotated[Service, Depends(get_service)]) -> str:
    return svc.ping()

print(handler())
```

### 2) Construct class instances via providers (async)

```
import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject

c = Container()

@provide(c, singleton=True)
async def get_db() -> dict:
    return {"db": "conn"}

class ServiceImpl:
    def __init__(self, db: dict):
        self.db = db
    async def add1(self, n: int) -> int:
        return n + 1

@provide(c)
async def get_service(db=Depends(get_db)) -> ServiceImpl:
    return ServiceImpl(db)

@ainject(c)
async def handler(svc: Annotated[ServiceImpl, Depends(get_service)]) -> int:
    return await svc.add1(41)

print(asyncio.run(handler()))
```

### 3) Inject into instance methods (sync) with `@inject_method`

```
from typing import Annotated
from fastdi import Container, Depends, provide, inject_method

c = Container()

@provide(c)
def get_num() -> int:
    return 41

class Foo:
    def __init__(self, base: int):
        self.base = base

    @inject_method(c)
    def calc(self, n: Annotated[int, Depends(get_num)]) -> int:
        return self.base + n

f = Foo(1)
print(f.calc())  # 42
```

 

### 4) Inject into async instance methods with `@ainject_method`

```
import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject_method

c = Container()

@provide(c)
async def get_num() -> int:
    return 40

class Bar:
    def __init__(self, base: int):
        self.base = base

    @ainject_method(c)
    async def calc(self, n: Annotated[int, Depends(get_num)]) -> int:
        return self.base + n + 1

print(asyncio.run(Bar(1).calc()))  # 42
```

### 5) Adapter pattern (closure capturing `self`)

If you prefer, you can create a closure that captures `self` and decorate the closure with `@inject`/`@ainject`.

```
from typing import Annotated
from fastdi import Container, Depends, provide, inject

c = Container()

@provide(c)
def get_config() -> dict:
    return {"feature": True}

class Controller:
    def __init__(self, name: str):
        self.name = name

    def make_handler(self):
        @inject(c)
        def handler(cfg: Annotated[dict, Depends(get_config)]) -> dict:
            return {"name": self.name, "feature": cfg["feature"]}
        return handler

print(Controller("alpha").make_handler()())
```

## Multiple containers in one project

You can have more than one `Container` in a project. Typical reasons:
- Modularization: each feature/package owns its container and providers.
- Testing: isolated containers per test to avoid global state.

Cross-container dependencies are not resolved automatically by `Depends`. If a function in one container needs a value from another, create an adapter provider that calls into the other container explicitly.

```python
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
