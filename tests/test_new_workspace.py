# ABOUTME: Tests for workspace bootstrap — scaffolding missing template files into a directory.
# ABOUTME: Verifies it fills an empty dir, coexists with existing files, and never clobbers.
import re
import sys

import new_workspace


def _section(markdown, heading):
    match = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL)
    assert match, f"no ## {heading} section"
    return match.group(1)


def test_scaffolds_empty_dir(tmp_path):
    ws = new_workspace.new_workspace(tmp_path / "ws")
    assert (ws / "grimoire.md").exists()
    assert (ws / "master-resume.md").exists()
    assert (ws / "applications").is_dir()


def test_scaffolded_grimoire_writes_for_an_outside_reader(tmp_path):
    grimoire = (new_workspace.new_workspace(tmp_path / "ws") / "grimoire.md").read_text()

    table_rows = [line for line in _section(grimoire, "Glossary").splitlines() if line.startswith("|")]
    header = [cell.strip() for cell in table_rows[0].strip("|").split("|")]
    assert header == ["Internal term", "Aliases", "Public description"]
    assert len(table_rows) >= 3, "the template shows one example row under the header and separator"

    voice = _section(grimoire, "Voice")
    assert "outside reader" in voice
    assert "Glossary's public description" in voice
    assert "keep the number" in voice
    assert "Name the technology, the system" not in grimoire

    assert "Glossary leak check" in _section(grimoire, "Linter Checklist")


def test_scaffolds_into_non_empty_dir(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "resume.pdf").write_text("existing resume")
    new_workspace.new_workspace(ws)
    assert (ws / "grimoire.md").exists()
    assert (ws / "master-resume.md").exists()
    assert (ws / "resume.pdf").read_text() == "existing resume"  # untouched


def test_does_not_clobber_existing_workspace_files(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "grimoire.md").write_text("MY REAL GRIMOIRE")
    new_workspace.new_workspace(ws)
    assert (ws / "grimoire.md").read_text() == "MY REAL GRIMOIRE"  # not overwritten
    assert (ws / "master-resume.md").exists()  # the missing one still scaffolded


def test_workspace_cli_uses_explicit_and_current_directory(tmp_path, monkeypatch, capsys):
    target = tmp_path / "explicit"
    monkeypatch.setattr(sys, "argv", ["new_workspace.py", str(target)])
    new_workspace.main()
    assert capsys.readouterr().out == (
        f"Workspace ready at {target}\n"
        "Fill the templates with /conjurer:grimoire and /conjurer:master-resume.\n"
    )
    assert (target / "master-resume.md").exists()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["new_workspace.py"])
    new_workspace.main()
    assert f"Workspace ready at {tmp_path}\n" in capsys.readouterr().out
    assert (tmp_path / "grimoire.md").exists()
