# Hooks (Observability)

FastDI can emit events during resolution so you can inspect and measure
behavior in production or tests.

## Events

- `provider_start`: `{key, async}`
- `provider_end`: `{key, async, duration_s}`
- `cache_hit`: `{key, scope}`

## Quick example

```
from fastdi import Container
c = Container()

c.add_hook(lambda e, p: print(e, p))
```

## Use cases

### 1) Per-provider timings

```
from fastdi import Container, provide, inject, Depends

c = Container()

timeline = []

def hook(event, payload):
    if event in ("provider_start", "provider_end"):
        timeline.append((event, payload["key"], payload.get("duration_s", 0.0)))

c.add_hook(hook)

@provide(c)
def a(): return 1

@provide(c)
def b(x = Depends(a)): return x + 1

@inject(c)
def handler(y = Depends(b)): return y

handler()
print(timeline)
```

### 2) Count cache hits

```
hits = {"singleton": 0, "request": 0}

def stats(event, payload):
    if event == "cache_hit":
        hits[payload["scope"]] = hits.get(payload["scope"], 0) + 1

c.add_hook(stats)
```

### 3) Integrate with logging / metrics

```
import logging
log = logging.getLogger("fastdi")

def metrics(event, payload):
    if event == "provider_end":
        log.info("provider %s took %.3fms", payload["key"], payload["duration_s"]*1000)

c.add_hook(metrics)
```

### 4) Filter noisy providers

```
NOISY_PREFIX = "thirdparty:"

def filter_hook(event, payload):
    key = payload.get("key", "")
    if key.startswith(NOISY_PREFIX):
        return
    # handle event ...

c.add_hook(filter_hook)
```

### 5) Remove hooks

```
# Keep a reference to remove later
c.remove_hook(metrics)
```

