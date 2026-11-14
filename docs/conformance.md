# Conformance with the kernel's `conf`

How closely kconfigpy's proposals match what the pinned kernel's own `conf` resolves them to.
Row `kc.conformance` in `ROADMAP.md`. This document is the method and the measurement; the numbers
come from `tools/conformance.py` and nothing else.

## Status of the measurement

**Measured** on the pinned tree (Linux 6.18.62, x86), with the builder image and the `rooter-build` volume.
The comparison logic is also tested without Docker (`tests/test_conformance.py`).

## Method

1. **Request.** Each request is one symbol. Two sources:
   - `--requests FILE`: one symbol per line, for example the options the router's hardware snapshot binds.
   - `--sample N --seed S`: a seeded random sample of N settable symbols (`random.Random(S)` over the sorted
     list of symbols that have a prompt of type `bool` or `tristate`).
2. **Proposal.** kconfigpy's `Solver` (`kconfigpy/solve.py`) runs `want(symbol)`. The proposal is the set of
   options it enables. Forced options (select targets whose own dependencies are unmet) are not part of the
   proposal, because they are not solved.
3. **Resolution by `conf`.** The proposal is written as a fragment (`CONFIG_X=y` lines). In the builder,
   `make O=<dir> ARCH=x86_64 KCONFIG_ALLCONFIG=<fragment> allnoconfig` resolves it for the pinned tree
   `/work/src/linux-6.18.62`. One container run handles every request, looping over the fragments. A
   request whose `make` fails is listed in `failures.txt` and the tool refuses to summarise a partial run.
4. **Comparison.** Per request, with `P` the proposal and `R` the symbols `conf` resolved as `y`:
   - **dropped** = `P − R`: options kconfigpy proposed that `conf` did not keep.
   - **extra** = `R − P`: options `conf` enabled that kconfigpy did not mention. Most of these are defaults
     that `allnoconfig` turns on, which is the expected disagreement, not an error.
   - `m` is not counted: kconfigpy only proposes `y`.
5. **Rates.** Over all requests:
   - *kept share* = kept ÷ proposed, where kept = `|P ∩ R|`. This is how much of what kconfigpy proposed
     `conf` keeps.
   - *proposed share of conf* = kept ÷ `|R|`. This is how much of what `conf` enables kconfigpy accounted for.
   - *requests with no drop*: the count of requests where every proposed option was kept.
   - *most dropped*: the options most often dropped, which says what kind of disagreement dominates.

## Reproducing

    python tools/conformance.py --volume rooter-build --image rooter-builder:latest \
        --sample 200 --seed 1 --out <a directory outside the repository>

Pass `--snapshot <file>` to add the symbols the snapshot's bound drivers map to, or `--requests <file>` for a
list of symbols. `--tree <host Kconfig copy>` skips the volume
extraction. The script writes `summary.json` and `results.jsonl` to `--out`.

## Results

Run on 2026-11-13: `--snapshot` (the router's 64-device snapshot, bound drivers mapped through the kernel's
Makefiles), plus `--sample 200 --seed 1` over the settable symbols. The requests are the 200 sampled symbols
and the snapshot's bound symbols, deduplicated: **208 requests**, each resolved as its own fragment. One
container ran all 208 resolutions. None failed.

| Measure | Value |
|---|---|
| Requests | 208 |
| Requests with no dropped option | 131 (63%) |
| Options proposed | 1,100 |
| Proposed options `conf` kept | 990 (**kept share 90.0%**) |
| Proposed options `conf` dropped | 110 |
| Options `conf` enabled, across all requests | 109,840 |
| Extra options (enabled by `conf`, never proposed) | 108,850 |
| Proposed share of `conf`'s options | 0.9% |

**Two kinds of disagreement, and they differ in size:**

- **Extra options dominate by volume.** Almost all of `conf`'s enabled options are defaults that `allnoconfig`
  turns on (`def_bool y`, `default` lines), which kconfigpy does not model yet. This is the `kc.defaults` row,
  not a proposal error. It is why the proposed share of `conf`'s options is under 1%.
- **Dropped proposals are spread across many symbols.** There are 110 drops over 105 distinct symbols; no symbol
  is dropped more than 3 times. The drops cluster on the requested symbol itself (for example `PINCTRL_SUN5I`,
  `COMMON_CLK_MT7622`, `CLK_BCM_HR2`, `NET_VENDOR_PASEMI`), and on platform-gated drivers (`ARCH_R8A78000`,
  `SND_SOC_TEGRA`, `TEGRA20_APB_DMA`). The most dropped are `SND_SOC_TEGRA` and `TEGRA20_APB_DMA` (3 each).

  **Cause not confirmed.** `PINCTRL_SUN5I` has no `depends on` of its own, so the gate must come from its enclosing
  menu or `if` block, or from a condition the reader does not carry into the solver. That is a hypothesis to test,
  not a finding. The likely area is block-scoped dependencies in `kconfig.py`, which this run does not isolate.

The per-request drop lists are in `results.jsonl` in the measurement's output directory. They were kept outside the
repository because they are derived from a real hardware snapshot.

## Results after the undefined-symbol fix

The first run's hypothesis was partly right and mostly different. The drops did not come from block-scoped
dependencies. The most dropped symbols (`SND_SOC_TEGRA`, `TEGRA20_APB_DMA`, `APPLE_MAILBOX`) all say
`depends on ARCH_X || COMPILE_TEST`. `COMPILE_TEST` is never chosen, and `ARCH_X` is not defined for x86, but
the solver counted an undefined symbol as free and took the dead branch. Kconfig reads an undefined symbol as
`n`. The solver now treats such a branch as impossible, and a settable option whose dependency cannot hold is
listed as "Wanted but cannot hold here" and not proposed.

Rerun on 2026-11-13 with the same method, seed and sample (200 sampled symbols plus the router snapshot's
bound symbols, now 217 requests because the repository's snapshot binds 9 more symbols than the scratch copy
of the first run):

| Measure | Before the fix (same 217 requests) | After the fix |
|---|---|---|
| Requests with no dropped option | 140 (65%) | 188 (87%) |
| Options proposed | 1,139 | 874 |
| Proposed options `conf` kept | 1,029 (**90.3%**) | 835 (**95.5%**) |
| Proposed options `conf` dropped | 110 | 39 |

Proposals fell by 265: 71 of them were options `conf` dropped, and the other 194 were options `conf` kept. The
likely reason for the second group is that an option that cannot hold is no longer walked, so the dependencies
it would have pulled in (for example `COMMON_CLK` and `RESET_CONTROLLER` for `SND_SOC_TEGRA`) are not proposed
either. That is the right behaviour, since nothing needs them, but it is an inference. `results.jsonl` keeps
only each request's dropped list, not its proposals, so this run does not prove it request by request.

The 39 that remain are single drops across 39 symbols (for example `DRM_PANEL_NOVATEK_NT36523`, `DVB_DRX39XYJ`,
`DVB_EC100`, `EISA`, `IMX_SCU`). Their cause is not examined here. The router's resolved configuration is
unchanged by the fix: 866 options, `verify` kept 188 and dropped none.
