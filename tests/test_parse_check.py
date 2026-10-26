# ABOUTME: Tests the parse round-trip check against synthetic resume.md files and extracted text.
# ABOUTME: PDF extraction is stubbed so the suite runs without pdftotext; docx uses a hand-built zip.
import subprocess
import sys
import zipfile
from types import SimpleNamespace

import pytest

import parse_check

RESUME_MD = """# Jane Doe

555.123.4567 | jane@example.com | github.com/jane

## Experience

### Acme — Remote

**Engineer** — January 2022 – April 2024
- Built a fault-tolerant queue for the **billing** service's [API](https://x.test).
- Ran service-, namespace-, and cluster-level drills.

## Skills

- Python, Kafka
"""

CLEAN_TEXT = """Jane Doe
555.123.4567 | jane@example.com | github.com/jane
Experience
Acme — Remote
Engineer — January 2022 – April 2024
• Built a fault-tolerant queue for the billing service’s API.
• Ran service-, namespace-, and cluster-level drills.
Skills
• Python, Kafka
"""


def _docx(path, lines):
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines)
    xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


def _kinds(findings):
    return [(f.kind, f.detail) for f in findings]


def test_normalize_flattens_markdown_quotes_and_space():
    assert parse_check.normalize("**Ran** the  [API](https://x.test)’s `job`\n") == "ran the api's job"


def test_clean_text_has_no_findings():
    assert parse_check.check_text("resume.pdf", RESUME_MD, CLEAN_TEXT) == []


def test_empty_extraction_is_no_text():
    assert _kinds(parse_check.check_text("resume.pdf", RESUME_MD, " \n")) == [
        ("no-text", "no text could be extracted; is it an image-only file?")
    ]


def test_missing_contact_and_heading():
    text = CLEAN_TEXT.replace("jane@example.com", "").replace("\nSkills\n", "\nSkills: \n")
    assert _kinds(parse_check.check_text("resume.pdf", RESUME_MD, text)) == [
        ("contact-missing", "jane@example.com"),
        ("heading-missing", "Skills"),
    ]


def test_bullet_missing_names_the_lost_hyphen_or_the_bullet():
    text = (
        CLEAN_TEXT.replace("fault-tolerant", "faulttolerant")
        .replace("service-, namespace-,", "service, namespace,")
        .replace("Python, Kafka", "Python")
    )
    assert _kinds(parse_check.check_text("resume.pdf", RESUME_MD, text)) == [
        ("bullet-missing", "hyphen lost at a line break: fault-tolerant"),
        ("bullet-missing", "hyphen lost at a line break: ran service-, namespace-, and cluster-level drills."),
        ("bullet-missing", "Python, Kafka"),
    ]


def test_date_range_split_across_lines():
    text = CLEAN_TEXT.replace("January 2022 – April 2024", "January 2022 –\nApril 2024")
    assert _kinds(parse_check.check_text("resume.pdf", RESUME_MD, text)) == [
        ("date-split", "January 2022 – April 2024")
    ]


def test_pdf_text_without_pdftotext(monkeypatch, tmp_path):
    monkeypatch.setattr(parse_check.shutil, "which", lambda _: None)
    assert parse_check.pdf_text(tmp_path / "resume.pdf") is None


@pytest.mark.parametrize(("returncode", "expected"), [(0, "text\n"), (1, "")])
def test_pdf_text_runs_pdftotext(monkeypatch, tmp_path, returncode, expected):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=returncode, stdout="text\n")

    monkeypatch.setattr(parse_check.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(subprocess, "run", run)
    pdf = tmp_path / "resume.pdf"
    assert parse_check.pdf_text(pdf) == expected
    assert calls == [["pdftotext", str(pdf), "-"]]


def test_check_app_dir_without_resume_md(tmp_path):
    assert parse_check.check_app_dir(tmp_path) == ([], ["No resume.md to compare against."])


def test_check_app_dir_without_exports(tmp_path):
    (tmp_path / "resume.md").write_text(RESUME_MD)
    assert parse_check.check_app_dir(tmp_path) == ([], ["No exported resume.pdf or resume.docx to check."])


def test_check_app_dir_reports_each_export(monkeypatch, tmp_path):
    (tmp_path / "resume.md").write_text(RESUME_MD)
    (tmp_path / "resume.pdf").write_bytes(b"%PDF")
    _docx(tmp_path / "resume.docx", CLEAN_TEXT.splitlines())
    monkeypatch.setattr(parse_check, "pdf_text", lambda _: CLEAN_TEXT.replace("April 2024", "\nApril 2024"))
    findings, status = parse_check.check_app_dir(tmp_path)
    assert _kinds(findings) == [("date-split", "January 2022 – April 2024")]
    assert status == ["resume.pdf: 1 finding(s)", "resume.docx: parses clean"]


def test_check_app_dir_skips_pdf_without_extractor(monkeypatch, tmp_path):
    (tmp_path / "resume.md").write_text(RESUME_MD)
    (tmp_path / "resume.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(parse_check, "pdf_text", lambda _: None)
    assert parse_check.check_app_dir(tmp_path) == ([], ["resume.pdf: skipped (pdftotext not installed)"])


def test_main_usage_findings_and_clean(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["parse_check.py"])
    with pytest.raises(SystemExit, match="2"):
        parse_check.main()
    assert "usage: python3 parse_check.py" in capsys.readouterr().err

    (tmp_path / "resume.md").write_text(RESUME_MD)
    _docx(tmp_path / "resume.docx", CLEAN_TEXT.replace("jane@example.com", "").splitlines())
    monkeypatch.setattr(sys, "argv", ["parse_check.py", str(tmp_path)])
    with pytest.raises(SystemExit, match="1"):
        parse_check.main()
    assert capsys.readouterr().out == (
        "resume.docx\tcontact-missing\tjane@example.com\nresume.docx: 1 finding(s)\n"
    )

    _docx(tmp_path / "resume.docx", CLEAN_TEXT.splitlines())
    with pytest.raises(SystemExit, match="0"):
        parse_check.main()
    assert capsys.readouterr().out == "resume.docx: parses clean\n"
