---
name: conjurer
description: This skill should be used when the user asks to "tailor my resume for this job", "conjure variants for this role", "generate resume/cover letter variants", "write a cover letter the conjurer way", "generate abundance and let me pick", or "run the conjurer pipeline". Generates grounded resume and cover letter variants from a master resume and a grimoire of encoded taste, curates them conversationally, and stitches final documents.
version: 0.1.0
---

# Conjurer

Generate many grounded variants of resume bullets and cover letter paragraphs, curate the best
with the user, and stitch them into final documents. Every claim is grounded in the user's master
resume or evidence; the grimoire encodes voice and taste. Generate abundance, exercise taste,
stitch from selections.

Scripts live in `scripts/` (run with bare `python3`, no dependencies). Detailed procedure is in
`references/pipeline.md`. Generation uses the `variant-generator` subagent.

## Workspace: default to the current directory

A workspace is a directory containing `grimoire.md`, `master-resume.md`, and `applications/`.
By default the workspace is the directory the user launched Claude Code in (the current working
directory). Resolve it before generating:

- **Workspace already here** — cwd contains `grimoire.md` and `master-resume.md`: use it. Go
  straight to the pipeline.
- **First run** — no `grimoire.md`/`master-resume.md` in cwd: bootstrap one here.
  1. Ask whether the user has an existing resume to start from. Accept a file path or pasted
     text and read it: for a PDF use the Read tool directly; for a `.docx` run
     `python3 <SKILL_DIR>/scripts/extract_text.py <file.docx>`; for markdown or plain text read
     it directly.
  2. Run `python3 <SKILL_DIR>/scripts/new_workspace.py .` to scaffold any MISSING workspace files
     (`grimoire.md`, `master-resume.md`, `applications/`) into the current directory. It does not
     clobber files that already exist, so running it in a directory that already holds the user's
     resume is safe.
  3. Build the master resume: ingest the user's existing resume into `master-resume.md` (the
     `/conjurer:master-resume` flow). If they have no resume, interview them.
  4. Build the grimoire: run the `/conjurer:grimoire` flow (interview, optionally ingesting the
     same resume and any writing samples).
- **Override** — if the user keeps their grimoire or master resume elsewhere (for example files
  they already maintain in another repo or vault), accept explicit paths and pass those to the
  steps below instead of the cwd copies.

`<SKILL_DIR>` is this skill's directory. Do not generate against unedited templates — confirm
`grimoire.md` and `master-resume.md` carry the user's real content first.

## Pipeline

1. **Ensure workspace** (above). Confirm `grimoire.md` and `master-resume.md` are filled in, not
   templates.
2. **Init the application**: `python3 <SKILL_DIR>/scripts/init_app.py <slug> <workspace>`. Ask the
   user for the job description (paste into `applications/<slug>/jd.txt`) and any extra evidence
   (`evidence.md`).
3. **Outline**: read the grimoire, master resume, JD, and evidence. Choose one strategic frame and
   design the unit skeleton. Write `applications/<slug>/outline.json`. See `references/pipeline.md`
   for the exact schema and the four frames.
4. **Variants**: for each unit in the outline, dispatch the `variant-generator` subagent in
   parallel, passing the grimoire, master resume, evidence, outline, and that unit. Assemble the
   returned blocks into `applications/<slug>/variants.md`. See `references/pipeline.md` for the
   file format.
5. **Curate**: present the variants conversationally. When the user picks, mark exactly one
   `- [x] Pick` per unit in `variants.md`.
6. **Stitch**: `python3 <SKILL_DIR>/scripts/stitch.py applications/<slug> <workspace>/master-resume.md`.
   Writes `cover_letter.md` and `resume.md`.
7. **Lint**: `python3 <SKILL_DIR>/scripts/lint.py applications/<slug>`. Report findings; fix any
   and re-run until clean.
8. **Export (optional)**: offer to export the finished documents for submission with
   `python3 <SKILL_DIR>/scripts/export_docs.py applications/<slug> pdf docx`. This uses `pandoc`
   if it is installed; if not, it reports that the markdown sources are the deliverable. Tell the
   user which outputs were written or skipped.

## Claim discipline

Never invent claims, numbers, technologies, or outcomes. Every variant re-frames a fact that
exists in the master resume or evidence, and cites its source. If the user asks for a claim that
is not in the evidence, say it is unsupported rather than fabricating it.

## Additional Resources

- **`references/pipeline.md`** — outline schema, strategic frames, variants.md format, exact commands.
- **`scripts/`** — `new_workspace.py`, `init_app.py`, `stitch.py`, `lint.py`, `extract_text.py`
  (docx ingest), `export_docs.py` (PDF/docx export).
- **`agents/variant-generator.md`** (plugin agent) — the per-unit generator.
- Workspace setup: the `/conjurer:grimoire` and `/conjurer:master-resume` commands.
