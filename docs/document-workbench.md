# Source document workbench

With an explicitly configured live workspace, open **Import or edit your source documents** on the start page, or visit `/documents`. The editor reads and writes `master-resume.md` and `grimoire.md` in that workspace. It never defaults to bundled fixtures.

Upload Markdown/plain UTF-8 text, DOCX, or a text-based PDF to review extracted content. Uploading retains the original bytes without changing the current source. Review and correct the preview, then choose Save. The imported layout is not reproduced. DOCX tables, omitted headers/footers or unsupported blocks, and PDF pages with images or without text carry review warnings; image-only PDFs require a text-based file or pasted text. OCR is not performed.

The editor saves text, not a generated or fact-verified resume. After a master résumé import, the preview checks the extracted text against the actual composer and reports usable role/bullet slots. Readable text with zero slots still needs work. **Prepare master resume** shows a separate, editable draft with line-linked formatting changes and missing or ambiguous structure to correct. The draft keeps existing factual text and optional sections in order; it never fills in an employer, date, accomplishment, or metric. Review it against the retained original file, then choose **Accept and save master résumé**. A DOCX table or other import warning requires an explicit reading-order review before acceptance. The composer and outline generator use only the saved `master-resume.md`; there is no additional normalized resume store.

Saves use content revisions to reject stale tabs, including normalized-draft acceptance. Previous content is stored under `.document-history/<document-name>/<content-hash>.md`; original upload bytes are retained under `.document-originals/<content-hash>/<original-filename>`. The extracted text remains visible in the import and normalization previews, and the original can be imported again to recover extraction. These are local workspace files, not new stores for variant picks. Saving the same content is a no-op. On conflict, copy unsaved text before reloading and comparing the current source.

Source saves and generation starts share a process-local lock; edits are refused while generation is running. Changing sources does not silently regenerate existing applications. Review existing application claims against updated evidence before using them. Existing claim/source fingerprints omit stale support judgments when their checked content differs.

This is a local, single-workspace tool. The save lock coordinates threads within one store instance; use one server process. Multi-process and external-writer coordination, per-user identity, source isolation, templates, and guided grimoire onboarding are subsequent work. Final-document editing is described in `final-documents.md`. Do not expose this server as a multi-user service.

Uploaded files are limited to 10 MiB; the total upload request is capped at 10 MiB plus 64 KiB of multipart overhead before parsing. Editable source text is limited to 2 MiB. Extraction errors, invalid names, oversized data, and stale revisions preserve the current source. Source-writing forms reject cross-origin browser requests.

Runtime:

```sh
cd web
CONJURER_BACKEND=live CONJURER_WORKSPACE=/absolute/path/to/workspace uv run uvicorn app.main:app --host 127.0.0.1 --port 8411
```

No API call is needed to import or edit documents. Generating an application uses the separately configured generation and verification adapters.
