# Professional export

The live web app exports the saved final `cover_letter.md` and `resume.md` from an application
workspace. It renders DOCX and PDF independently, validates text readback, and replaces each
published file only after its temporary artifact passes validation. `FinalDocuments` records the
source revision and written artifact hashes; the download route rejects stale or edited files.
Markdown remains the editable source and is available even when another format fails. The plugin
CLI retains its optional Pandoc exporter.

Professional uses a single reading column with contact details in the body, section headings,
ordinary bullets, and flowing pages. It supports CommonMark headings, paragraphs, soft and hard
line breaks, bold, italic, link text, and nested bullet and ordered lists. Raw HTML, images,
fences, tables, and other unsupported Markdown are rejected with a per-format status rather than
silently dropped. Link labels and emphasis survive; PDF underlines link text but does not create
clickable links. The 2 MiB source and 20 MiB rendered-file limits bound export work.

PDF uses bundled Noto Sans Regular/Bold/Italic/Bold Italic and Noto Sans JP variable fonts. Readback and a rendered
multi-page sample verify accented Latin, Greek, euro signs, and Japanese CJK characters, including
`José`, `€42M`, `Αθήνα`, and `東京`. A font glyph preflight rejects unsupported characters. Right-to-left
text is rejected for PDF because the native renderer cannot guarantee correct shaping or reading
order. DOCX preserves those characters as editable Unicode text, but its font binaries are not
embedded; Word may substitute installed fonts when reading it on another computer. Neither
format claims universal script or exact cross-reader typography support.

Font assets in `app/assets/fonts/` are licensed under the accompanying SIL Open Font License
files. Noto Sans Regular/Bold came from the [Noto font distribution](https://github.com/notofonts/notofonts.github.io/tree/main/fonts/NotoSans/hinted/ttf),
with its [OFL license](https://github.com/google/fonts/blob/main/ofl/notosans/OFL.txt).
Noto Sans JP VF came from the [Noto CJK 2.004 release](https://github.com/notofonts/noto-cjk/tree/Sans2.004/Sans/Variable/TTF/Subset),
with its [OFL license](https://github.com/notofonts/noto-cjk/blob/Sans2.004/LICENSE).
The web lockfile pins `python-docx`, `reportlab`, and `markdown-it-py`; runtime export does not
invoke Pandoc, LibreOffice, a browser, or a host-installed font.

Run `uv sync --locked` from `web/`, then `uv run pytest -q` for the artifact and route gates.
