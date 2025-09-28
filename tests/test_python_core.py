import asyncio

import pytest

from fastdi._python_core import PythonContainerCore


def test_python_core_sync_resolution_and_hooks():
    core = PythonContainerCore()
    events: list[tuple[str, dict[str, object]]] = []
    core.add_hook(lambda event, payload: events.append((event, payload.copy())))

    core.register_provider("a", lambda: 1, singleton=False, is_async=False, dep_keys=())

    def provide_b(a: int) -> int:
        return a + 1

    core.register_provider("b", provide_b, singleton=False, is_async=False, dep_keys=("a",))

    assert core.resolve("b") == 2
    cache_events = [event for event, _ in events if event == "cache_hit"]
    assert not cache_events
    starts = [payload["key"] for event, payload in events if event == "provider_start"]
    assert starts == ["a", "b"]


def test_python_core_detects_cycles():
    core = PythonContainerCore()

    core.register_provider("a", lambda b: b, singleton=False, is_async=False, dep_keys=("b",))
    core.register_provider("b", lambda a: a, singleton=False, is_async=False, dep_keys=("a",))

    with pytest.raises(RuntimeError):
        core.resolve("a")


async def _collect_request_ids(core: PythonContainerCore) -> tuple[object, object]:
    first = await core.resolve_async("handler")
    second = await core.resolve_async("handler")
    return first, second


@pytest.mark.asyncio
async def test_python_core_request_scope_cache():
    core = PythonContainerCore()
    counter = 0

    async def request_id() -> int:
        nonlocal counter
        counter += 1
        return counter

    async def handler(rid: int) -> tuple[int, int]:
        return (rid, rid)

    core.register_provider("request_id", request_id, singleton=False, is_async=True, dep_keys=(), scope="request")
    core.register_provider(
        "handler",
        handler,
        singleton=False,
        is_async=True,
        dep_keys=("request_id",),
    )

    (first_a, first_b), (second_a, second_b) = await asyncio.gather(
        _collect_request_ids(core),
        _collect_request_ids(core),
    )

    # Same task gets same request-scoped value
    assert first_a == first_b
    assert second_a == second_b
    # Different tasks see different values
    assert first_a != second_a


def test_python_core_overrides():
    core = PythonContainerCore()
    core.register_provider("value", lambda: 1, singleton=False, is_async=False, dep_keys=())
    assert core.resolve("value") == 1

    core.begin_override_layer()
    core.set_override("value", lambda: 2, singleton=False, is_async=False, dep_keys=())
    assert core.resolve("value") == 2
    core.end_override_layer()
    assert core.resolve("value") == 1


def test_python_core_singleton_cache_hits():
    core = PythonContainerCore()
    calls: list[int] = []

    def provide_object() -> int:
        calls.append(1)
        return 42

    events: list[tuple[str, dict[str, object]]] = []
    core.add_hook(lambda event, payload: events.append((event, payload.copy())))

    core.register_provider("obj", provide_object, singleton=True, is_async=False, dep_keys=())

    assert core.resolve("obj") == 42
    assert core.resolve("obj") == 42
    assert len(calls) == 1
    cache_hits = [payload for event, payload in events if event == "cache_hit"]
    assert cache_hits and cache_hits[-1]["scope"] == "singleton"
