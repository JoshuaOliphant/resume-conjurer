# ABOUTME: Tests for per-application scaffolding (jd.txt, evidence.md, README.md).
# ABOUTME: Verifies file creation, overwrite guard, and that templates carry no vault paths.
import init_app
import pytest


def test_init_creates_files(tmp_path):
    app = init_app.init_app_dir("acme-platform", tmp_path)
    assert (app / "jd.txt").exists()
    assert (app / "evidence.md").exists()
    assert (app / "README.md").exists()


def test_evidence_template_has_no_vault_paths(tmp_path):
    app = init_app.init_app_dir("acme-platform", tmp_path)
    evidence = (app / "evidence.md").read_text()
    assert "/areas/career" not in evidence


def test_existing_dir_raises_without_overwrite(tmp_path):
    init_app.init_app_dir("acme-platform", tmp_path)
    with pytest.raises(RuntimeError):
        init_app.init_app_dir("acme-platform", tmp_path)
