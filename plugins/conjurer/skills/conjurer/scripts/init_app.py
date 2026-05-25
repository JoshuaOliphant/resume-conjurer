# ABOUTME: Scaffolds a per-application working directory (jd.txt, evidence.md, README.md).
# ABOUTME: Templates are generic — no vault-specific paths.
import shutil
import sys
from datetime import datetime
from pathlib import Path

JD_TEMPLATE = """# Paste the job description below. Plain text is fine.
# Lines starting with # are ignored by the outline step.
# Title and company at the top help; the rest can be the full posting.

"""

EVIDENCE_TEMPLATE = """# Evidence for {slug}

List files, sections, or quoted spans the variant generator should draw from.
Every generated bullet or paragraph must cite from this pool. The model re-frames; it does not invent.

## Resume facts

- `master-resume.md` — full master resume (the primary evidence pool)

## Project receipts

- (add paths or quoted spans here, one per line)

## Quoted spans (optional, verbatim)

> Paste a sentence or paragraph that should be available verbatim.
> source: <where it came from>

"""

WORKFLOW_TEMPLATE = """# {slug} — Workflow

1. Paste the JD into `jd.txt`.
2. List evidence in `evidence.md`.
3. Ask Claude to run the conjurer pipeline (outline -> variants -> curate -> stitch -> lint).

Created: {created}
"""


def init_app_dir(slug: str, base_dir: Path, overwrite: bool = False) -> Path:
    app_dir = base_dir / slug
    if app_dir.exists():
        if not overwrite:
            raise RuntimeError(
                f"Application directory '{app_dir}' already exists. "
                f"Pass --overwrite to wipe and recreate, or choose a different slug."
            )
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    (app_dir / "jd.txt").write_text(JD_TEMPLATE)
    (app_dir / "evidence.md").write_text(EVIDENCE_TEMPLATE.format(slug=slug))
    (app_dir / "README.md").write_text(
        WORKFLOW_TEMPLATE.format(slug=slug, created=datetime.now().isoformat(timespec="seconds"))
    )
    return app_dir


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python3 init_app.py <slug> <workspace_dir> [--overwrite]", file=sys.stderr)
        raise SystemExit(2)
    slug, workspace = sys.argv[1], Path(sys.argv[2])
    overwrite = "--overwrite" in sys.argv[3:]
    app = init_app_dir(slug, workspace / "applications", overwrite=overwrite)
    print(f"Created {app}")


if __name__ == "__main__":
    main()
