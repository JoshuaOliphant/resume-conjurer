# ABOUTME: Exports the stitched cover_letter.md and resume.md to PDF/docx via pandoc if installed.
# ABOUTME: Falls back to a clear message when pandoc is absent or fails on a format; no hard dependency.
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
    exception is raised; the markdown sources remain the deliverable. A format pandoc
    fails on (PDF with no LaTeX engine installed, say) is skipped with pandoc's last
    stderr line, and the remaining targets are still exported.
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
            done = subprocess.run(["pandoc", str(src), "-o", str(out)], capture_output=True, text=True)
            if done.returncode == 0:
                results[out.name] = "written"
            else:
                reason = (done.stderr.strip().splitlines() or [f"exit status {done.returncode}"])[-1]
                results[out.name] = f"skipped: pandoc failed ({reason})"
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
