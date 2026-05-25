# ABOUTME: Bootstraps a conjurer workspace from bundled templates.
# ABOUTME: Writes grimoire.md + master-resume.md templates and an empty applications/ dir.
import shutil
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def new_workspace(workspace_dir: Path) -> Path:
    if workspace_dir.exists() and any(workspace_dir.iterdir()):
        raise RuntimeError(
            f"'{workspace_dir}' already exists and is not empty. Choose a fresh directory."
        )
    workspace_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ASSETS / "grimoire.md", workspace_dir / "grimoire.md")
    shutil.copy(ASSETS / "master-resume.md", workspace_dir / "master-resume.md")
    (workspace_dir / "applications").mkdir()
    return workspace_dir


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python3 new_workspace.py <workspace_dir>", file=sys.stderr)
        raise SystemExit(2)
    ws = new_workspace(Path(sys.argv[1]))
    print(f"Created workspace {ws}")
    print("Next: run /conjurer:grimoire and /conjurer:master-resume to fill the templates.")


if __name__ == "__main__":
    main()
