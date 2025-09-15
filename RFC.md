
# RFC: FastDI — Rust‑powered Dependency Injection for Python

## Context

Существующие DI‑решения для Python (например, `python-dependency-injector`) используют Cython для ускорения «горячих» путей (провайдеры, контейнеры). Это улучшает производительность, но усложняет сопровождение.

**Цель:** создать DI‑библиотеку для Python, которая:

* синтаксически выглядит как FastAPI (`Depends`, `@inject`),
* под капотом использует Rust (через PyO3) для максимальной скорости и безопасности,
* устраняет ограничения MVP (циклы, скоупы, async‑поддержка, overrides).

## Problem Statement

* В веб‑сервисах с DI может быть миллионы разрешений зависимостей на запрос.
* Чисто Python‑решение даёт избыточный оверхед (dict lookup, дескрипторы).
* Cython решает проблему частично, но усложняет портируемость и отстаёт от Rust по безопасности и эргономике.

## Proposal

### Компоненты

1. **fastdi-core (Rust, PyO3)**

   * `Container`: хранение провайдеров, быстрая резолюция, массовое разрешение зависимостей.
   * `Provider`: хранит Python‑фабрику, поддерживает factory/singleton, lazy caching.
   * Async‑поддержка через `pyo3-asyncio`.
   * Request/task/thread scopes на Rust‑уровне с использованием `contextvars`.

2. **fastdi (Python API)**

   * `Depends(callable|"key")`: маркер зависимостей в сигнатуре.
   * `@provide(container, singleton=..., scope=...)`: регистрация провайдера.
   * `@inject(container)`: компилирует «план» разрешения зависимостей, вызывает `resolve_many`.
   * Поддержка overrides для тестов.
   * Типовая привязка (по аннотациям) + явные ключи.

### FastAPI‑style Usage

```python
from fastdi import Container, Depends, provide, inject

container = Container()

@provide(container, singleton=True)
def get_db():
    return {"db": "connection"}

@provide(container)
def get_service(db = Depends(get_db)):
    class Service:
        def __init__(self, db):
            self.db = db
        def ping(self):
            return {"ok": True, "via": self.db["db"]}
    return Service(db)

@inject(container)
def handler(service = Depends(get_service)):
    return service.ping()

print(handler())
```

### MVP Rust Core (закрывает базовые ограничения)

* Поддержка factory/singleton.
* Batch‑resolve зависимостей.
* Кэширование singleton на стороне Rust.
* Поддержка async через `pyo3-asyncio`.
* Request scope через контекст.
* Проверка циклов в графе зависимостей.
* Overrides API для тестов:

```python
with container.override(get_service, lambda: FakeService()):
    assert handler().ok
```

### Roadmap Beyond MVP

1. Graph compile + топологическая сортировка для минимального оверхеда.
2. Обсервабилити (метрики, хуки на cache‑hit, latency провайдеров).
3. Поддержка DI внутри FastAPI routers/middleware.
4. Оптимизированные wheels (maturin, manylinux, macOS, Windows).

## Advantages

* **Performance**: Rust HashMap/IndexMap + batch resolve.
* **Safety**: строгая проверка циклов и скоупов.
* **Compatibility**: API как у FastAPI (`Depends`, `@inject`).
* **Portability**: бинарные колёса под все платформы.

## Open Questions

* Нужно ли делать auto‑wire по типовым аннотациям (как в FastAPI) или оставлять только явные ключи?
* Где хранить overrides — в Rust (эффективнее) или в Python (гибче)?

## Next Steps

1. Реализовать `fastdi-core` с поддержкой factory/singleton/async/scope.
2. Обёртку `fastdi` с API как у FastAPI.
3. Добавить тесты на циклы, async‑инъекцию, overrides.
4. Подготовить wheels через `maturin`.

---

**Резюме:** FastDI закрывает ограничения MVP: циклы, async, скоупы, overrides. Codex должен выдать полный код решения: Rust‑ядро (PyO3), Python‑обёртка, примеры использования, тесты, setup с `maturin`. Это позволит сразу получить готовую библиотеку DI с FastAPI‑подобным синтаксисом и максимальной производительностью.
