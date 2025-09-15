import time
from tabulate import tabulate


def bench_fastdi_simple(n: int) -> float:
    from fastdi import Container, provide, inject, Depends

    c = Container()

    @provide(c)
    def v():
        return 1

    @provide(c)
    def w():
        return 2

    @inject(c)
    def handler(a=Depends(v), b=Depends(w)):
        return a + b

    handler()  # warmup/compile
    t0 = time.perf_counter()
    s = 0
    for _ in range(n):
        s += handler()
    dt = time.perf_counter() - t0
    assert s == n * 3
    return dt


def bench_fast_depends_simple(n: int) -> float:
    from fast_depends import inject as fd_inject
    from fast_depends.dependencies import Depends

    def v():
        return 1

    def w():
        return 2

    @fd_inject
    def handler(a=Depends(v), b=Depends(w)):
        return a + b

    handler()  # warmup/compile
    t0 = time.perf_counter()
    s = 0
    for _ in range(n):
        s += handler()
    dt = time.perf_counter() - t0
    assert s == n * 3
    return dt


def bench_dependency_injector_simple(n: int) -> float:
    from dependency_injector import containers, providers

    class C(containers.DeclarativeContainer):
        v = providers.Factory(lambda: 1)
        w = providers.Factory(lambda: 2)
        s = providers.Factory(lambda a, b: a + b, a=v, b=w)

    c = C()

    # Measure direct provider resolution overhead
    assert c.s() == 3
    t0 = time.perf_counter()
    ssum = 0
    for _ in range(n):
        ssum += c.s()
    dt = time.perf_counter() - t0
    assert ssum == n * 3
    return dt


def bench_dependency_injector_injected(n: int) -> float:
    """Measure dependency-injector wired function injection.

    We create a handler function with Provide[...] defaults and wire a synthetic
    module so the library can patch it correctly.
    """
    import types, sys
    from dependency_injector import containers, providers
    from dependency_injector.wiring import Provide, inject

    class C(containers.DeclarativeContainer):
        v = providers.Factory(lambda: 1)
        w = providers.Factory(lambda: 2)
        s = providers.Factory(lambda a, b: a + b, a=v, b=w)

    c = C()

    # Create a synthetic module to avoid __main__ wiring issues
    mod_name = "_bench_di_module"
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod

    @inject
    def handler(total: int = Provide[C.s]):
        return total

    # Rebind function to synthetic module for wiring
    handler.__module__ = mod_name
    setattr(mod, "handler", handler)

    # Wire and run
    c.wire(modules=[mod_name])
    assert getattr(mod, "handler")() == 3
    t0 = time.perf_counter()
    ssum = 0
    for _ in range(n):
        ssum += getattr(mod, "handler")()
    dt = time.perf_counter() - t0
    assert ssum == n * 3
    c.unwire()
    # Cleanup synthetic module
    sys.modules.pop(mod_name, None)
    return dt


def run_all(n: int = 50000) -> None:
    rows = []
    for name, fn in [
        ("fastdi", bench_fastdi_simple),
        ("fast-depends", bench_fast_depends_simple),
        ("dependency-injector (provider)", bench_dependency_injector_simple),
        ("dependency-injector (wired function)", bench_dependency_injector_injected),
    ]:
        dt = fn(n)
        rows.append(
            {
                "library": name,
                "calls": n,
                "total_ms": round(dt * 1000, 2),
                "per_call_us": round(dt * 1e6 / n, 2),
            }
        )

    print(tabulate(rows, headers="keys", tablefmt="github"))


if __name__ == "__main__":
    run_all()
