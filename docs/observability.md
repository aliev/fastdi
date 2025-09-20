# Observability Hooks

Hook functions receive structured events each time FastDI resolves providers. Use them to capture timings, count cache hits, or forward data to logging and metrics systems.

## Events
- `provider_start`: `{key, async}`
- `provider_end`: `{key, async, duration_s}`
- `cache_hit`: `{key, scope}`

## Getting Started
```python
from fastdi import Container

container = Container()
container.add_hook(lambda event, payload: print(event, payload))
```

## Common Patterns

### Measure Provider Durations
```python
from typing import Annotated
from fastdi import Container, Depends, inject, provide

container = Container()
recorded = []

def track(event, payload):
    if event in {"provider_start", "provider_end"}:
        recorded.append((event, payload["key"], payload.get("duration_s", 0.0)))

container.add_hook(track)

@provide(container)
def a() -> int:
    return 1

@provide(container)
def b(value: Annotated[int, Depends(a)]) -> int:
    return value + 1

@inject(container)
def handler(result: Annotated[int, Depends(b)]) -> int:
    return result

handler()
print(recorded)
```

### Count Cache Hits
```python
hits = {"singleton": 0, "request": 0}

def count(event, payload):
    if event == "cache_hit":
        scope = payload["scope"]
        hits[scope] = hits.get(scope, 0) + 1

container.add_hook(count)
```

### Forward to Logging or Metrics
```python
import logging

log = logging.getLogger("fastdi")

def report(event, payload):
    if event == "provider_end":
        log.info(
            "provider %s took %.3fms",
            payload["key"],
            payload["duration_s"] * 1000,
        )

container.add_hook(report)
```

### Remove Hooks
```python
container.remove_hook(report)
```
