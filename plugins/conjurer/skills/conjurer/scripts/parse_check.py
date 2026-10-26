# ABOUTME: Reads the exported resume.pdf/resume.docx back as plain text and checks what an ATS parser would get.
# ABOUTME: Compares the extracted text with resume.md: contact details, headings, every bullet, and each role's dates.
"""Implementation of `python3 parse_check.py <app_dir>`.

Screeners such as Ashby, Greenhouse Talent Matching, and Workday HiredScore judge the text a
parser pulls out of the uploaded file, not the file as it looks. This script extracts that text
(`pdftotext -raw` for PDF, `extract_text.py` for docx) and checks it against the stitched
`resume.md` it was exported from. A hyphen that ends a line is joined to the next word first
(`fault-` + `tolerant` reads as `fault-tolerant`), as extractors that keep hyphens report it.

- `no-text`: the file yields no text at all (an image-only PDF).
- `contact-missing`: an email address or phone number from the resume header is not found.
- `heading-missing`: a `##` section heading is not a line of its own.
- `bullet-missing`: a bullet's words are not found in order. When they are found once hyphens
  are ignored, the detail names the hyphenated words the extractor dropped the hyphen from
  (`fault-tolerant` read as `faulttolerant`), or says the hyphens differ at a line break.
- `date-split`: a role's date range is broken across lines, so a line-by-line parser can miss
  the end date. Ranges are recognized with full or abbreviated month names (`January 2022`,
  `Jan. 2022`, `Sept 2022`) or numeric months (`01/2022`), ending in another date or
  `Present`; year-only ranges (`2019 – 2021`) are not checked.

`-raw` keeps the text in content-stream order, which matches reading order for the single-column
pandoc export; a two-column template could read out of order and set off `heading-missing` on
headings that render fine.

Prints `<file>\t<kind>\t<detail>` per finding and exits 1, or one clean line per checked file
and exits 0. A format whose extractor is missing is reported as skipped, not as a finding.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from extract_text import extract_docx_text

EXPORTS = ("resume.pdf", "resume.docx")

_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"'}
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPHASIS_RE = re.compile(r"[*_`]")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<text>.+)$")
_HEADING_RE = re.compile(r"^##\s+(?P<text>.+?)\s*$")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"\+?\d[\d .()-]{7,}\d")
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
_DATE = rf"(?:{_MONTH} \d{{4}}|\d{{1,2}}/\d{{4}})"
_DATE_RANGE_RE = re.compile(rf"\b{_DATE}\s*[–-]\s*(?:{_DATE}|Present)\b")
_LINE_END_HYPHEN_RE = re.compile(r"(?<=\w)-[ \t]*\n\s*(?=\w)")
_HYPHENATED_RE = re.compile(r"\w+(?:-\w+)+")
_HEADER_LINES = 5


class Finding(NamedTuple):
    file: str
    kind: str
    detail: str


def normalize(text: str) -> str:
    """Lowercase words with markdown, smart quotes, and runs of whitespace flattened."""
    for curly, straight in _QUOTES.items():
        text = text.replace(curly, straight)
    text = _EMPHASIS_RE.sub("", _LINK_RE.sub(r"\1", text))
    return re.sub(r"\s+", " ", text).strip().lower()


def pdf_text(path: Path) -> str | None:
    """The PDF's text as `pdftotext` reads it, or None when pdftotext is not installed."""
    if shutil.which("pdftotext") is None:
        return None
    done = subprocess.run(["pdftotext", "-raw", str(path), "-"], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


def extracted_text(path: Path) -> str | None:
    if path.suffix == ".pdf":
        return pdf_text(path)
    return extract_docx_text(path)


def check_text(name: str, resume_md: str, text: str) -> list[Finding]:
    """Every way `text`, extracted from export `name`, loses what `resume_md` says."""
    flat = normalize(_LINE_END_HYPHEN_RE.sub("-", text))
    if not flat:
        return [Finding(name, "no-text", "no text could be extracted; is it an image-only file?")]
    findings: list[Finding] = []
    lines = text.splitlines()
    header = "\n".join(resume_md.splitlines()[:_HEADER_LINES])
    for contact in _EMAIL_RE.findall(header) + _PHONE_RE.findall(header):
        if contact.lower() not in flat:
            findings.append(Finding(name, "contact-missing", contact))
    line_set = {normalize(line) for line in lines}
    for line in resume_md.splitlines():
        if (heading := _HEADING_RE.match(line)) and normalize(heading["text"]) not in line_set:
            findings.append(Finding(name, "heading-missing", heading["text"]))
        if bullet := _BULLET_RE.match(line):
            words = normalize(bullet["text"])
            if words in flat:
                continue
            if words.replace("-", "") in flat.replace("-", ""):
                lost = [w for w in _HYPHENATED_RE.findall(words) if w not in flat]
                detail = f"hyphen lost at a line break: {', '.join(lost)}" if lost else "hyphens differ at a line break"
            else:
                detail = bullet["text"][:60]
            findings.append(Finding(name, "bullet-missing", detail))
        for dates in _DATE_RANGE_RE.findall(line):
            if not any(normalize(dates) in normalize(extracted) for extracted in lines):
                findings.append(Finding(name, "date-split", dates))
    return findings


def check_app_dir(app_dir: Path) -> tuple[list[Finding], list[str]]:
    """Findings for each exported resume beside `resume.md`, plus one status line per export."""
    resume_md = app_dir / "resume.md"
    if not resume_md.exists():
        return [], ["No resume.md to compare against."]
    findings: list[Finding] = []
    status: list[str] = []
    for name in EXPORTS:
        path = app_dir / name
        if not path.exists():
            continue
        text = extracted_text(path)
        if text is None:
            status.append(f"{name}: skipped (pdftotext not installed)")
            continue
        found = check_text(name, resume_md.read_text(), text)
        findings.extend(found)
        status.append(f"{name}: {len(found)} finding(s)" if found else f"{name}: parses clean")
    return findings, status or ["No exported resume.pdf or resume.docx to check."]


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python3 parse_check.py <app_dir>", file=sys.stderr)
        raise SystemExit(2)
    findings, status = check_app_dir(Path(sys.argv[1]))
    for finding in findings:
        print("\t".join(finding))
    for line in status:
        print(line)
    raise SystemExit(1 if findings else 0)


if __name__ == "__main__":
    main()
