# Concepts

This page explains the core concepts and attributes in FastDI.

## Container

`Container` is the central registry and runtime:
- Stores providers (factories) and layered overrides.
- Manages scopes: `transient`, `singleton` (Rust-level cache), and `request` (per-async-task cache).
- Exposes sync resolution (Rust) and async resolution (Python).
- Emits observability hooks (`provider_start`, `provider_end`, `cache_hit`).
- Tracks an internal epoch (version) to invalidate compiled plans when the graph changes.

Create one container and pass it to decorators:

```
from fastdi import Container
c = Container()
```

## Depends

`Depends(target)` marks a function parameter as a dependency.
- `target` can be a callable (provider) or a string key (e.g., "db").
- Use it in either default value or `typing.Annotated[Type, Depends(...)]` to keep type checkers happy.

```
from typing import Annotated
from fastdi import Depends

def handler(svc: Annotated[Service, Depends(get_service)]):
    ...
```

## provide

`@provide(container, *, singleton=False, key=None, scope=None)` registers a provider function.

Parameters:
- `singleton: bool` — cache result globally in Rust after first computation. Best for configs, clients, pools.
- `key: Optional[str]` — explicit registration key. By default derived from function (`module:qualname`).
- `scope: Optional[str]` — Python-managed scope:
  - `"transient"` (default) — no caching.
  - `"request"` — cache per async task (ASGI request task fits naturally).
  - If `singleton=True`, `scope` is ignored (singleton wins).

Notes:
- Provider can be sync or async. FastDI detects coroutine functions automatically.
- Dependencies are discovered from parameter defaults or `Annotated` metadata.

### Scopes: how they work

- `transient` (default): no caching. Every resolution invokes the provider.
  - Sync path (Rust): just calls the Python callable each time.
  - Async path (Python): awaits the callable each time; no entry in request cache.

- `singleton`: process-wide cache stored in Rust next to the provider entry.
  - First successful computation is stored in Rust (`Provider.cache`) and reused for subsequent resolutions across threads/tasks.
  - Overrides are isolated: an overridden provider has its own cache within the override layer. When the override context exits, its cache is dropped along with the layer.
  - Good for configs, client pools, shared services.

- `request`: per-async-task cache stored in Python.
  - Implementation uses a `WeakKeyDictionary[asyncio.Task, dict]` so entries are garbage-collected when tasks finish.
  - Outside of any running task, a `ContextVar` fallback holds a separate per-context dict.
  - Only available on the async path (`@ainject`/`resolve_async`/async plan execution). The sync path does not consult the request cache.
  - Good for values tied to a single request (IDs, auth context, per-request DB sessions if desired).

Priority: if `singleton=True` is set, it overrides `scope` and enforces singleton caching. Otherwise, `scope` controls caching (`request`/`transient`).

## inject

`@inject(container)` wraps a sync function for dependency injection.
- Compiles and validates a plan once and re-validates when the container changes.
- Executes via the Rust plan executor (topologically, without recursion).
- Fails fast if any provider in the graph is async (use `@ainject` instead).
- The resulting wrapper takes no arguments; all parameters marked with `Depends` are injected.

```
@inject(c)
def handler(svc: Annotated[Service, Depends(get_service)]):
    return svc.ping()

handler()  # no args
```

## ainject

`@ainject(container)` wraps an async function for dependency injection.
- Compiles a plan and executes it iteratively in Python (awaiting async providers).
- Supports `request` scope and emits hook events.
- The resulting wrapper is an async callable with no arguments.

```
@ainject(c)
async def handler(n: Annotated[int, Depends(get_number)]):
    return n + 1

await handler()
```

## override

`container.override(key_or_callable, replacement, *, singleton=False)` is a context manager to temporarily replace a provider.
- Accepts original callable or a key string.
- The replacement provider can be sync or async and may have a different dependency shape.
- Bumps the container epoch on enter and exit so injectors rebuild plans as needed.

```
with c.override(get_service, lambda: FakeService(), singleton=True):
    assert handler().ok
```

## Keys and typing

- Keys are strings identifying providers. By default they are derived from function `module:qualname`. You can also use explicit string keys for indirection.
- Prefer `Annotated[T, Depends(...)]` or `param: T = Depends(...)` so static type checkers know the parameter type.
