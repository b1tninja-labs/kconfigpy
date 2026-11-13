"""One test per Kconfig construct the reader claims to handle. docs/kconfig-coverage.md cites these by name."""

from __future__ import annotations

from pathlib import Path

from kconfigpy.kconfig import And, Const, KconfigDb, Not, Sym, Unknown, parse_expr, read_kconfig


def _read(tmp_path: Path, files: dict[str, str]) -> KconfigDb:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return read_kconfig(tmp_path)


def _deps(db: KconfigDb, name: str) -> list[object]:
    definition = db.preferred(name)
    assert definition is not None
    return list(definition.all_deps())


def test_config_and_menuconfig_define_typed_symbols(tmp_path: Path) -> None:
    db = _read(tmp_path, {"Kconfig": 'config A\n\tbool "a"\nmenuconfig B\n\ttristate "b"\nconfig C\n\tint "c"\n'})
    assert [db.preferred(n).kind for n in "ABC"] == ["bool", "tristate", "int"]  # type: ignore[union-attr]
    assert db.is_settable("A") and db.is_settable("B")
    assert not db.is_settable("C"), "an int has a prompt but is not a y/m/n switch"


def test_menu_dependency_is_inherited_until_endmenu(tmp_path: Path) -> None:
    text = 'menu "m"\n\tdepends on NET\nconfig IN\n\tbool "in"\nendmenu\nconfig OUT\n\tbool "out"\n'
    db = _read(tmp_path, {"Kconfig": text})
    assert _deps(db, "IN") == [Sym("NET")]
    assert _deps(db, "OUT") == []


def test_if_block_dependency_is_inherited_until_endif(tmp_path: Path) -> None:
    text = 'if X && !Y\nconfig IN\n\tbool "in"\nendif\nconfig OUT\n\tbool "out"\n'
    db = _read(tmp_path, {"Kconfig": text})
    assert _deps(db, "IN") == [And(Sym("X"), Not(Sym("Y")))]
    assert _deps(db, "OUT") == []


def test_choice_dependency_is_inherited_by_its_members(tmp_path: Path) -> None:
    text = 'choice\n\tprompt "pick"\n\tdepends on BASE\nconfig ONE\n\tbool "one"\nconfig TWO\n\tbool "two"\nendchoice\n'
    db = _read(tmp_path, {"Kconfig": text})
    assert _deps(db, "ONE") == [Sym("BASE")]
    assert _deps(db, "TWO") == [Sym("BASE")]


def test_source_expands_srcarch_and_records_a_missing_file(tmp_path: Path) -> None:
    files = {
        "Kconfig": 'source "arch/$(SRCARCH)/Kconfig"\nsource "gone/Kconfig"\n',
        "arch/x86/Kconfig": 'config FROM_ARCH\n\tbool "x"\n',
    }
    db = _read(tmp_path, files)
    assert "FROM_ARCH" in db.definitions
    assert db.missing_sources == ["gone/Kconfig"]


def test_backslash_continuation_joins_one_dependency(tmp_path: Path) -> None:
    db = _read(tmp_path, {"Kconfig": 'config A\n\tbool "a"\n\tdepends on X && \\\n\t\tY\n'})
    assert _deps(db, "A") == [And(Sym("X"), Sym("Y"))]


def test_help_text_is_skipped_and_the_next_entry_still_parses(tmp_path: Path) -> None:
    text = 'config A\n\tbool "a"\n\thelp\n\t  depends on NOT_A_DEP\n\t  config NOT_A_SYMBOL\n\nconfig B\n\tbool "b"\n'
    db = _read(tmp_path, {"Kconfig": text})
    assert sorted(db.definitions) == ["A", "B"]
    assert _deps(db, "A") == []


def test_equality_with_a_tristate_constant_is_the_symbol_or_its_negation() -> None:
    assert parse_expr("FOO = y") == Sym("FOO")
    assert parse_expr("FOO != n") == Sym("FOO")
    assert parse_expr("FOO = n") == Not(Sym("FOO"))
    assert parse_expr('FOO != "y"') == Not(Sym("FOO"))


def test_what_cannot_be_evaluated_is_unknown_never_guessed() -> None:
    for text in ("$(cc-option,-fstack-protector)", "NR_CPUS >= 64", 'ARCH = "x86"', "A = B"):
        assert isinstance(parse_expr(text), Unknown), text


def test_precedence_is_not_then_and_then_or() -> None:
    parsed = parse_expr("!A && B || C")
    assert parsed == parse_expr("((!A) && B) || C")
    assert parse_expr("m") == Const("m")


def test_prompt_condition_is_a_dependency_only_when_nothing_defaults(tmp_path: Path) -> None:
    text = 'config GATED\n\tbool "g" if EXPERT\nconfig DEFAULTED\n\tbool "d" if EXPERT\n\tdefault y\n'
    db = _read(tmp_path, {"Kconfig": text})
    assert _deps(db, "GATED") == [Sym("EXPERT")]
    assert _deps(db, "DEFAULTED") == [], "it still gets a value from its default when the prompt is hidden"


def test_def_bool_sets_the_type_and_a_default_without_a_prompt(tmp_path: Path) -> None:
    db = _read(tmp_path, {"Kconfig": "config AUTO\n\tdef_bool y\n"})
    definition = db.preferred("AUTO")
    assert definition is not None
    assert (definition.kind, definition.has_default, definition.has_prompt) == ("bool", True, False)
    assert not db.is_settable("AUTO")


def test_a_symbol_defined_twice_keeps_both_and_prefers_the_prompted_one(tmp_path: Path) -> None:
    text = 'config TWICE\n\tbool\n\tdepends on A\nconfig TWICE\n\tbool "t"\n\tdepends on B\n'
    db = _read(tmp_path, {"Kconfig": text})
    assert len(db.definitions["TWICE"]) == 2
    assert _deps(db, "TWICE") == [Sym("B")]


def test_select_records_the_selected_symbol(tmp_path: Path) -> None:
    db = _read(tmp_path, {"Kconfig": 'config A\n\tbool "a"\n\tselect LIB\nconfig LIB\n\tbool\n'})
    definition = db.preferred("A")
    assert definition is not None and definition.selects == ["LIB"]
