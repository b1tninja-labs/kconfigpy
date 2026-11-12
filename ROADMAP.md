# Roadmap

Each row is one obligation. A row moves to done only when its named test exists, passes, and would fail
if the behaviour broke. `ROADMAP.md` is the source of truth; the GitHub issues are derived from it.

| Id | Status | Area | Obligation | Evidence |
|---|---|---|---|---|
| `fwd.reader` | [x] | forward | Kconfig dependency reader, Makefile module map, minimal solver, reasons per option | `tests/test_pipeline.py::test_every_option_records_a_reason` |
| `fwd.verify` | [x] | forward | `verify` checks a fragment against the kernel's own resolved `.config` | `tests/test_pipeline.py::test_verify_names_the_blocking_dependency` |
| `fwd.modalias` | [ ] | forward | Generate `modules.alias` from the exact tree instead of accepting one from a host | |
| `fwd.select` | [ ] | forward | Follow `select` chains in the report, so implied options also carry a reason | |
| `fwd.roles` | [ ] | forward | Role fragments (networking, containers) with the same provenance as hardware | |
| `fwd.surface` | [ ] | forward | Attack-surface report: which options bring which code, and banned-feature checks | |
| `rev.evidence` | [ ] | reverse | Recover evidence from a kernel image: embedded config, kallsyms, `__ksymtab`, `__kcrctab`, vermagic | |
| `rev.symbols` | [ ] | reverse | Symbol presence: `obj-$(CONFIG_X)` makes a present symbol evidence for its option | |
| `rev.crc` | [ ] | reverse | CRC sensitivity map: flip one option at a time, record which modversion CRCs change | |
| `rev.structs` | [ ] | reverse | Struct offsets from disassembly (Ghidra) as evidence for conditional fields | |
| `rev.combine` | [ ] | reverse | Combine evidence with Kconfig constraints, reporting confidence and unresolved options | |
| `rev.validate` | [ ] | reverse | Validate on kernels whose real config is known, before trusting it on vendor firmware | |
| `oot.report` | [ ] | out-of-tree | Report unclaimed devices that have a known out-of-tree driver as such, not as simply unclaimed | |
| `oot.model` | [ ] | out-of-tree | Model out-of-tree drivers as inputs, so their options and firmware needs get reasons like any other | |

The out-of-tree driver work itself is tracked in the router firmware roadmap.
