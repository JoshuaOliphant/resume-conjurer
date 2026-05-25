# ABOUTME: Extracts plain text from a .docx file using only the standard library.
# ABOUTME: Lets the conjurer ingest a docx resume; PDF is read by Claude directly, md/txt are plain.
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# WordprocessingML namespace for text runs.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx_text(path: Path) -> str:
    """Return the visible text of a .docx, one line per paragraph.

    Reads word/document.xml from the docx zip and concatenates the text runs
    (<w:t>) within each paragraph (<w:p>), with a newline between paragraphs.
    """
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for p in root.iter(f"{_W}p"):
        runs = [node.text for node in p.iter(f"{_W}t") if node.text]
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs).strip() + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python3 extract_text.py <file.docx>", file=sys.stderr)
        raise SystemExit(2)
    print(extract_docx_text(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
