# ABOUTME: Verifies bounded document extraction against real text, DOCX, and PDF artifacts.
# ABOUTME: Checks source order, extraction warnings, and rejection of unreadable inputs.

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from app.document_import import DocumentImportError, import_document


def _docx(body: str, extra: dict[str, bytes] | None = None) -> bytes:
    contents = BytesIO()
    with ZipFile(contents, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>',
        )
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return contents.getvalue()


def _pdf(*pages: str) -> bytes:
    writer = PdfWriter()
    for value in pages:
        page = writer.add_blank_page(width=300, height=300)
        if value:
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 250 Td ({value}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): DictionaryObject(
                    {NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")}
                )})}
            )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("filename", ["resume.md", "resume.TXT"])
def test_utf8_text_preserves_lines_and_numbers(filename: str) -> None:
    result = import_document(filename, b"\xef\xbb\xbf# Casey\n- Grew revenue 42% in 2023\n")
    assert result.text == "# Casey\n- Grew revenue 42% in 2023\n"
    assert result.warnings == ()


def test_docx_preserves_heading_bullets_and_table_reading_order() -> None:
    content = _docx(
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Experience</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="ListBullet"/></w:pPr><w:r><w:t>Built 42 services in 2023</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>Reduced cost 12%</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>2021-2024</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>Acme</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    )
    result = import_document("resume.docx", content)
    assert result.text == "## Experience\n\n- Built 42 services in 2023\n\n- Reduced cost 12%\n\n2021-2024 | Acme"
    assert result.warnings == ("Table text was flattened into reading order.",)


def test_docx_keeps_plain_paragraphs_and_ignores_blank_blocks() -> None:
    result = import_document("resume.docx", _docx(
        '<w:p><w:r><w:t>First</w:t></w:r></w:p><w:p/>'
        '<w:p><w:pPr><w:pStyle w:val="Heading7"/></w:pPr><w:r><w:t>Second</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl><w:sectPr/>'
    ))
    assert result.text == "First\n\nSecond"
    assert result.warnings == ("Table text was flattened into reading order.",)


def test_docx_preserves_tabs_and_line_breaks_within_a_paragraph() -> None:
    result = import_document("resume.docx", _docx(
        '<w:p><w:r><w:t>Staff Engineer</w:t><w:tab/><w:t>2021-2024</w:t>'
        '<w:br/><w:t>Saved 42%</w:t><w:cr/><w:t>casey@example.com</w:t></w:r></w:p>'
    ))
    assert result.text == "Staff Engineer\t2021-2024\nSaved 42%\ncasey@example.com"
    assert result.warnings == ()


@pytest.mark.parametrize("part", ["header1.xml", "footer1.xml"])
def test_docx_reports_unimported_header_or_footer(part: str) -> None:
    result = import_document("resume.docx", _docx(
        '<w:p><w:r><w:t>Experience: Northwind</w:t></w:r></w:p>',
        {f"word/{part}": b'<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:r><w:t>jordan@example.com</w:t></w:r></w:p>'},
    ))
    assert result.text == "Experience: Northwind"
    assert result.warnings == ("Headers and footers were not imported. Check contact details against the original file.",)


def test_docx_reports_unsupported_body_content() -> None:
    result = import_document("resume.docx", _docx(
        '<w:p><w:r><w:t>Visible introduction</w:t></w:r></w:p>'
        '<w:sdt><w:sdtContent><w:p><w:r><w:t>Led 25 engineers</w:t></w:r></w:p></w:sdtContent></w:sdt>'
    ))
    assert result.text == "Visible introduction"
    assert result.warnings == ("Some DOCX content is outside ordinary paragraphs and tables and was not imported. Check the original file.",)


def test_pdf_extracts_pages_in_order_and_reports_image_only_page() -> None:
    content = _pdf("Casey 2023", "", "Saved 42%")
    assert PdfReader(BytesIO(content)).pages[0].extract_text().strip() == "Casey 2023"
    result = import_document("resume.pdf", content)
    assert result.text == "Casey 2023\n\nSaved 42%"
    assert result.warnings == ("Page 2 has no extractable text; OCR was not performed.",)


def test_pdf_reports_images_on_pages_with_extractable_text() -> None:
    reader = PdfReader(BytesIO(_pdf("Visible typed header")))
    writer = PdfWriter()
    page = writer.add_page(reader.pages[0])
    picture = DecodedStreamObject()
    picture.set_data(b"\x00\x00\x00")
    picture.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(1), NameObject("/Height"): NumberObject(1),
                    NameObject("/BitsPerComponent"): NumberObject(8), NameObject("/ColorSpace"): NameObject("/DeviceRGB")})
    resources = page["/Resources"]
    assert isinstance(resources, DictionaryObject)
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Picture"): writer._add_object(picture)})
    contents = BytesIO()
    writer.write(contents)
    result = import_document("resume.pdf", contents.getvalue())
    assert result.text == "Visible typed header"
    assert result.warnings == ("Page 1 contains images whose text was not imported; OCR was not performed.",)


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("resume.rtf", b"text", "Unsupported document type"),
        ("resume.txt", b"\xff", "must be UTF-8"),
        ("resume.md", b" \n", "no readable text"),
        ("resume.docx", b"broken", "corrupt or encrypted"),
        ("resume.pdf", b"broken", "corrupt or unreadable"),
        ("resume.pdf", _pdf(""), "no readable text"),
    ],
    ids=["unsupported", "invalid-utf8", "empty-text", "corrupt-docx", "corrupt-pdf", "image-only-pdf"],
)
def test_rejects_unreadable_inputs(filename: str, content: bytes, message: str) -> None:
    with pytest.raises(DocumentImportError, match=message):
        import_document(filename, content)


def test_rejects_oversized_input() -> None:
    with pytest.raises(DocumentImportError, match="10 MiB"):
        import_document("resume.md", b"a" * (10 * 1024 * 1024 + 1))


def test_rejects_docx_without_body_or_valid_xml() -> None:
    missing = BytesIO()
    with ZipFile(missing, "w") as archive:
        archive.writestr("other.xml", "text")
    with pytest.raises(DocumentImportError, match="no readable document body"):
        import_document("resume.docx", missing.getvalue())
    for body, message in [
        (b"<broken", "document body is corrupt"),
        (b"<root/>", "no readable document body"),
        (b"<!DOCTYPE root><root/>", "unsupported XML declarations"),
    ]:
        content = BytesIO()
        with ZipFile(content, "w") as archive:
            archive.writestr("word/document.xml", body)
        with pytest.raises(DocumentImportError, match=message):
            import_document("resume.docx", content.getvalue())


def test_rejects_docx_expansion_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.document_import as importer

    monkeypatch.setattr(importer, "MAX_EXPANDED_BYTES", 20)
    with pytest.raises(DocumentImportError, match="expands beyond"):
        import_document("resume.docx", _docx("<w:p/>", {"padding": b"z" * 21}))
    monkeypatch.setattr(importer, "MAX_EXPANDED_BYTES", 1000)
    monkeypatch.setattr(importer, "MAX_XML_BYTES", 10)
    with pytest.raises(DocumentImportError, match="body is too large"):
        import_document("resume.docx", _docx("<w:p/>"))


def test_rejects_password_encrypted_pdf() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    with pytest.raises(DocumentImportError, match="Password-encrypted"):
        import_document("resume.pdf", output.getvalue())
