# ABOUTME: Tests for putting the conjurer scripts directory on sys.path.
# ABOUTME: The helper both script-backed adapters share.

from __future__ import annotations

import sys
from pathlib import Path

from app.adapters.scripts_path import ensure_scripts_on_path


def testensure_scripts_on_path_adds_once(tmp_path: Path) -> None:
    fresh = tmp_path / "scripts"
    assert str(fresh) not in sys.path
    ensure_scripts_on_path(fresh)  # absent -> appended
    assert sys.path.count(str(fresh)) == 1
    ensure_scripts_on_path(fresh)  # present -> no duplicate
    assert sys.path.count(str(fresh)) == 1
    sys.path.remove(str(fresh))
