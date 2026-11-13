# Conformance with the kernel's `conf`

How closely kconfigpy's proposals match what the pinned kernel's own `conf` resolves them to.
Row `kc.conformance` in `ROADMAP.md`. This document is the method and the measurement; the numbers
come from `tools/conformance.py` and nothing else.

## Status of the measurement

**Not yet measured.** The run needs the builder image and its `rooter-build` volume, and the Docker
engine on the measuring machine was not responding when this was written (the `com.docker.service`
Windows service was stopped, and `docker version` hung). No agreement figure is recorded here until a run
completes. The comparison logic is tested without Docker (`tests/test_conformance.py`).

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

Pass `--requests <file>` to add the bound-device symbols. `--tree <host Kconfig copy>` skips the volume
extraction. The script writes `summary.json` and `results.jsonl` to `--out`.

## Results

None yet. When a run completes, record here: the date, the kernel version, the sample and seed, the request
count, and the table from `summary.json` (kept share, proposed share of conf, requests with no drop, extra
count, and the most-dropped options with their counts).
