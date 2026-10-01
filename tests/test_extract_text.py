# ABOUTME: Tests docx text extraction using a hand-built minimal .docx zip.
# ABOUTME: Verifies paragraphs split by newline and runs within a paragraph concatenate.
import zipfile
import sys

import extract_text
import pytest

_DOC = (
    '<?xml version="1.0"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>"
    "<w:p><w:r><w:t>Jane Doe</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Senior </w:t></w:r><w:r><w:t>Engineer</w:t></w:r></w:p>"
    "</w:body></w:document>"
)


@pytest.fixture
def docx_file(tmp_path):
    docx = tmp_path / "resume.docx"
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", _DOC)
    return docx


def test_extract_docx_text(docx_file):
    text = extract_text.extract_docx_text(docx_file)
    assert text.splitlines() == ["Jane Doe", "Senior Engineer"]


def test_extract_cli_reports_usage_and_document(docx_file, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["extract_text.py"])
    with pytest.raises(SystemExit, match="2"):
        extract_text.main()
    assert "usage: python3 extract_text.py" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["extract_text.py", str(docx_file)])
    extract_text.main()
    assert capsys.readouterr().out == "Jane Doe\nSenior Engineer\n\n"
