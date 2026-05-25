# ABOUTME: Regex-based grimoire style linter for cover_letter.md and resume.md.
# ABOUTME: Covers the pure-regex/counting checks from the grimoire's 10-point checklist.

import re
from dataclasses import dataclass
from pathlib import Path

EM_DASH_RE = re.compile(r"—")

CORRELATIVE_RES = [
    re.compile(r"\bnot just\b.*?,?\s*it'?s\b", re.IGNORECASE),
    re.compile(r"\bnot only\b.*?,?\s*but also\b", re.IGNORECASE),
    re.compile(r"\bnot just\b.*?,?\s*but\b", re.IGNORECASE),
    re.compile(r"\bmore than just\b", re.IGNORECASE),
]

FILLER_WORDS = ["just", "actually", "a bit", "really", "basically", "pretty much", "kind of", "sort of"]

AI_GENERIC_OPENERS = [
    re.compile(r"^\s*In (today'?s|the) (fast-moving|fast-paced|rapidly-evolving|ever-changing)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Let'?s (dive into|explore|take a look at)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*I am writing to (express|apply|inquire)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*I would be (honored|thrilled|delighted|excited)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Please find (my resume|attached)", re.IGNORECASE | re.MULTILINE),
]

SELF_DEPRECATION_RES = [
    re.compile(r"\bsmall (thing|tool|project)\b", re.IGNORECASE),
    re.compile(r"\bnothing fancy\b", re.IGNORECASE),
    re.compile(r"\bI'?m sure there are better ways\b", re.IGNORECASE),
]

DISCLAIMER_RES = [
    re.compile(r"\bI could be wrong, but\b", re.IGNORECASE),
    re.compile(r"\bjust my opinion\b", re.IGNORECASE),
    re.compile(r"\bin my humble opinion\b", re.IGNORECASE),
]

WE_LETS_RE = re.compile(r"\b(we|we'?ll|we'?ve|we are|let'?s)\b", re.IGNORECASE)

BUZZWORDS = [
    "synergy",
    "rockstar",
    "ninja",
    "guru",
    "results-oriented",
    "detail-oriented",
    "self-starter",
    "hard worker",
    "excellent communication skills",
    "passionate about",
]

COVER_LETTER_WORD_LIMIT = 350


@dataclass
class Finding:
    file: Path
    line: int
    rule: str
    snippet: str


def lint_text(text: str, source: Path, is_cover_letter: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        if EM_DASH_RE.search(line):
            findings.append(Finding(source, i, "em_dash", line.strip()))

        for pat in CORRELATIVE_RES:
            if pat.search(line):
                findings.append(Finding(source, i, "correlative_construction", line.strip()))
                break

        for word in FILLER_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", line, re.IGNORECASE):
                findings.append(Finding(source, i, f"filler:{word}", line.strip()))

        if WE_LETS_RE.search(line) and not line.lstrip().startswith(("#", ">", "*")):
            findings.append(Finding(source, i, "first_person_plural", line.strip()))

        for pat in SELF_DEPRECATION_RES:
            if pat.search(line):
                findings.append(Finding(source, i, "self_deprecation", line.strip()))
                break

        for pat in DISCLAIMER_RES:
            if pat.search(line):
                findings.append(Finding(source, i, "disclaimer_hedge", line.strip()))
                break

        for word in BUZZWORDS:
            if re.search(rf"\b{re.escape(word)}\b", line, re.IGNORECASE):
                findings.append(Finding(source, i, f"buzzword:{word}", line.strip()))

    for pat in AI_GENERIC_OPENERS:
        m = pat.search(text)
        if m:
            snippet = m.group(0).strip()
            line_no = text.count("\n", 0, m.start() + len(m.group(0)) - len(snippet)) + 1
            findings.append(Finding(source, line_no, "ai_generic_opener", snippet[:120]))
            break

    if is_cover_letter:
        word_count = len(re.findall(r"\b\w+\b", text))
        if word_count > COVER_LETTER_WORD_LIMIT:
            findings.append(
                Finding(source, 0, "length", f"cover letter is {word_count} words (limit {COVER_LETTER_WORD_LIMIT})")
            )

    return findings


def lint_app_dir(app_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    cover = app_dir / "cover_letter.md"
    resume = app_dir / "resume.md"
    if cover.exists():
        findings.extend(lint_text(cover.read_text(), cover, is_cover_letter=True))
    if resume.exists():
        findings.extend(lint_text(resume.read_text(), resume, is_cover_letter=False))
    return findings


def main() -> None:
    import sys
    if len(sys.argv) != 2:
        print("usage: python3 lint.py <app_dir>", file=sys.stderr)
        raise SystemExit(2)
    findings = lint_app_dir(Path(sys.argv[1]))
    if not findings:
        print("No style issues found.")
        return
    for f in findings:
        print(f"{f.file.name}:{f.line}\t{f.rule}\t{f.snippet[:80]}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
