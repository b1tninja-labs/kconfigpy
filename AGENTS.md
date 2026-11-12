# Instructions for coding agents

Explainable Linux Kconfig analysis. `README.md` says what it is for, `ROADMAP.md` what is planned.

## Commands

    python -m pip install -e ".[dev]"
    python -m pytest -q
    python -m ruff format .
    python -m ruff check .
    python -m mypy

Run formatters from this directory only.

## Invariants

- No runtime dependencies.
- The kernel's own `conf` is the authority on a configuration. This code proposes, and `verify` checks.
- Every enabled option carries a reason. An option with no reason is a bug.
- When the mapping is unknown, report it as unknown. Never guess a symbol.
- Hardware snapshots from real machines stay out of this repository.
- Commit messages take no `Co-Authored-By` trailer or other AI attribution.
