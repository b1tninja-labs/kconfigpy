# Plan: kconfigpy

## What it is

Explainable Linux Kconfig analysis. It takes a snapshot of real hardware (sysfs devices and loaded
modules) and an exact kernel source tree, and proposes a minimal configuration in which every enabled
option records why it is there. `verify` checks that proposal against the kernel's own resolved `.config`.

## Status

- Working: Kconfig reader, module map, solver with reasons, `verify`, `snapshot` (local or over SSH),
  `generate` (saved snapshot or `--current`), `trace` as an alias of `generate`.
- Tests: 24 pass; 8 are Linux-only and skipped on Windows. The forge's five gates pass.
- Not yet: the end-to-end `generate` run on a real kernel tree (ROADMAP row `cli.generate`).

## Tier and wave (proposed, not decided)

- **Tier:** 3, a tool that serves the router firmware. Not a library the portfolio depends on.
- **Wave:** unscheduled. It is not on the critical path for any tier-1 project.
- **Active:** no. It does not count against the two-active-projects rule.

These belong in `PORTFOLIO.md`, which is the authority. This file records them so a reader of the project
sees them without opening the portfolio.

## Dependencies

- **Blocks nothing yet.** The router firmware uses it as a build gate (`scripts/build-kernel.sh` runs
  `verify`), so a regression here stops the kernel build.
- **Blocked by nothing.** It reads the kernel tree and sysfs; it needs no runtime dependency.
- **Firmware coupling:** the kernel version is pinned in `kernel/version.env` (6.18.62). A new kernel means
  a new tree to trace against and a new banned-list check.

## Decisions taken

- Stdlib only at runtime. The snapshot module is one file, so it can be piped to a remote `python3`
  without installing the package there.
- Refuse rather than guess: a snapshot off Linux, from an empty sysfs, or with no device records is an
  error, never an empty result.
- The kernel's own `conf` is the authority. This tool proposes; `verify` checks.
- The name is `kconfigpy`. The forge's name checker flags it as one keystroke from `configpy` and
  `jconfigpy`; that was accepted deliberately.

## Research

Existing tools that solve parts of this (listed in the README): `autokernel`, `kernelconfig`,
`AutoKernConf`, and `make localmodconfig`. Most rely on a separate database or on what is loaded today.
kconfigpy reads its mapping from the exact tree being built and records a reason per option.
Hardening audits (`kernel-hardening-checker`) and CVE filters (`CVEhound`) are complementary, and
`tools/cve_reach.py` is an early CVE-reachability check against the kernel's own branch history.

Open research questions, each tied to a ROADMAP row:

- Reverse direction (`rev.*`): whether a kernel binary carries enough evidence (embedded config, symbol
  tables, modversion CRCs) to recover a configuration with stated confidence. Validate on kernels whose
  real config is known before trusting it on vendor firmware.
- Out-of-tree hardware (`oot.*`): how to report a device with a known out-of-tree driver as such, rather
  than as unclaimed. The first case is Intel QuickAssist on the router.

## Kconfig coverage

How much of the Kconfig language the reader handles is measured, construct by construct, in
[kconfig-coverage.md](kconfig-coverage.md). In short: structure and dependencies are read almost
completely (0.3% of terms unevaluated on 6.18.62), and value semantics are not modelled yet. The `kc.*`
rows in `ROADMAP.md` close those gaps, with `kc.select-if` first because it is the one loss `verify`
cannot detect, and `kc.conformance` last as the measure of the rest.

## Risks

- **Mapping gaps:** a driver built another way is listed as unmapped. The tool reports this and does not
  guess a symbol.
- **Snapshot coverage:** a snapshot only sees hardware present at capture time. A config from one
  snapshot can drop a driver the machine needs for hardware it does not have today.
- **Remote access:** `snapshot --ssh` reads a host you name. It is read-only, and it writes nothing on
  the host.

## Next

1. Run `generate --current` end to end on a real kernel tree, on Linux, and record the result.
2. Close the remaining `fwd.*` rows, starting with `fwd.modalias`, which removes the host-supplied
   `modules.alias` dependency.
3. Decide the tier and wave in `PORTFOLIO.md`, then register the project there.
