# Changelog

## 0.1.0 - unreleased

- Kconfig reader, module map, solver that records a reason for every option, and `verify` against a resolved `.config`.
- `snapshot`: export the hardware snapshot of this machine, or of an SSH host. Standard library only; refuses off Linux and on an empty sysfs.
- `generate`: write the config fragment from a saved snapshot, or from a fresh one with `--current`.
- `trace` is kept as an alias of `generate --snapshot`.
- `select X if <expr>` keeps its condition: the select is followed only when the requested options make it hold, and the report lists the ones not followed. On the router's snapshot this takes the proposal from 60 options to 53.
- `docs/kconfig-coverage.md`: a construct-by-construct matrix of the Kconfig language against the reader, measured on Linux 6.18.62 with `tools/kconfig_census.py`.
