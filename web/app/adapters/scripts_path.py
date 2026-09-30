# ABOUTME: Puts the conjurer plugin's scripts directory on sys.path for the adapters that import it.
# ABOUTME: The scripts import each other by bare name, so the directory itself must be importable.

from __future__ import annotations

import sys
from pathlib import Path

# The conjurer scripts directory, relative to the repo root (three levels up from
# this file: app/adapters/ -> app/ -> web/ -> repo root).
SCRIPTS_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "conjurer"
    / "skills"
    / "conjurer"
    / "scripts"
)


def ensure_scripts_on_path(scripts_dir: Path = SCRIPTS_DIR) -> None:
    """Add the conjurer scripts dir to sys.path once so its bare-name imports resolve."""
    entry = str(scripts_dir)
    if entry not in sys.path:
        sys.path.append(entry)
