# Roadmap

Each row is one obligation. A row moves to done only when its named test exists, passes, and would fail
if the behaviour broke. `ROADMAP.md` is the source of truth; the GitHub issues are derived from it.

| Id | Status | Area | Obligation | Evidence |
|---|---|---|---|---|
| `fwd.reader` | [x] | forward | Kconfig dependency reader, Makefile module map, minimal solver, reasons per option | `tests/test_pipeline.py::test_every_option_records_a_reason` |
| `fwd.verify` | [x] | forward | `verify` checks a fragment against the kernel's own resolved `.config` | `tests/test_pipeline.py::test_verify_names_the_blocking_dependency` |
| `cli.snapshot` | [x] | cli | `snapshot` exports a hardware snapshot from this machine or over SSH, from one stdlib-only module | `tests/test_snapshot.py::test_snapshot_command_writes_a_file` |
| `cli.generate` | [ ] | cli | `generate` writes a fragment from a saved snapshot or a fresh one (`--current`), with an end-to-end test on a real kernel tree | |
| `fwd.modalias` | [ ] | forward | Read `modules.alias` and `modules.builtin.alias` from the built tree, the output of `modpost` and `depmod`, and refuse when they are missing; never derive them from source | |
| `fwd.select` | [x] | forward | Follow `select` chains in the report, so implied options carry a reason. An option forced by `select` whose own dependencies are unmet is reported as forced, not solved, and `verify` has the final say | `tests/test_select.py::test_select_forced_option_with_unmet_dependency_is_forced_not_solved` |
| `fwd.roles` | [ ] | forward | Role fragments (networking, containers) with the same provenance as hardware | |
| `fwd.surface` | [ ] | forward | Attack-surface report: which options bring which code, and banned-feature checks | |
| `fwd.builtin` | [ ] | forward | With `CONFIG_MODULES` off, map drivers to built-in symbols and say so in the report | |
| `fwd.banned` | [ ] | forward | Take the banned-feature list from the firmware's `kernel/banned.list` as the input to the attack-surface report, not a list of its own | |
| `test.fixture-tree` | [ ] | test | A small kernel-tree fixture, so `generate` runs end to end in CI without the network; this closes `cli.generate` | |
| `ci.golden` | [ ] | ci | A checked-in golden fragment for the firmware kernel, so a change in the tool shows as a diff in CI | |

| `rev.evidence` | [ ] | reverse | Recover evidence from a kernel image: embedded config, kallsyms, `__ksymtab`, `__kcrctab`, vermagic | |
| `rev.symbols` | [ ] | reverse | Symbol presence: `obj-$(CONFIG_X)` makes a present symbol evidence for its option | |
| `rev.crc` | [ ] | reverse | CRC sensitivity map: flip one option at a time, record which modversion CRCs change | |
| `rev.structs` | [ ] | reverse | Struct offsets from disassembly (Ghidra) as evidence for conditional fields | |
| `rev.combine` | [ ] | reverse | Combine evidence with Kconfig constraints, reporting confidence and unresolved options | |
| `rev.validate` | [ ] | reverse | Validate on kernels whose real config is known, before trusting it on vendor firmware | |
| `oot.report` | [ ] | out-of-tree | Report unclaimed devices that have a known out-of-tree driver as such, not as simply unclaimed | |
| `oot.model` | [ ] | out-of-tree | Model out-of-tree drivers as inputs, so their options and firmware needs get reasons like any other | |

The out-of-tree driver work itself is tracked in the router firmware roadmap.
