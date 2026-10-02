# ABOUTME: Extracts bounded, readable resume text from Markdown, text, DOCX, and PDF files.
# ABOUTME: Reports extraction gaps while preserving the source's paragraph and page order.

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf.errors import PyPdfError

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_XML_BYTES = 20 * 1024 * 1024
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentImportError(ValueError):
    pass


@dataclass(frozen=True)
class ImportedDocument:
    text: str
    warnings: tuple[str, ...]


def _read_docx(content: bytes) -> ImportedDocument:
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
                raise DocumentImportError("DOCX expands beyond the allowed size")
            try:
                document = archive.getinfo("word/document.xml")
            except KeyError as exc:
                raise DocumentImportError("DOCX has no readable document body") from exc
            if document.file_size > MAX_XML_BYTES:
                raise DocumentImportError("DOCX document body is too large")
            xml = archive.read(document)
    except (BadZipFile, RuntimeError, EOFError, OSError) as exc:
        raise DocumentImportError("DOCX is corrupt or encrypted") from exc

    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise DocumentImportError("DOCX contains unsupported XML declarations")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentImportError("DOCX document body is corrupt") from exc
    body = root.find(f"{WORD_NS}body")
    if body is None:
        raise DocumentImportError("DOCX has no readable document body")

    lines: list[str] = []
    warnings: list[str] = []
    if any(entry.filename.startswith(("word/header", "word/footer")) and entry.filename.endswith(".xml") for entry in entries):
        warnings.append("Headers and footers were not imported. Check contact details against the original file.")

    def paragraph_text(paragraph: ElementTree.Element) -> str:
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_NS}t":
                parts.append(node.text or "")
            elif node.tag == f"{WORD_NS}tab":
                parts.append("\t")
            elif node.tag in {f"{WORD_NS}br", f"{WORD_NS}cr"}:
                parts.append("\n")
        return "".join(parts).strip()

    def paragraph_markup(paragraph: ElementTree.Element) -> str:
        parts: list[str] = []
        bold_open = False
        for run in paragraph.iter(f"{WORD_NS}r"):
            properties = run.find(f"{WORD_NS}rPr")
            marker = properties.find(f"{WORD_NS}b") if properties is not None else None
            bold = marker is not None and marker.get(f"{WORD_NS}val", "true").lower() not in {"0", "false", "off"}
            run_parts: list[str] = []
            for node in run.iter():
                if node.tag == f"{WORD_NS}t":
                    run_parts.append(node.text or "")
                elif node.tag == f"{WORD_NS}tab":
                    run_parts.append("\t")
                elif node.tag in {f"{WORD_NS}br", f"{WORD_NS}cr"}:
                    run_parts.append("\n")
            value = "".join(run_parts)
            if not value:
                continue
            if bold != bold_open:
                parts.append("**")
                bold_open = bold
            parts.append(value)
        if bold_open:
            parts.append("**")
        return "".join(parts).strip()

    def formatted_paragraph(paragraph: ElementTree.Element) -> str:
        value = paragraph_text(paragraph)
        if not value:
            return ""
        properties = paragraph.find(f"{WORD_NS}pPr")
        if properties is None:
            return paragraph_markup(paragraph)
        style = properties.find(f"{WORD_NS}pStyle")
        style_name = style.get(f"{WORD_NS}val", "") if style is not None else ""
        if style_name.startswith("Heading") and style_name[7:].isdigit():
            level = int(style_name[7:])
            if 1 <= level <= 6:
                return f"{'#' * level} {value}"
        if style_name.startswith("List") or properties.find(f"{WORD_NS}numPr") is not None:
            return f"- {value}"
        return paragraph_markup(paragraph)

    for block in body:
        if block.tag == f"{WORD_NS}p":
            value = formatted_paragraph(block)
            if value:
                lines.append(value)
        elif block.tag == f"{WORD_NS}tbl":
            warnings.append("Table text was flattened into reading order.")
            for row in block.findall(f"{WORD_NS}tr"):
                cells = []
                for cell in row.findall(f"{WORD_NS}tc"):
                    cells.append(" ".join(filter(None, (paragraph_text(p) for p in cell.iter(f"{WORD_NS}p")))))
                if any(cells):
                    lines.append(" | ".join(cells))
        elif block.tag != f"{WORD_NS}sectPr":
            warnings.append("Some DOCX content is outside ordinary paragraphs and tables and was not imported. Check the original file.")
    return ImportedDocument("\n\n".join(lines), tuple(dict.fromkeys(warnings)))


def _read_pdf(content: bytes) -> ImportedDocument:
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise DocumentImportError("Password-encrypted PDFs are unsupported")
        pages = list(reader.pages)
        extracted = [page.extract_text() or "" for page in pages]
        image_pages = [bool(page.images) for page in pages]
    except DocumentImportError:
        raise
    except (PyPdfError, ValueError, OSError, UnicodeError) as exc:
        raise DocumentImportError("PDF is corrupt or unreadable") from exc
    warnings = ["PDF reading order may differ from the visible layout. Check and correct it against the original file."]
    for number, (text, has_images) in enumerate(zip(extracted, image_pages, strict=True), start=1):
        if not text.strip():
            warnings.append(f"Page {number} has no extractable text; OCR was not performed.")
        elif has_images:
            warnings.append(f"Page {number} contains images whose text was not imported; OCR was not performed.")
    return ImportedDocument("\n\n".join(page.strip() for page in extracted if page.strip()), tuple(warnings))


def import_document(filename: str, content: bytes) -> ImportedDocument:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentImportError("Document exceeds the 10 MiB size limit")
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".txt"}:
        try:
            result = ImportedDocument(content.decode("utf-8-sig"), ())
        except UnicodeDecodeError as exc:
            raise DocumentImportError("Text document must be UTF-8") from exc
    elif suffix == ".docx":
        result = _read_docx(content)
    elif suffix == ".pdf":
        result = _read_pdf(content)
    else:
        raise DocumentImportError("Unsupported document type")
    if not result.text.strip():
        raise DocumentImportError("Document has no readable text")
    return result
