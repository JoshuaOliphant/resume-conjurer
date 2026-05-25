# ABOUTME: Tests doc export — pandoc detection and the no-pandoc fallback.
# ABOUTME: Verifies fallback skips cleanly without raising and only targets existing sources.
import export_docs


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
