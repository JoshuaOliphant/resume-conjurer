# ABOUTME: Composes final Markdown and exports validated Professional documents.
# ABOUTME: Keeps filesystem publication at the edge of the deterministic pipeline.

"""Script-backed :class:`CompositionPort`.

The conjurer engine lives in ``plugins/conjurer/skills/conjurer/scripts/`` and its
modules import each other by bare name (``stitch`` imports ``composer``), so that
directory is added to ``sys.path`` once at import time.

``lint`` depends on ``stitch`` having run, because the linter reads the stitched
``cover_letter.md`` / ``resume.md`` from disk.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.adapters.scripts_path import ensure_scripts_on_path
from app.domain import LintCheck
from app.professional_export import ExportError, export_document

ensure_scripts_on_path()

from lint import lint_app_dir  # noqa: E402
from stitch import stitch_app_dir  # noqa: E402

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
        app_dir = self._app_dir(slug)
        results: dict[str, str] = {}
        for document in ("cover_letter", "resume"):
            source = app_dir / f"{document}.md"
            if not source.is_file():
                continue
            try:
                markdown = source.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                for format_name in formats:
                    results[f"{document}.{format_name}"] = f"skipped: cannot read final document: {exc}"
                continue
            for format_name in formats:
                filename = f"{document}.{format_name}"
                if format_name not in {"pdf", "docx"}:
                    results[filename] = "skipped: unsupported export format"
                    continue
                temporary_path: Path | None = None
                try:
                    descriptor, temporary = tempfile.mkstemp(
                        prefix=f".{document}.", suffix=f".{format_name}", dir=app_dir
                    )
                    temporary_path = Path(temporary)
                    os.close(descriptor)
                    export_document(markdown, format_name, temporary_path)
                    os.replace(temporary_path, app_dir / filename)
                except (ExportError, OSError) as exc:
                    results[filename] = f"skipped: {exc}"
                except Exception as exc:
                    results[filename] = f"skipped: renderer failed ({type(exc).__name__})"
                else:
                    results[filename] = "written"
                finally:
                    if temporary_path is not None:
                        try:
                            temporary_path.unlink(missing_ok=True)
                        except OSError:
                            results[filename] = "skipped: temporary export cleanup failed"
        return results

    def download(self, slug: str, filename: str) -> Path | None:
        if filename not in EXPORT_FILENAMES:
            return None
        app_dir = self._app_dir(slug).resolve()
        artifact = (app_dir / filename).resolve()
        if artifact.parent != app_dir or not artifact.is_file():
            return None
        return artifact
