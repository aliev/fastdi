# Repository Guidelines

## Project Structure & Module Organization
- `fastdi/`: Python API (container, decorators, types) and `py.typed`.
- `_fastdi_core` (Rust ext): `Cargo.toml`, `src/lib.rs` exposed via PyO3.
- `tests/`: Pytest suite (sync/async, plan, hooks, methods).
- `examples/`: Small runnable samples (basic, async, request scope).
- `benchmarks/`: Microbenchmarks comparing libraries.
- `docs/` + `mkdocs.yml`: User docs, guides, and diagrams.
- `README.md`: Overview and design reference.

## Build, Test, and Development Commands
- Create env: `uv sync --all-groups` (or `pip install -e .[dev]`).
- Build Rust ext (editable): `maturin develop -r` (use `-r` for release).
- Lint/format: `ruff check .` and `ruff format .`.
- Type check: `mypy .`.
- Tests: `pytest -q` (add `-k pattern` to filter).
- Docs preview: `mkdocs serve` (build: `mkdocs build`).
- Benchmarks: `python benchmarks/benchmarks.py` (run on release build).

## Coding Style & Naming Conventions
- Python: 4‑space indent, type‑annotated; prefer `Annotated[...]` for DI.
- Rust: idiomatic Rust, minimal `unsafe`, small focused modules.
- Tools: ruff (lint/format), mypy (strict typing). Keep code clear and small.
- Naming: snake_case (functions/vars), PascalCase (classes), SCREAMING_SNAKE_CASE (consts).

## Testing Guidelines
- Framework: pytest. Place tests in `tests/` as `test_*.py`.
- Cover new features with sync/async cases and edge conditions.
- Avoid flakiness: no network or time‑sensitive sleeps; use fixtures.
- Run `pytest -q && ruff check . && mypy .` before pushing.

## Commit & Pull Request Guidelines
- Commits: concise imperative subject (≤72 chars), focused diff.
- Include context in body: what/why; reference issues (`Fixes #123`).
- PRs: clear description, motivation, screenshots/logs if relevant.
- Requirements: passing CI, updated tests, docs when user‑visible behavior changes.
- Scope: no unrelated refactors; keep changes minimal and reviewable.

## Architecture Overview
- Two layers: Python API (user‑facing DI) and Rust core (plan compilation and high‑perf execution via PyO3).
- Observability hooks surface provider start/end and cache hits.
