# Changelog

## 0.1.0 - unreleased

- Kconfig reader, module map, solver that records a reason for every option, and `verify` against a resolved `.config`.
- `snapshot`: export the hardware snapshot of this machine, or of an SSH host. Standard library only; refuses off Linux and on an empty sysfs.
- `generate`: write the config fragment from a saved snapshot, or from a fresh one with `--current`.
- `trace` is kept as an alias of `generate --snapshot`.
- `select X if <expr>` keeps its condition: the select is followed only when the requested options decide that it holds, and the report lists the ones not followed. An option the request never mentions is undecided, not off. On the router's snapshot this takes the proposal from 60 options to 52.
- `generate --exclude FILE`: options never to enable. An excluded option is not requested and nothing it depends on or selects is followed; before this, a caller could only filter the fragment afterwards, which left what the excluded option had selected.
- `docs/kconfig-coverage.md`: a construct-by-construct matrix of the Kconfig language against the reader, measured on Linux 6.18.62 with `tools/kconfig_census.py`.
