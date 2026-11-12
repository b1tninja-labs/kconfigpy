# Contributing

Run the same gates CI runs before a commit:

    python -m pip install -e ".[dev]"
    python -m ruff format --check .
    python -m ruff check .
    python -m mypy
    python -m pytest -q

Rules that matter here:

- A row in `ROADMAP.md` moves to done only when its named test exists, passes, and would fail if the behaviour broke.
- Every enabled option carries a reason. An option with no reason is a bug.
- When the mapping is unknown, report it as unknown. Never guess a symbol.
- Hardware snapshots from real machines stay out of the repository.
- Commit messages take no co-author trailer or other attribution.
