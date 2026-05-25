# resume-conjurer

A Claude Code plugin that generates grounded resume and cover letter variants, lets you curate
them, and stitches final documents. Generate abundance, exercise taste, stitch from selections.

Inspired by Scott Werner's [The Illusionist and the Conjurer](https://worksonmymachine.ai/p/the-illusionist-and-the-conjurer):
instead of asking for one perfect output, summon many grounded variants and recognize the right one.

## What it does

- **Grounded variants.** Every bullet and paragraph traces back to your master resume or evidence.
  The model re-frames; it does not invent.
- **Encoded taste.** A `grimoire.md` captures your voice and rules so output sounds like you.
- **Conversational curation.** Claude presents variants; you pick; it stitches the winners.
- **Style linting.** A checklist catches em dashes, filler, AI-generic openers, and overlong cover letters.
- **Reads and writes real formats.** Bootstraps from your existing resume in PDF, docx, or markdown, and exports the finished cover letter and resume to PDF/docx (via `pandoc` if installed; otherwise markdown is the deliverable).

## Install

```
/plugin marketplace add joshuaoliphant/resume-conjurer
/plugin install conjurer@resume-conjurer
```

## Setup

```
/conjurer:grimoire        # build your grimoire (point it at an old resume to bootstrap)
/conjurer:master-resume   # build your master resume (the evidence pool)
```

These create and fill a workspace: a directory with `grimoire.md`, `master-resume.md`, and
`applications/`.

## Use

Ask Claude to tailor your resume for a job ("conjure variants for this role" + paste the JD). The
conjurer skill runs the pipeline: outline -> variants (in parallel) -> curate with you -> stitch ->
lint. Output lands in `applications/<slug>/cover_letter.md` and `resume.md`.

## How it works

Deterministic work (scaffolding, stitching, linting) is pure-stdlib Python in
`plugins/conjurer/skills/conjurer/scripts/`. Generation is a skill procedure plus a parallel
`variant-generator` subagent. No API keys: inside Claude Code, Claude is the model.

## License

MIT
