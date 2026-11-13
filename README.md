# kconfigpy

Explainable Linux Kconfig analysis. Give it a snapshot of real hardware and an exact kernel
source tree, and it produces a minimal configuration fragment in which every option records
why it is there.

    python -m kconfigpy snapshot --ssh root@target --out host.tsv
    python -m kconfigpy generate --snapshot host.tsv --tree linux-6.18.62 --out out/
    python -m kconfigpy generate --current --ssh root@target --tree linux-6.18.62 --out out/
    python -m kconfigpy verify --tree linux-6.18.62 --fragment out/hardware.config --config .config

`trace` writes `hardware.config` and `report.md`. Run `make allnoconfig
KCONFIG_ALLCONFIG=hardware.config`, then `verify` compares the result with the request and names
the dependency that blocked anything the kernel dropped. The kernel's own `conf` is always the
authority; this tool only proposes.

The `snapshot` command gathers it, locally or over SSH (`--ssh HOST`). It only reads `/sys` and `/proc/modules`,
and the snapshot module is standard library only, so it runs on a target without installing anything there.

## Workflow

1. **Snapshot** the hardware you want to support, once per machine:

       python -m kconfigpy snapshot --ssh root@target --out host.tsv

2. **Generate** the fragment from the snapshot and the exact kernel source tree:

       python -m kconfigpy generate --snapshot host.tsv --tree linux-6.18.62 \
           --built-tree build/ --exclude exclude.list --out out/

   - `--built-tree DIR` is the build output directory of a finished build of the same kernel version.
     It must hold `modules.alias`, `modules.builtin.alias` (the `depmod` output) and `.config`. Aliases
     are read from there, never derived from source, so a device no driver has bound yet can still be
     matched to the driver that claims it. When any of the three files is missing the command refuses
     and names the file (exit status 2, nothing written). `--aliases FILE` still takes a bare
     `modules.alias` and can be combined with it.
   - With `CONFIG_MODULES` off in that `.config`, no module can load, so each driver is mapped to the
     symbol that builds it in, and `report.md` opens with "modules are off: drivers mapped to built-in
     symbols".
   - `--exclude FILE` lists symbols (one per line) that must never be enabled; they appear in the report
     under "Excluded on request" instead of in the fragment. Lines may omit the `CONFIG_` prefix, and
     `#` starts a comment.
   - The command writes `hardware.config` (each option preceded by the reason it is there) and `report.md`.

3. **Resolve and verify.** Merge the fragment with any role fragments, run
   `make allnoconfig KCONFIG_ALLCONFIG=merged.config`, then ask the kernel what it kept:

       python -m kconfigpy verify --tree linux-6.18.62 --fragment merged.config --config .config

   A non-zero exit means the kernel dropped something; each dropped option is listed with the
   dependency that blocked it.

## How it differs from what exists

Hardware-to-config tools exist: [autokernel](https://github.com/oddlama/autokernel),
[kernelconfig](https://github.com/dywisor/kernelconfig),
[AutoKernConf](https://github.com/heeplr/autokernconf) and `make localmodconfig`. Most rely on a
separately maintained database or on what happens to be loaded today. kconfigpy reads its
mapping from the exact tree being built, and records the reason for each option.

Hardening audits ([kernel-hardening-checker](https://github.com/a13xp0p0v/kernel-hardening-checker))
and CVE filters ([CVEhound](https://github.com/linux-analysis/cvehound)) are complementary.

## Known limits

- The Kconfig reader extracts dependencies only. On Linux 6.18.62 for x86 it reads all 18,456 symbols
  and leaves 225 of 72,310 dependency terms unevaluated (numeric tests and compiler probes), which are
  reported and left to `conf`.
- It does not yet model when a `default`, `imply` or `choice` applies. A `select X if <expr>` is followed
  only when the requested options decide that the condition holds, and is reported otherwise.
  [docs/kconfig-coverage.md](docs/kconfig-coverage.md) lists every construct, its status and the
  roadmap row that closes it.
- Module-to-option mapping reads `obj-$(CONFIG_X)` lines, so a module built another way is listed
  as unmapped, not guessed.
- A snapshot only sees hardware and drivers present at capture time.

`generate --exclude FILE` takes a list of options never to enable, one per line. An excluded option is
not requested, and nothing it depends on or selects is followed. The report lists each one that a device
wanted.

See `ROADMAP.md` for the planned reverse direction: inferring a configuration from a kernel binary.
