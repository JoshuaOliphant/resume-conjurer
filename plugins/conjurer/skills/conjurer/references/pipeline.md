# Conjurer Pipeline Detail

## The outline (step 3)

After reading the grimoire, master resume, JD, and evidence, decide the strategy and write
`<app_dir>/outline.json` with this shape:

```json
{
  "strategic_frame": "scale | friction | conviction | multiplier",
  "frame_rationale": "2-3 sentences on why this angle fits this role",
  "company": "Company name",
  "role_title": "Role title",
  "cover_letter_units": [
    {"unit_id": "cover_letter.opening", "description": "what this paragraph must accomplish"},
    {"unit_id": "cover_letter.evidence", "description": "..."},
    {"unit_id": "cover_letter.strategic", "description": "..."},
    {"unit_id": "cover_letter.closing", "description": "optional"}
  ],
  "resume_units": [
    {"unit_id": "resume.<company>.<subrole?>.bullet_1", "description": "experience this bullet surfaces"}
  ]
}
```

Be decisive: one strategic frame, clearly justified. Units in document order — cover letter
first, then resume bullets in the order they appear in the master resume. Only include resume
bullets worth tailoring; leave older roles untouched.

Resume `unit_id`s must encode the role so the stitcher can match them to a sub-role:
`resume.<company>.<optional subrole qualifiers>.bullet_<n>` (for example
`resume.acme.platform.bullet_1`). Token overlap matches the unit to its sub-role.

## Strategic frames

- **scale** — external prestige company: scale, fundamentals, excellence.
- **friction** — internal transfer: name what you cannot do where you are now.
- **conviction** — AI-first startup: name the thesis bet you share.
- **multiplier** — platform/infra company: name the leverage over many engineers.

## Variants (step 4)

For each unit in the outline, dispatch the `variant-generator` subagent (in parallel) with: the
grimoire, master resume, evidence, outline, and that unit. Each returns a `## Unit:` block.
Concatenate a header plus all blocks into `<app_dir>/variants.md`:

```
# Conjurer Variants — <slug>

Strategic frame: `<frame>`

Mark picks by changing `- [ ] Pick` to `- [x] Pick` next to your chosen variant per unit.

<unit blocks here>
```

## Curation (step 5)

Present variants conversationally, one unit at a time or grouped. When the user chooses, edit
`variants.md` so exactly one variant per unit reads `- [x] Pick`. Exactly one pick per unit.

## Stitch, lint, export (steps 6-8)

```bash
python3 <SKILL_DIR>/scripts/stitch.py <app_dir> <workspace>/master-resume.md
python3 <SKILL_DIR>/scripts/lint.py <app_dir>
python3 <SKILL_DIR>/scripts/export_docs.py <app_dir> pdf docx
```

Stitch writes `cover_letter.md` and `resume.md`. Lint prints findings; fix any and re-run. Export
produces PDF/docx via pandoc when installed, otherwise reports that the markdown is the deliverable.

## Ingesting an existing resume (first-run bootstrap)

Read the user's source resume by format: PDF via the Read tool, `.docx` via
`python3 <SKILL_DIR>/scripts/extract_text.py <file.docx>`, markdown or text directly. Map the
content into the structured `master-resume.md` (the `/conjurer:master-resume` flow).
