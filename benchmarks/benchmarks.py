import time
from tabulate import tabulate


def bench_fastdi_simple(n: int) -> float:
    from typing import Annotated
    from fastdi import Container, provide, inject, Depends

    c = Container()

    @provide(c)
    def v():
        return 1

    @provide(c)
    def w():
        return 2

    @inject(c)
    def handler(a: Annotated[int, Depends(v)], b: Annotated[int, Depends(w)]):
        return a + b

    handler()  # warmup/compile
    t0 = time.perf_counter()
    s = 0
    for _ in range(n):
        s += handler()
    dt = time.perf_counter() - t0
    assert s == n * 3
    return dt


def run_all(n: int = 50000) -> None:
    rows = []
    for name, fn in [
        ("fastdi", bench_fastdi_simple),
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
