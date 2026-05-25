# ABOUTME: Bootstraps a conjurer workspace by scaffolding missing template files into a directory.
# ABOUTME: Default target is the current directory; never clobbers existing grimoire/master-resume.
import shutil
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TEMPLATES = ("grimoire.md", "master-resume.md")


def new_workspace(workspace_dir: Path) -> Path:
    """Scaffold any missing workspace files into workspace_dir.

    Creates the directory if needed, copies each template only when absent (never
    clobbering an existing grimoire.md or master-resume.md), and ensures applications/
    exists. Safe to run in a directory that already holds other files (such as the
    user's resume).
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for name in TEMPLATES:
        target = workspace_dir / name
        if not target.exists():
            shutil.copy(ASSETS / name, target)
    (workspace_dir / "applications").mkdir(exist_ok=True)
    return workspace_dir


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    ws = new_workspace(target)
    print(f"Workspace ready at {ws}")
    print("Fill the templates with /conjurer:grimoire and /conjurer:master-resume.")


if __name__ == "__main__":
    main()
