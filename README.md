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
- It does not yet model when a `select`, `default`, `imply` or `choice` applies. The one loss `verify`
  cannot see is `select X if <expr>`: the condition is dropped, so a fragment can ask for more than it
  needs. [docs/kconfig-coverage.md](docs/kconfig-coverage.md) lists every construct, its status and the
  roadmap row that closes it.
- Module-to-option mapping reads `obj-$(CONFIG_X)` lines, so a module built another way is listed
  as unmapped, not guessed.
- A snapshot only sees hardware and drivers present at capture time.

See `ROADMAP.md` for the planned reverse direction: inferring a configuration from a kernel binary.
