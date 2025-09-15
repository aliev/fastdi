# Benchmarks

This page shows a simple micro-benchmark comparing FastDI against
FastDepends and dependency-injector.

## How to run

```
uv sync --dev
uv run maturin develop -r -q  # build Rust core in release mode
uv run python -m benchmarks.benchmarks
```

To change the number of calls, you can run the benchmark entrypoint from
Python and pass a value explicitly:

```
uv run maturin develop -r -q
uv run python - << 'PY'
from benchmarks.benchmarks import run_all
run_all(100_000)  # 100k calls
PY
```

Large-scale functional tests (deep chains) can be run separately:

```
FASTDI_RUN_LARGE=1 FASTDI_LARGE_N=3000 uv run python -m pytest -q -s tests/test_large_scale.py
```
Where `FASTDI_LARGE_N` controls chain length (default 3000). These tests
validate scalability but are not timed by default.

Tips for more consistent numbers:
- Always build in release (`maturin develop -r`) before timing.
- Pin CPU frequency or run on a quiet system to reduce noise.
- Optionally set `RUSTFLAGS="-C target-cpu=native"` before build to enable CPU-specific optimizations locally.

## Current results

- Machine: Apple M1
- Python: 3.11 (uv venv)
- Calls: 50,000
- Scenario: sum of two dependencies via function injection
- Note: dependency-injector measured direct provider calls (`container.s()`), not function injection wiring

```
| library                              |   calls |   total_ms |   per_call_us |
|--------------------------------------|---------|------------|---------------|
| fastdi                               |   50000 |      48.99 |          0.98 |
| fast-depends                         |   50000 |     216.52 |          4.33 |
| dependency-injector (provider)       |   50000 |      12.10 |          0.24 |
| dependency-injector (wired function) |   50000 |      24.22 |          0.48 |
```

Notes:
- FastDI and FastDepends rows measure function injection with two dependencies.
- The “provider” row measures direct provider resolution (`container.s()`); the “wired function” row measures function-level injection via `dependency_injector.wiring.inject` with `Provide[...]`.
- Values are indicative and depend on hardware, Python version, and environment.
— Large-scale tests (deep chains up to thousands of nodes) are included separately to validate scalability; they are functional and not timed by default.

### Why dependency-injector can look faster here

This microbenchmark measures different things for different libraries:

- For `dependency-injector` we call a provider directly (`container.s()`), which is essentially an already-wired Python function call with its dependencies bound via provider objects. There is no function-level injection step on each call.
- For `fastdi` and `fast-depends` we do function-level injection on each call: the wrapper resolves dependencies and then invokes the original function.

As a result, `dependency-injector` can appear faster in this specific setup because:

- Direct provider invocation avoids extra steps involved in function injection (resolving a parameter list and building args for a function call).
- `dependency-injector`’s providers are highly optimized and avoid runtime signature inspection on calls (wiring is done ahead of time). Parts of its core are implemented with C extensions, further reducing Python overhead.
- `fastdi` uses a Rust core for planning and provider lookup, but each resolution still crosses the Python↔Rust boundary via PyO3 and then calls back into Python providers. For very small graphs, this FFI transition can dominate total time.

What to expect in apples-to-apples cases:

- If we benchmark `dependency-injector` with wired function injection (using `dependency_injector.wiring.inject` + `Provide[...]`) instead of direct provider calls, there will be additional overhead comparable in spirit to function wrappers in `fastdi`/`fast-depends`.
- For larger graphs and batch resolutions, `fastdi`’s plan execution (topological order) and singleton caching in Rust reduce overhead per node and can close the gap or outperform in scenarios with many dependencies or repeated resolutions.

We plan to add:
- A wired function-injection benchmark for `dependency-injector`.
- Wider/deeper and async scenarios to show behavior beyond trivial two-node graphs.

Planned:
- Add more scenarios (deep chains, singletons, async).
- Provide wired function-injection benchmark for `dependency-injector`.
