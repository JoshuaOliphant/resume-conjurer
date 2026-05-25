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


def test_overwrite_true_recreates_existing_dir(tmp_path):
    app = init_app.init_app_dir("acme-platform", tmp_path)
    # Plant a marker file that should be gone after overwrite.
    marker = app / "marker.txt"
    marker.write_text("I should be deleted by overwrite.")
    # Re-init with overwrite=True should wipe and recreate cleanly.
    app2 = init_app.init_app_dir("acme-platform", tmp_path, overwrite=True)
    assert app2 == app
    assert not marker.exists(), "Marker file should have been removed by overwrite"
    assert (app2 / "jd.txt").exists()
    assert (app2 / "evidence.md").exists()
    assert (app2 / "README.md").exists()
