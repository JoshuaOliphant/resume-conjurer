# ABOUTME: Tests doc export — pandoc detection and the no-pandoc fallback.
# ABOUTME: Verifies fallback skips cleanly without raising and only targets existing sources.
import export_docs
import pytest
import sys


def test_export_fallback_when_no_pandoc(tmp_path, monkeypatch):
    monkeypatch.setattr(export_docs.shutil, "which", lambda _: None)
    app = tmp_path / "app"
    app.mkdir()
    (app / "cover_letter.md").write_text("# Cover\n")
    (app / "resume.md").write_text("# Resume\n")
    results = export_docs.export_app_dir(app, formats=("pdf", "docx"))
    assert results["cover_letter.pdf"].startswith("skipped")
    assert results["resume.docx"].startswith("skipped")
    assert not (app / "cover_letter.pdf").exists()


def test_export_skips_missing_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(export_docs.shutil, "which", lambda _: None)
    app = tmp_path / "app"
    app.mkdir()
    (app / "resume.md").write_text("# Resume\n")  # no cover_letter.md
    results = export_docs.export_app_dir(app, formats=("pdf",))
    assert "resume.pdf" in results
    assert "cover_letter.pdf" not in results


def test_export_writes_requested_formats_with_pandoc(tmp_path, monkeypatch):
    pandoc = tmp_path / "pandoc"
    pandoc.write_text("#!/bin/sh\nprintf '%s' \"$1\" > \"$3\"\n")
    pandoc.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    app = tmp_path / "app"
    app.mkdir()
    (app / "cover_letter.md").write_text("Cover letter")
    (app / "resume.md").write_text("Resume")

    results = export_docs.export_app_dir(app, formats=("pdf", "docx"))

    assert results == {name: "written" for name in (
        "cover_letter.pdf", "cover_letter.docx", "resume.pdf", "resume.docx"
    )}
    assert (app / "cover_letter.pdf").read_text() == str(app / "cover_letter.md")
    assert (app / "resume.docx").read_text() == str(app / "resume.md")


def test_export_cli_reports_usage_and_empty_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["export_docs.py"])
    with pytest.raises(SystemExit, match="2"):
        export_docs.main()
    assert "usage: python3 export_docs.py" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["export_docs.py", str(tmp_path)])
    export_docs.main()
    assert capsys.readouterr().out == "Nothing to export (run stitch first).\n"


def test_export_cli_reports_each_target(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(export_docs.shutil, "which", lambda _: None)
    (tmp_path / "resume.md").write_text("Resume")
    monkeypatch.setattr(sys, "argv", ["export_docs.py", str(tmp_path), "docx"])

    export_docs.main()

    assert capsys.readouterr().out == "resume.docx: skipped: pandoc not installed (markdown source kept)\n"
