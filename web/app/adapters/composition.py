# ABOUTME: CompositionPort over the deterministic conjurer scripts (stitch/lint/export).
# ABOUTME: Thin adapter; maps the linter's findings into the domain LintCheck type.

"""Script-backed :class:`CompositionPort`.

The conjurer engine lives in ``plugins/conjurer/skills/conjurer/scripts/`` and its
modules import each other by bare name (``stitch`` imports ``composer``), so that
directory is added to ``sys.path`` once at import time. This adapter then delegates
to the pure functions there: ``stitch_app_dir``, ``lint_app_dir``, ``export_app_dir``.

``lint`` depends on ``stitch`` having run, because the linter reads the stitched
``cover_letter.md`` / ``resume.md`` from disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.domain import LintCheck

# The conjurer scripts directory, relative to the repo root (three levels up from
# this file: app/adapters/ -> app/ -> web/ -> repo root).
_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "conjurer"
    / "skills"
    / "conjurer"
    / "scripts"
)


def _ensure_scripts_on_path(scripts_dir: Path = _SCRIPTS_DIR) -> None:
    """Add the conjurer scripts dir to sys.path once so its bare-name imports resolve."""
    entry = str(scripts_dir)
    if entry not in sys.path:
        sys.path.append(entry)


_ensure_scripts_on_path()

from stitch import stitch_app_dir  # noqa: E402
from lint import lint_app_dir  # noqa: E402
from export_docs import export_app_dir  # noqa: E402


class ScriptCompositionPort:
    """Runs stitch/lint/export against one application directory in the workspace."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _app_dir(self, slug: str) -> Path:
        return self.root / "applications" / slug

    def stitch(self, slug: str) -> None:
        stitch_app_dir(
            app_dir=self._app_dir(slug),
            master_resume_path=self.root / "master-resume.md",
            overwrite=True,
        )

    def lint(self, slug: str) -> list[LintCheck]:
        findings = lint_app_dir(self._app_dir(slug))
        return [
            LintCheck(
                label=finding.rule,
                detail=f"{finding.file.name}:{finding.line} {finding.snippet}",
                passed=False,
            )
            for finding in findings
        ]

    def export(self, slug: str, formats: tuple[str, ...] = ("pdf", "docx")) -> dict[str, str]:
        return export_app_dir(self._app_dir(slug), formats)
