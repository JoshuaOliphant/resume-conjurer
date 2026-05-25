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
lint -> export. Output lands in `applications/<slug>/`.

## Example walkthrough

Start in a folder that holds your current resume and launch Claude Code there:

```
~/job-search $ ls
resume.pdf
~/job-search $ claude
```

Then describe the job:

> **You:** Help me apply to the Staff Platform Engineer role at Globex. [paste the JD]

On the first run there is no workspace yet, so the skill bootstraps one from what you already have:

> **Conjurer:** I don't see a conjurer workspace here, but I found `resume.pdf`. I'll read it to
> build your `master-resume.md` (the evidence pool) and interview you briefly to capture your voice
> in `grimoire.md`. Ready?

After setup, the pipeline runs:

1. **Outline.** It reads the JD against your master resume and picks one strategic frame (scale,
   friction, conviction, or multiplier), then lists the cover letter paragraphs and the resume
   bullets worth tailoring.
2. **Variants.** It generates four grounded variants per unit in parallel, each citing the evidence
   it draws from, and writes them to `applications/globex-staff-platform/variants.md`.
3. **Curate.** It walks you through the units conversationally:

   > **Conjurer:** For your opening bullet, which lands better?
   > 1. *Architected the billing-platform migration to event-driven services, cutting invoice
   >    latency from 40s to under 2s across three regions.*
   > 2. *Led the platform migration that moved billing onto an event-driven backbone, taking
   >    invoice generation from 40 seconds to two and clearing the path for regional rollout.*
   >
   > **You:** 1

4. **Stitch.** It assembles your picks into `cover_letter.md` and `resume.md`.
5. **Lint.** It runs the grimoire checklist (no em dashes in prose, no filler, no AI-generic
   openers, cover letter under 350 words) and fixes anything it flags.
6. **Export.** It offers PDF and docx for submission (via `pandoc` if installed).

```
~/job-search $ ls applications/globex-staff-platform
cover_letter.md   cover_letter.pdf   resume.md   resume.pdf
jd.txt            evidence.md        outline.json  variants.md
```

Every claim in those documents traces back to a line in your master resume or evidence. The model
re-frames; it does not invent.

## How it works

Deterministic work (scaffolding, stitching, linting) is pure-stdlib Python in
`plugins/conjurer/skills/conjurer/scripts/`. Generation is a skill procedure plus a parallel
`variant-generator` subagent. No API keys: inside Claude Code, Claude is the model.

## License

MIT
