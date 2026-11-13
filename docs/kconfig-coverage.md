# Kconfig language coverage

What of the Kconfig language kconfigpy reads, what it deliberately skips, and what it gets wrong today.

The reference is the kernel's own definition, at the pinned version (Linux 6.18.62):
`Documentation/kbuild/kconfig-language.rst`, `Documentation/kbuild/kconfig-macro-language.rst`, and the
grammar in `scripts/kconfig/parser.y`. Where the prose and the grammar differ, the grammar wins.

## Where it stands

Measured on the 6.18.62 tree for x86 with `tools/kconfig_census.py` (run it again when the kernel changes):

| Measure | Count |
|---|---|
| Kconfig files read | 1,633 |
| Symbols (definitions) | 18,456 (18,474) |
| `source` targets not found | 0 |
| Dependency expression terms | 72,310 |
| Terms the reader could not evaluate | 225 (0.3%) |

So the structure and the dependency graph are read almost completely. The losses that remain are in **value
semantics** (`int`, `hex` and `string` values, three-valued logic, macros). `default`, `imply` and `choice` are
read with their conditions. The condition of the 1,348 `select ... if` lines (9% of all selects) is kept and judged
against the request, as far as the request decides it.

kconfigpy never decides what a configuration resolves to. It proposes a fragment, the kernel's `conf`
resolves it, and `verify` compares the two. The last column of each table says what a gap costs under
that rule.

## Status words

- **done**: read and used. A named test fails if it breaks.
- **partial**: read, with the stated loss.
- **skipped**: not read, and it cannot make a proposal wrong (presentation, or documentation).
- **gap**: not read, and it can make a proposal wrong. Each has a row in `ROADMAP.md`.

Tests are in `tests/test_kconfig_language.py` unless a file is named.

## Entries

| Construct | Uses | Status | What the reader does | Evidence or roadmap row |
|---|---|---|---|---|
| `config` | 18,159 | done | Defines a symbol with file and line | `test_config_and_menuconfig_define_typed_symbols` |
| `menuconfig` | 315 | done | Same as `config`; the menu hint is presentation | same test |
| The same symbol defined twice | 18 symbols | done | Keeps every definition; prefers the one with a prompt | `test_a_symbol_defined_twice_keeps_both_and_prefers_the_prompted_one` |
| `menu` / `endmenu` | 337 | done | Its `depends on` applies to every entry inside | `test_menu_dependency_is_inherited_until_endmenu` |
| `if` / `endif` | 701 | done | Its expression applies to every entry inside | `test_if_block_dependency_is_inherited_until_endif` |
| `choice` / `endchoice`, as a block | 76 | done | Its `depends on` applies to the members, also when written after the choice's `help` | `test_choice_dependency_is_inherited_by_its_members`; `tests/test_parser_losses.py::test_an_attribute_after_help_on_a_choice_is_kept` |
| `choice`, as exclusion | 76 | done | The members are recorded with the choice's `default` lines and `optional`. A second member proposed while one is on is a conflict naming both reasons. A tristate choice is treated as a bool one until `kc.tristate` | `tests/test_choice.py::test_two_members_are_a_conflict_naming_both_reasons`; `tests/test_choice.py::test_reader_records_the_members_and_the_default_of_a_choice` |
| `source` | 1,510 | done | Follows the file once, expanding `$(SRCARCH)`; a missing file is recorded, not ignored | `test_source_expands_srcarch_and_records_a_missing_file` |
| `comment` | 190 | skipped | Presentation only | |
| `mainmenu` | 1 | skipped | Presentation only | |

## Attributes

| Construct | Uses | Status | What the reader does | Evidence or roadmap row |
|---|---|---|---|---|
| `bool`, `tristate` | 17,550 | done | Type; a quoted prompt makes the symbol settable | `test_config_and_menuconfig_define_typed_symbols` |
| `int`, `hex`, `string` | 359 | partial | Type is recorded. Values are not, so the symbol is never proposed | `kc.values` |
| `prompt`, and a prompt on the type line | 15,445 symbols | done | Marks the symbol settable | same test |
| `"prompt" if <expr>` | 702 | done | A dependency when nothing else gives the symbol a value | `test_prompt_condition_is_a_dependency_only_when_nothing_defaults` |
| `depends on` | 17,852 | done | Every one is kept and all must hold | `test_backslash_continuation_joins_one_dependency` |
| `def_bool`, `def_tristate` | 560 | done | Type, and a default: the value and its `if` are kept in file order. Only a `y`/`m`/`n` value or a symbol expression is evaluated; an `int`, `hex` or `string` value is not (`kc.values`) | `test_def_bool_sets_the_type_and_a_default_without_a_prompt`; `tests/test_defaults.py::test_reader_keeps_each_default_value_with_its_condition_in_order` |
| `default` | 4,204 | done | The value and its `if` are kept in file order, split on the top-level `if` so a compound value survives | `tests/test_defaults.py::test_a_value_with_a_compound_expression_is_split_on_the_top_level_if` |
| `select` | 15,401 | partial | The target is recorded and followed | `test_select_records_the_selected_symbol`, `tests/test_select.py::test_select_chain_is_followed_and_each_option_has_a_reason` |
| `select ... if <expr>` | 1,348 | done | The condition is kept. The select is followed only when the requested options decide that it holds; otherwise it is listed as not followed, with the condition | `tests/test_select_if.py::test_unmet_condition_is_not_followed_and_says_why` |
| `imply` | 451 | done | The target and its `if` are kept. An implied option is reported as likely on only when its own direct dependencies and the `if` hold; it is never put in the fragment | `tests/test_imply.py::test_imply_obeys_the_direct_dependencies_of_the_target` |
| `range` | 120 | gap | Not read | `kc.values` |
| `modules` | 1 | gap | Not read; `MODULES` is an ordinary symbol to the reader | `kc.tristate` |
| `visible if` | 19 | skipped | Hides a menu from a person. Symbols inside can still be set | |
| `transitional` | 1 | skipped | Only affects which names `conf` writes back | |
| `help` | 15,141 | done | The body is skipped by indentation, so text in it is never parsed | `test_help_text_is_skipped_and_the_next_entry_still_parses` |

## Expressions

| Construct | Status | What the reader does | Evidence or roadmap row |
|---|---|---|---|
| `<symbol>`, `y`, `m`, `n` | done | A symbol or a constant | `test_precedence_is_not_then_and_then_or` |
| `!`, `&&`, <code>&#124;&#124;</code>, `( )` | done | Kernel precedence: `!`, then `&&`, then <code>&#124;&#124;</code> | same test |
| `SYM = y`, `SYM != n`, and the negations | done | The symbol, or its negation | `test_equality_with_a_tristate_constant_is_the_symbol_or_its_negation` |
| `SYM = m` | partial | Read as "the symbol is on". Built-in and module are not told apart | `kc.tristate` |
| `depends on m` | partial | Reported as a conflict: it cannot be built in | `kc.tristate` |
| `=`, `!=` against a symbol, number or string | gap, reported | Becomes an unevaluated term naming the text (153 uses) | `test_what_cannot_be_evaluated_is_unknown_never_guessed`; `kc.values` |
| `<`, `>`, `<=`, `>=` | gap, reported | Same (39 uses) | same |
| `$(...)` inside an expression | gap, reported | Same (33 uses) | same; `kc.macro` |

An unevaluated term is never guessed. It is listed in the report with the option that needed it.

## Value semantics

This is where the reader stops and `conf` takes over.

| Rule in the kernel | Status | Effect today | Row |
|---|---|---|---|
| Three values, with `&&` as min and <code>&#124;&#124;</code> as max | gap | Two values. Enough for a kernel with `CONFIG_MODULES` off, which the router's is | `kc.tristate` |
| `select` forces a lower limit without visiting the target's dependencies | done | A select-forced option with unmet dependencies is reported as forced, not solved | `tests/test_select.py::test_select_forced_option_with_unmet_dependency_is_forced_not_solved` |
| A symbol with no prompt gets its value only from `default` and `select` | done | It is still listed as left to the kernel; the report adds `predicted on` or `predicted off` with the default that decided it, and says nothing more when the request does not decide the conditions. A later `select` by an option nobody requested can still raise a symbol predicted off | `tests/test_defaults.py::test_default_n_or_no_applicable_default_predicts_off` |
| The first visible `default` wins | done | Defaults are tried in file order. One whose condition the request does not decide stops the search: which default wins is open. Its own direct dependencies must hold too | `tests/test_defaults.py::test_an_earlier_default_the_request_does_not_decide_blocks_the_later_one` |
| `imply` sets a default the user can turn off | done | Reported as likely on, or as not known to take effect with the reason | `tests/test_imply.py::test_an_implied_option_with_no_dependencies_is_likely_on_and_names_its_owner` |
| Exactly one member of a `choice` is on | done | A second member is a conflict, whether requested or selected | `tests/test_choice.py::test_a_select_of_a_second_member_is_a_conflict_too` |
| An `int` or `hex` must be inside its `range` | gap | No values are proposed at all | `kc.values` |

## Macro language

| Construct | Uses | Status | What the reader does | Row |
|---|---|---|---|---|
| `$(SRCARCH)`, `$(ARCH)`, `$(HEADER_ARCH)`, `$(srctree)` in `source` | all arch sources | done | Set from `--arch` | `test_source_expands_srcarch_and_records_a_missing_file` |
| `name = value`, `:=`, `+=` | 31, almost all in `scripts/Kconfig.include` | gap | Ignored | `kc.macro` |
| `$(shell,...)`, `$(success,...)`, `$(cc-option,...)` and other calls | 33 in dependencies; more in defaults | gap, reported | Never run. In a dependency it is an unevaluated term | `kc.macro` |
| `$(info,...)`, `$(warning-if,...)`, `$(error-if,...)` | few | skipped | Diagnostics from `conf` itself | |
| `$(filename)`, `$(lineno)` | few | skipped | Only used inside those diagnostics | |

kconfigpy will not run a shell to answer a compiler probe. `kc.macro` takes the answers as an input
instead: `conf` records every probe result as a symbol (`CC_IS_GCC`, `CC_HAS_...`) in the `.config` it writes.

## Lexical rules

| Rule | Status | Note | Evidence or row |
|---|---|---|---|
| `#` comments, blank lines | done | | covered by every test |
| A trailing backslash joins lines | done | | `test_backslash_continuation_joins_one_dependency` |
| Help ends at the first line indented less than its first line | done | | `test_help_text_is_skipped_and_the_next_entry_still_parses` |
| Quoted constants in single or double quotes | done | A backslash-escaped quote stays inside the constant | `tests/test_parser_losses.py::test_an_escaped_quote_does_not_end_a_constant_early` |
| An attribute written after `help` on a `menu` or `choice` | done | It is kept | `tests/test_parser_losses.py::test_an_attribute_after_help_on_a_menu_is_kept` |
| A statement the grammar rejects | done | Reported in `KconfigDb.errors` with file, line and text; reading goes on. Macro assignments and `$(call)` lines are not errors | `tests/test_parser_losses.py::test_a_statement_the_grammar_rejects_is_reported_with_file_and_line` |

## What a gap can cost

| Kind of loss | Example | Does `verify` catch it? |
|---|---|---|
| Asking for more than needed | Before `kc.select-if`: a `select ... if` whose condition is false was followed anyway | **No.** The extra options resolve and are kept. The fragment is valid but not minimal |
| Not following a select the kernel will follow | `select X if SMP`, where `SMP` is on by `default` and was not requested | Not a fragment error: `conf` applies the select itself. The report says the request does not decide the condition |
| Asking for something that cannot hold | Two members of one choice | Reported as a conflict before the build (`kc.choice`); `verify` would also show the dropped option |
| Not predicting what else turns on | `imply`, `default y` | Not a fragment error. The report now says what the defaults and `imply` predict where the request decides it; the attack-surface report must still read the resolved `.config`, not the fragment |
| A term that needs a value | `NR_CPUS >= 64` | Reported before the build as unevaluated |

The first row was the only loss `verify` could not see, and `kc.select-if` closed it. On the router's
snapshot against 6.18.62 the proposal went from 60 options to 52: `KGDB`, `DEBUG_KERNEL`, `SMP`, `PROC_FS`,
`SCHED_SMT`, `ACPI_CONTAINER`, `CPU_IDLE_GOV_MENU` and `CPU_IDLE_GOV_LADDER` are no longer requested, and 96
conditional selects are listed as not followed (93 the request does not decide, 3 not evaluated).

A condition is judged against what was requested, not against defaults: `kc.defaults` predicts a promptless
symbol from its own defaults, but does not feed that prediction back into other conditions. An option the request never mentions is **undecided**, not off: a default or another
fragment may turn it on. So `select X if !Y` is followed only when the request itself requires `Y` off.
The first version of this fix treated an unmentioned `Y` as off, and on the router it then requested
`CPU_IDLE_GOV_LADDER` (selected `if !NO_HZ && !NO_HZ_IDLE`) although a role fragment sets `NO_HZ_IDLE=y`.
Checking the resolved configuration against the previous one is what caught it.

## Completion

Of the 51 rows above, 32 are done, 4 are partial, 9 are gaps and 6 are skipped on purpose.
The rows that close the gaps, in the order that removes the most wrong proposals first:

1. `kc.select-if`: done.
2. `kc.choice`: done.
3. `kc.defaults`: done.
4. `kc.imply`: done.
5. `kc.values`: 359 valued symbols, 120 ranges, 192 comparisons.
6. `kc.tristate`: matters once a target builds modules.
7. `kc.macro`: 33 terms in dependencies, more in defaults.
8. `kc.parser-losses`: done.
9. `kc.conformance`: the measure of all of the above, as agreement with `conf` on the real tree.
