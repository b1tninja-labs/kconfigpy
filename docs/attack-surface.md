# Attack-surface report

`kconfigpy/surface.py` answers two questions about a kernel configuration:

1. Which options are on, and which code each one brings (through the module map).
2. Which banned options are on, which excluded options are on, and which options are on although no fragment asked for them.

## Method

**The resolved `.config` is the authority.** The kernel's own `conf` writes it, so it contains every option that `default y`, `select` or `imply` turned on, including options no fragment named. A fragment only records what was asked for. The report therefore takes the resolved config as its main input and the fragment as a comparison:

- `requested_by(fragment)` gives the options a fragment asks to have on (a value of `n` asks for off).
- `surface(resolved, modules, banned, excluded, requested=...)` lists every enabled option the fragment did not name as `unrequested`.

**Feature options are `y` and `m`.** Other set values (for example `CONFIG_GCC_VERSION=160201` or `CONFIG_LOCALVERSION=""`) are not features that bring code, so they are left out of the code and unmapped sections. They are still checked against the banned and excluded lists, because a banned option is on whatever its value.

**Banned and excluded lists are inputs.** `read_banned` reads the firmware's `kernel/banned.list` and `read_exclude` reads `kernel/exclude.list`. Both take one option per line, ignore `#` comments, accept a `CONFIG_` prefix, and refuse a malformed line with its line number. The module holds no list of its own.

**Code is attributed through the module map.** `kconfigpy.kbuild.module_map(tree)` reads each `obj-$(CONFIG_X) += name.o` in the kernel tree. An enabled option with no mapping is listed as unmapped and is not guessed at. Options that build no module, such as `KEXEC` on this tree, appear as unmapped only when no `obj-$(CONFIG_X)` line names them.

## Reproduce

There is no CLI yet (see "CLI wiring remaining" below), so call the functions directly from the repository. The inputs are read-only firmware files and a kernel tree for the code section:

```python
from pathlib import Path
from kconfigpy.kbuild import module_map
from kconfigpy.surface import read_banned, read_exclude, requested_by, surface, report_text
from kconfigpy.verify import read_config

fw = Path("D:/code/aws/router/firmware")
resolved = read_config(fw / "out" / "kernel.config")
requested = set()
for fragment in sorted((fw / "kernel" / "fragments").glob("*.config")):
    requested |= requested_by(read_config(fragment))
modules = module_map(Path("<kernel tree>"), "x86")  # needs the 6.18.62 tree
result = surface(resolved, modules, read_banned(fw / "kernel/banned.list"),
                 read_exclude(fw / "kernel/exclude.list"), requested=requested)
print(report_text(result))
```

The kernel tree is in the Docker volume `rooter-build` at `/work/src/linux-6.18.62`. Reading it needs the Docker engine running:

```bash
docker run --rm -v rooter-build:/work:ro rooter-builder:latest ls /work/src/linux-6.18.62
```

## Results: router firmware, 6.18.62

Inputs: `out/kernel.config` (3,400 lines, Linux 6.18.62 x86_64), the nine fragments in `kernel/fragments/`, `kernel/banned.list` (42 options), `kernel/exclude.list` (17 options).

| Measure | Count |
|---|---|
| Options set to `y` in the resolved config | 792 |
| Options set to `m` | 0 (`CONFIG_MODULES` is off) |
| Other set values (numeric or string, not features) | 74 |
| Options named as on by the nine fragments | 158 |
| Fragment-named options whose resolved value is not `y`/`m` (numeric or string) | 3 |
| Enabled features the fragments did not name (`unrequested`) | 637 |
| Banned options enabled | **0** of 42 |
| Excluded options enabled | **1** of 17 (`INPUT=y`) |
| Modules in the x86 module map (kernel tree `Makefile`/`Kbuild`) | 14,670 |
| Enabled features with a module mapping | 248 of 792 |
| Enabled features with no module mapping (`unmapped`) | 544 |
| Unrequested features with a mapping / without | 161 / 476 |

Every fragment-named value matches the resolved config exactly. Every banned option is absent from the resolved config. The 637 unrequested features come from `default y`, `select` and `imply` in the Kconfig tree; they are the reason the resolved config is the authority.

### Findings

- **No banned option is on.** None of the 42 options in `banned.list` is set in `out/kernel.config`, including `MODULES`, `KEXEC`, `USER_NS`, `IO_URING` and the `CRYPTO_USER_API*` family.
- **`INPUT` is on, against `exclude.list`.** `exclude.list` lists `INPUT` under "Power button: nothing here needs a key press event", and says it is removed from the generated hardware fragment. But `kernel/fragments/15-console-key.config` line 2 names `CONFIG_INPUT=y`, and the resolved config has it. So the hand-written fragment and the exclude list disagree, and the exclude list is not enforced on the fragments. The 16 other excluded options are absent from the resolved config.
- **No banned option brings code, because none is on.** The module map was built from the kernel tree, so the `banned.list` options that have module entries (for example `KEXEC`, `USER_NS`, `IO_URING`, `BT`) would be attributed if they were enabled. None is.
- **`INPUT` brings `input_core`.** The excluded `INPUT=y` is built as `input_core`, so turning it off removes that module.
- **Most of the set is unmapped.** 544 of 792 enabled features have no `obj-$(CONFIG_X)` line; no `obj-$(CONFIG_X)` line in the tree's Makefiles or Kbuild files names them. The report says so rather than guessing; this run did not check why each one is unmapped.

## Code-attribution run

The kernel tree's `Makefile` and `Kbuild` files were copied out of the `rooter-build` volume with `docker run --rm -v rooter-build:/work:ro rooter-builder:latest sh -c 'cd /work/src/linux-6.18.62 && find . \( -name Makefile -o -name Kbuild \) | tar -cf - -T -'` (3,282 files), then `module_map(tree, "x86")` ran on that copy. The Docker engine answered on the second attempt, after it was started by hand.

## Limits

- The report lists options and their modules. It does not say why a `select` or `imply` fired; that needs the Kconfig reader and the solver (`fwd.select`).
- `unrequested` is the list of features nobody asked for. It is not a list of defects.
- A banned option that is set to a non-`n` value is reported whatever its value.

## CLI wiring remaining

These are the steps for a later session, and they touch `kconfigpy/__main__.py`, which another session owns:

1. Add a `surface` subcommand with `--config` (resolved `.config`), `--fragment` (repeatable, merged through `requested_by`), `--tree`, `--arch`, `--banned` (default `kernel/banned.list`), `--exclude` (default `kernel/exclude.list`), and `--out` for the Markdown report.
2. Its handler calls `read_config`, `module_map`, `read_banned`, `read_exclude`, `requested_by`, `surface` and `report_text`, then writes the report and exits non-zero when a banned option is enabled.
3. A CLI test runs `main(["surface", ...])` on a small tree, and asserts the exit code and the report text.
