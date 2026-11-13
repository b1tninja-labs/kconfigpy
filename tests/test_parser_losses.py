"""kc.parser-losses: an escaped quote, an attribute after help, and a statement the grammar rejects."""

from __future__ import annotations

from pathlib import Path

from kconfigpy.kconfig import And, KconfigDb, Sym, Unknown, parse_expr, read_kconfig


def _read(tmp_path: Path, files: dict[str, str]) -> KconfigDb:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return read_kconfig(tmp_path)


def test_an_escaped_quote_does_not_end_a_constant_early() -> None:
    parsed = parse_expr(r'A = "a\"b" && C')
    assert parsed == And(Unknown(r'A = "a\"b"'), Sym("C"))


def test_an_escaped_quote_in_a_prompt_does_not_hide_its_condition(tmp_path: Path) -> None:
    text = 'config A\n\tbool "say \\"hi\\"" if EXPERT\n'
    db = _read(tmp_path, {"Kconfig": text})
    definition = db.preferred("A")
    assert definition is not None and definition.has_prompt
    assert definition.prompt_condition == Sym("EXPERT")


def test_a_macro_assignment_with_an_escaped_quote_is_not_an_error(tmp_path: Path) -> None:
    db = _read(tmp_path, {"Kconfig": 'NAME = "a\\"b"\nconfig A\n\tbool "a"\n'})
    assert db.errors == []
    assert "A" in db.definitions


def test_an_attribute_after_help_on_a_choice_is_kept(tmp_path: Path) -> None:
    text = 'choice\n\tprompt "pick"\n\thelp\n\t  words\n\tdepends on BASE\nconfig ONE\n\tbool "one"\nendchoice\n'
    db = _read(tmp_path, {"Kconfig": text})
    definition = db.preferred("ONE")
    assert definition is not None and list(definition.all_deps()) == [Sym("BASE")]
    assert db.errors == []


def test_an_attribute_after_help_on_a_menu_is_kept(tmp_path: Path) -> None:
    text = 'menu "m"\n\thelp\n\t  words\n\tdepends on BASE\nconfig IN\n\tbool "in"\nendmenu\n'
    db = _read(tmp_path, {"Kconfig": text})
    definition = db.preferred("IN")
    assert definition is not None and list(definition.all_deps()) == [Sym("BASE")]


def test_a_statement_the_grammar_rejects_is_reported_with_file_and_line(tmp_path: Path) -> None:
    files = {
        "Kconfig": 'config A\n\tbool "a"\n\tfrobnicate X\nsource "sub/Kconfig"\n',
        "sub/Kconfig": 'config B\n\tbool "b"\nendif\nconfig\n',
    }
    db = _read(tmp_path, files)
    found = [(e.file, e.line, e.message) for e in db.errors]
    assert found == [
        ("Kconfig", 3, "unknown statement"),
        ("sub/Kconfig", 3, "endif does not close the open block"),
        ("sub/Kconfig", 4, "config needs a symbol name"),
    ]
    assert str(db.errors[0]) == "Kconfig:3: unknown statement: frobnicate X"
    assert sorted(db.definitions) == ["A", "B"], "reading goes on past a rejected statement"


def test_an_attribute_outside_any_entry_is_reported(tmp_path: Path) -> None:
    db = _read(tmp_path, {"Kconfig": 'bool "stray"\nconfig A\n\tbool "a"\n'})
    assert [(e.line, e.message) for e in db.errors] == [(1, "bool outside an entry")]


def test_a_valid_tree_has_no_errors(tmp_path: Path) -> None:
    text = (
        'mainmenu "x"\nmenu "m"\n\tdepends on A\nchoice\n\tprompt "p"\n\toptional\nconfig ONE\n\tbool "one"\n'
        'endchoice\nendmenu\nif B\ncomment "c"\n\tdepends on C\nendif\n$(warning-if,,x)\n'
    )
    assert _read(tmp_path, {"Kconfig": text}).errors == []
