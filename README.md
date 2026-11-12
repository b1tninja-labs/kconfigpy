# kconfexplain

Explainable Linux Kconfig analysis. Give it a snapshot of real hardware and an exact kernel
source tree, and it produces a minimal configuration fragment in which every option records
why it is there.

    python -m kconfexplain trace --tree linux-6.18.62 --snapshot host.tsv --out out/
    python -m kconfexplain verify --tree linux-6.18.62 --fragment out/hardware.config --config .config

`trace` writes `hardware.config` and `report.md`. Run `make allnoconfig
KCONFIG_ALLCONFIG=hardware.config`, then `verify` compares the result with the request and names
the dependency that blocked anything the kernel dropped. The kernel's own `conf` is always the
authority; this tool only proposes.

`tools/collect-snapshot.sh` gathers the snapshot on the target. It only reads from `/sys` and
`/proc/modules`.

## How it differs from what exists

Hardware-to-config tools exist: [autokernel](https://github.com/oddlama/autokernel),
[kernelconfig](https://github.com/dywisor/kernelconfig),
[AutoKernConf](https://github.com/heeplr/autokernconf) and `make localmodconfig`. Most rely on a
separately maintained database or on what happens to be loaded today. kconfexplain reads its
mapping from the exact tree being built, and records the reason for each option.

Hardening audits ([kernel-hardening-checker](https://github.com/a13xp0p0v/kernel-hardening-checker))
and CVE filters ([CVEhound](https://github.com/linux-analysis/cvehound)) are complementary.

## Known limits

- The Kconfig reader extracts dependencies only. Numeric tests and compiler probes are reported
  as not evaluated and left to `conf`.
- Module-to-option mapping reads `obj-$(CONFIG_X)` lines, so a module built another way is listed
  as unmapped, not guessed.
- A snapshot only sees hardware and drivers present at capture time.

See `ROADMAP.md` for the planned reverse direction: inferring a configuration from a kernel binary.
