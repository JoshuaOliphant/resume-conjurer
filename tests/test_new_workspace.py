# ABOUTME: Tests for workspace bootstrap — scaffolding missing template files into a directory.
# ABOUTME: Verifies it fills an empty dir, coexists with existing files, and never clobbers.
import new_workspace


def test_scaffolds_empty_dir(tmp_path):
    ws = new_workspace.new_workspace(tmp_path / "ws")
    assert (ws / "grimoire.md").exists()
    assert (ws / "master-resume.md").exists()
    assert (ws / "applications").is_dir()


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
