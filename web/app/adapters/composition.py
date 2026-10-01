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

from pathlib import Path

from app.adapters.scripts_path import ensure_scripts_on_path
from app.domain import LintCheck

ensure_scripts_on_path()

from stitch import stitch_app_dir  # noqa: E402
from lint import lint_app_dir  # noqa: E402
from export_docs import export_app_dir  # noqa: E402

EXPORT_FILENAMES = {
    f"{document}.{extension}"
    for document in ("cover_letter", "resume")
    for extension in ("md", "pdf", "docx")
}


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

    def download(self, slug: str, filename: str) -> Path | None:
        if filename not in EXPORT_FILENAMES:
            return None
        app_dir = self._app_dir(slug).resolve()
        artifact = (app_dir / filename).resolve()
        if artifact.parent != app_dir or not artifact.is_file():
            return None
        return artifact
