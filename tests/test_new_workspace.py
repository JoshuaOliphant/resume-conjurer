# ABOUTME: Tests for workspace bootstrap — copying templates and creating applications/.
# ABOUTME: Verifies grimoire.md, master-resume.md, and applications/ land in a fresh workspace.
import new_workspace
import pytest


def test_new_workspace_scaffolds(tmp_path):
    ws = new_workspace.new_workspace(tmp_path / "ws")
    assert (ws / "grimoire.md").exists()
    assert (ws / "master-resume.md").exists()
    assert (ws / "applications").is_dir()


def test_existing_workspace_raises(tmp_path):
    new_workspace.new_workspace(tmp_path / "ws")
    with pytest.raises(RuntimeError):
        new_workspace.new_workspace(tmp_path / "ws")
