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

## Claim check (steps 4b and 6b)

After assembling `variants.md`, check every variant against the evidence it cites:

```bash
python3 <SKILL_DIR>/scripts/verify.py <app_dir> <workspace>
python3 <SKILL_DIR>/scripts/verify.py <app_dir> <workspace> --picks   # after stitch
```

It needs `TYPESAFE_API_KEY`. Without it, it prints `Claim check skipped: set TYPESAFE_API_KEY to
check variants against your evidence.`, writes nothing, and exits 0. The plugin itself still needs
no key.

For each variant, Jev (`jev-1.13.0`, pinned because the thresholds were tuned on it) answers two
questions: how the variant's grounded cited lines relate to it (asked only when it has one), and
whether it states a fact that the whole evidence pool (every line of `master-resume.md` and
`evidence.md`) does not. The script writes `<app_dir>/support.json` and prints one line per
flagged variant, `<unit_id>#<n>: <note>`. Mention those notes while curating. A flag is a note,
never a reason to hide, reorder, or regenerate a variant, and an unflagged variant is not
"verified true": the check only tests consistency with the user's own evidence.

`--picks` checks only the picked variants and keeps the other rows already in `support.json`.
`stitch.py` never reads `support.json`, so the check cannot change a stitched document.

### support.json

```json
{
  "model": "jev-1.13.0",
  "variants": {
    "resume.northwind.billing.bullet_1#3": {
      "verdict": "adds_detail",
      "relation": "partly_supports",
      "relation_confidence": 1.0,
      "unstated": 0.94,
      "unsourced_numbers": ["12"],
      "fingerprint": "<sha256 hex>"
    }
  }
}
```

- Keys are variant ids, `<unit_id>#<n>`, where `n` is the number in `### Variant N`.
- `relation` is `supports`, `partly_supports`, `contradicts`, or `says_nothing`, with its
  `relation_confidence`; both are `null` when the variant has no grounded cited line or the check
  failed. `unstated` is the probability that the variant states a fact the pool does not; `null`
  when the check failed.
- `unsourced_numbers` lists numbers (digits or number words) in the variant that its cited lines
  never state. It only names a value in the note; it never decides the verdict.
- `fingerprint` is the sha256 hex digest of the UTF-8 text of the variant followed by each
  resolved cited line, joined by `\n`. **A row whose fingerprint no longer matches the variant is
  ignored**, so a hand-edited variant reads as "no verdict", never as a stale one.
  Web saves preserve the checker's fingerprint. Verdicts without a fingerprint use the checked
  units and evidence snapshot; saving never substitutes evidence edited after the check.

The web review row is "Claim check of picked lines". It names flagged picks, unresolved
citations, failed checks, and picks without a current verdict. A passing row means no picked
line was flagged, not that every claim was proven. Support-file read and write failures are
logged and leave generation and curation available without verdicts.

### Verdicts

| verdict | when | note |
|---|---|---|
| `traced` | none of the below | none |
| `untraced` | no grounded cited line, `unstated` < 0.5 | none (the citation already reads as unverified) |
| `adds_detail` | `partly_supports` at confidence ≥ 0.8, or `unstated` ≥ 0.5 | "Adds detail your evidence doesn't state", plus `: <numbers>` |
| `conflicts` | `contradicts`, at any confidence | "Conflicts with your evidence", plus `: <numbers>` |
| `wrong_trace` | `says_nothing` and `unstated` < 0.5: the pool has the fact | "Your evidence supports this, but not the line it cites" |
| `not_covered` | `says_nothing` and `unstated` ≥ 0.5 | "The cited line doesn't cover this" |
| `unchecked` | a Jev request timed out (5 s) or failed | "Couldn't check this line" |

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
