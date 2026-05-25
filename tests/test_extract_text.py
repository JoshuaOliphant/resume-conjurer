# ABOUTME: Tests docx text extraction using a hand-built minimal .docx zip.
# ABOUTME: Verifies paragraphs split by newline and runs within a paragraph concatenate.
import zipfile
import extract_text

_DOC = (
    '<?xml version="1.0"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>"
    "<w:p><w:r><w:t>Jane Doe</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Senior </w:t></w:r><w:r><w:t>Engineer</w:t></w:r></w:p>"
    "</w:body></w:document>"
)


def test_extract_docx_text(tmp_path):
    docx = tmp_path / "resume.docx"
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", _DOC)
    text = extract_text.extract_docx_text(docx)
    assert text.splitlines() == ["Jane Doe", "Senior Engineer"]
