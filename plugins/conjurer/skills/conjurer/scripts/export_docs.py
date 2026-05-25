# ABOUTME: Exports the stitched cover_letter.md and resume.md to PDF/docx via pandoc if installed.
# ABOUTME: Falls back to a clear message when pandoc is absent; no hard dependency.
import shutil
import subprocess
import sys
from pathlib import Path

SOURCES = ("cover_letter.md", "resume.md")


def pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def export_app_dir(app_dir: Path, formats=("pdf", "docx")) -> dict:
    """Export each existing source doc in app_dir to the requested formats.

    Returns a dict mapping output filename -> "written" | "skipped: <reason>".
    When pandoc is not installed, every target is skipped with that reason and no
    exception is raised; the markdown sources remain the deliverable.
    """
    results: dict[str, str] = {}
    have_pandoc = pandoc_available()
    for src_name in SOURCES:
        src = app_dir / src_name
        if not src.exists():
            continue
        for fmt in formats:
            out = app_dir / f"{src.stem}.{fmt}"
            if not have_pandoc:
                results[out.name] = "skipped: pandoc not installed (markdown source kept)"
                continue
            subprocess.run(["pandoc", str(src), "-o", str(out)], check=True)
            results[out.name] = "written"
    return results


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python3 export_docs.py <app_dir> [pdf|docx ...]", file=sys.stderr)
        raise SystemExit(2)
    app_dir = Path(sys.argv[1])
    fmts = tuple(sys.argv[2:]) or ("pdf", "docx")
    results = export_app_dir(app_dir, fmts)
    if not results:
        print("Nothing to export (run stitch first).")
        return
    for name, status in results.items():
        print(f"{name}: {status}")


if __name__ == "__main__":
    main()
