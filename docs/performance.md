# Performance

FastDI ships with a small benchmark suite that exercises common injection paths. Use it to measure the library on your own hardware.

## How to Run

```bash
uv sync --dev
uv run maturin develop -r -q
uv run python -m benchmarks.benchmarks
```

To change the number of calls:

```bash
uv run python - <<'PY'
from benchmarks.benchmarks import run_all
run_all(100_000)  # 100k calls
PY
```

For deep graph validation you can enable the large-scale tests (functional, not timed by default):

```bash
FASTDI_RUN_LARGE=1 FASTDI_LARGE_N=3000 uv run python -m pytest -q -s tests/test_large_scale.py
```

## Sample Results

- Machine: Apple M4 Pro
- Python: 3.11 (uv virtualenv)
- Calls: 50,000
- Scenario: sync function injection with two dependencies

```text
| metric        | value  |
|---------------|--------|
| total_ms      | 55.75  |
| per_call_us   | 1.12   |
```

Numbers will vary with hardware and environment. Rebuild with `maturin develop -r` and close background workloads for consistent measurements. Setting `RUSTFLAGS="-C target-cpu=native"` before building can provide an extra boost on local machines.
