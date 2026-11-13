# Roadmap

Each row is one obligation. A row moves to done only when its named test exists, passes, and would fail
if the behaviour broke. `ROADMAP.md` is the source of truth; the GitHub issues are derived from it.

| Id | Status | Area | Obligation | Evidence |
|---|---|---|---|---|
| `fwd.reader` | [x] | forward | Kconfig dependency reader, Makefile module map, minimal solver, reasons per option | `tests/test_pipeline.py::test_every_option_records_a_reason` |
| `fwd.verify` | [x] | forward | `verify` checks a fragment against the kernel's own resolved `.config` | `tests/test_pipeline.py::test_verify_names_the_blocking_dependency` |
| `cli.snapshot` | [x] | cli | `snapshot` exports a hardware snapshot from this machine or over SSH, from one stdlib-only module | `tests/test_snapshot.py::test_snapshot_command_writes_a_file` |
| `cli.generate` | [x] | cli | `generate` writes a fragment from a saved snapshot or a fresh one (`--current`), with an end-to-end test on a real kernel tree | `tests/test_generate.py::test_generate_from_snapshot_writes_fragment_and_report`, `tests/test_generate.py::test_generate_current_collects_then_generates`, `tests/test_generate.py::test_generate_refuses_a_snapshot_with_no_devices` |
| `fwd.modalias` | [x] | forward | Read `modules.alias` and `modules.builtin.alias` from the built tree, the output of `modpost` and `depmod`, and refuse when they are missing; never derive them from source | `tests/test_built_tree.py::test_missing_alias_file_is_refused_by_name` |
| `fwd.select` | [x] | forward | Follow `select` chains in the report, so implied options carry a reason. An option forced by `select` whose own dependencies are unmet is reported as forced, not solved, and `verify` has the final say | `tests/test_select.py::test_select_forced_option_with_unmet_dependency_is_forced_not_solved` |
| `fwd.roles` | [ ] | forward | Role fragments (networking, containers) with the same provenance as hardware | |
| `fwd.surface` | [x] | forward | Attack-surface report: which options bring which code, and banned-feature checks | `tests/test_surface.py::test_each_enabled_option_brings_the_modules_it_builds`, `tests/test_surface.py::test_enabled_banned_option_is_reported_from_a_fragment` |
| `fwd.builtin` | [x] | forward | With `CONFIG_MODULES` off, map drivers to built-in symbols and say so in the report | `tests/test_built_tree.py::test_modules_off_is_reported_and_drivers_are_mapped` |
| `fwd.banned` | [x] | forward | Take the banned-feature list from the firmware's `kernel/banned.list` as the input to the attack-surface report, not a list of its own | `tests/test_surface.py::test_the_banned_file_is_the_only_list_checked`, `tests/test_surface.py::test_banned_list_is_read_one_option_per_line` |
| `fwd.exclude` | [x] | forward | Take an exclude list as input: an excluded option is never enabled, and nothing it depends on or selects is followed; the report names each one a device wanted | `tests/test_exclude.py::test_excluded_symbol_is_not_enabled_and_neither_is_what_it_selects_or_needs` |
| `test.fixture-tree` | [x] | test | A small kernel-tree fixture, so `generate` runs end to end in CI without the network; this closes `cli.generate` | `tests/test_generate.py::test_fixture_tree_has_the_shape_generate_needs`, `tests/test_generate.py::test_generate_from_snapshot_writes_fragment_and_report` |
| `ci.golden` | [part] | ci | A checked-in golden fragment for the firmware kernel, so a change in the tool shows as a diff in CI; the mechanism is built and tested on the synthetic fixture, and the firmware's real golden still has to be generated in the builder and checked in, with a CI step that regenerates and diffs it. It depends on `fwd.reproducible` | `tests/test_golden.py::test_regenerated_fragment_matches_the_checked_in_golden` |
| `snap.boot-only` | [x] | snapshot | Record modules that load only at boot or on demand, and list drivers the snapshot cannot see, so a fragment states what it could not cover | `tests/test_snapshot.py::test_boot_only_modules_are_recorded_as_seen` |
| `verify.exact-lines` | [x] | verify | Match every fragment line verbatim against the resolved `.config`, so `CONFIG_NR_CPUS=1` never matches `CONFIG_NR_CPUS=128` | `tests/test_verify_exact.py::test_nr_cpus_1_is_not_accepted_for_nr_cpus_128` |
| `fwd.reproducible` | [x] | forward | Flag options that break reproducible builds (absolute paths such as `CONFIG_DEBUG_EFI`, timestamps, `CONFIG_BUILD_SALT`) in the report and in `verify` | `tests/test_reproducible.py::test_every_documented_option_stays_flagged` |
| `fwd.diff` | [x] | forward | Produce a fragment from the diff between a golden config and a build config, with each line's reason carried over | `tests/test_fragments.py::test_diff_applied_to_golden_gives_build` |
| `fwd.minimal` | [x] | forward | A split mode that writes a minimal defconfig, keeping only the flags that differ from the kernel's defaults, for version control | `tests/test_fragments.py::test_minimal_defconfig_expands_to_the_same_config_under_the_kernels_conf` |
| `aud.unneeded` | [ ] | audit | An `audit` command for a machine that must keep modules: from a running config, a snapshot and a must-keep list, list the enabled options no present device or must-keep entry needs, as candidates to turn off, each with why it was not needed; never a verdict, because a device that is not plugged in is invisible to a snapshot | |

| `kc.entries` | [x] | kconfig | Read every entry kind the kernel grammar has (`config`, `menuconfig`, `menu`, `if`, `choice`, `source`), with block dependencies inherited by what is inside | `tests/test_kconfig_language.py::test_menu_dependency_is_inherited_until_endmenu` |
| `kc.expr` | [x] | kconfig | Parse dependency expressions with the kernel's precedence; a term that cannot be evaluated is reported, never guessed | `tests/test_kconfig_language.py::test_what_cannot_be_evaluated_is_unknown_never_guessed` |
| `kc.census` | [x] | kconfig | `tools/kconfig_census.py` counts what a tree uses and what the reader could not evaluate, so `docs/kconfig-coverage.md` is measured, not estimated | `tests/test_kconfig_census.py::test_scan_counts_statements_and_skips_help_bodies` |
| `kc.select-if` | [x] | kconfig | Keep the condition of `select X if <expr>` and follow the select only when the requested options make it hold (1,348 uses in 6.18.62); one not followed is reported with its condition | `tests/test_select_if.py::test_unmet_condition_is_not_followed_and_says_why` |
| `kc.choice` | [x] | kconfig | Model a `choice` as exactly one member on: proposing two members is a conflict with both reasons named, and the choice's `default` is known | `tests/test_choice.py::test_two_members_are_a_conflict_naming_both_reasons` |
| `kc.defaults` | [x] | kconfig | Record `default` and `def_bool` values with their `if` conditions, first visible one wins, so a promptless symbol is predicted on or off instead of assumed | `tests/test_defaults.py::test_the_first_visible_default_wins` |
| `kc.imply` | [x] | kconfig | Read `imply` and report implied options as likely on, with the implying option as the reason | `tests/test_imply.py::test_imply_obeys_the_direct_dependencies_of_the_target` |
| `kc.values` | [ ] | kconfig | Carry `int`, `hex` and `string` values from a given `.config`, check `range`, and evaluate `=`, `!=`, `<`, `>`, `<=`, `>=` against them | |
| `kc.tristate` | [ ] | kconfig | Three-valued evaluation (`n` < `m` < `y`, `&&` as min, `||` as max), the `modules` symbol, `depends on m` and `SYM = m` | |
| `kc.macro` | [ ] | kconfig | Read macro assignments and expand calls from recorded probe results (the `CC_*` symbols of a `.config`); never run a shell | |
| `kc.parser-losses` | [x] | kconfig | Fix three reader faults: an escaped quote ends a constant early, an attribute after `help` on a `menu` or `choice` is dropped, and a statement the grammar rejects is ignored silently | `tests/test_parser_losses.py::test_a_statement_the_grammar_rejects_is_reported_with_file_and_line` |
| `kc.conformance` | [ ] | kconfig | Differential test against the kernel's own `conf` on the pinned tree: for a set of requests, the predicted and resolved configurations agree, and the agreement rate is recorded | |
| `rev.evidence` | [ ] | reverse | Recover evidence from a kernel image: embedded config, kallsyms, `__ksymtab`, `__kcrctab`, vermagic | |
| `rev.symbols` | [ ] | reverse | Symbol presence: `obj-$(CONFIG_X)` makes a present symbol evidence for its option | |
| `rev.crc` | [ ] | reverse | CRC sensitivity map: flip one option at a time, record which modversion CRCs change | |
| `rev.structs` | [ ] | reverse | Struct offsets from disassembly (Ghidra) as evidence for conditional fields | |
| `rev.combine` | [ ] | reverse | Combine evidence with Kconfig constraints, reporting confidence and unresolved options | |
| `rev.validate` | [ ] | reverse | Validate on kernels whose real config is known, before trusting it on vendor firmware | |
| `oot.report` | [ ] | out-of-tree | Report unclaimed devices that have a known out-of-tree driver as such, not as simply unclaimed | |
| `oot.model` | [ ] | out-of-tree | Model out-of-tree drivers as inputs, so their options and firmware needs get reasons like any other | |

The out-of-tree driver work itself is tracked in the router firmware roadmap.
