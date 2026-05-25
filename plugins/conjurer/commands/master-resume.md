---
description: Build or refine the workspace master-resume (the evidence pool) by interview and by ingesting an existing resume.
argument-hint: "[optional path to an existing resume or work-history notes]"
---

# Build the Master Resume

Produce or refine `master-resume.md` in the user's conjurer workspace. This is the evidence pool:
every generated variant must trace back to a claim here. It is the user's full history, broader
than any single tailored resume.

## Structure constraint (required)

The file must parse with the conjurer composer. Keep this structure:

- A `## Experience` H2 section.
- One `### <Company> — <Title>` H3 per company.
- One `**<Sub-role>** — <dates>` line per role tenure under a company.
- `- ` bullets under each sub-role.

The template at the skill's `assets/master-resume.md` shows a valid skeleton.

## Procedure

1. **Locate the workspace master-resume.** Ask for the workspace path if unknown. If none exists,
   start from the skill's `assets/master-resume.md` template.

2. **Ingest (if a resume or notes were provided in `$ARGUMENTS` or pointed at).** Read it (PDF via
   the Read tool; `.docx` via `python3 <SKILL_DIR>/scripts/extract_text.py <file>`; markdown or text
   directly) and map roles, sub-roles, dates, and accomplishments into the required structure.

3. **Interview to fill gaps**, one focused question at a time:
   - Missing roles, dates, or scope.
   - Quantified accomplishments (numbers, adoption, impact) for each significant role.
   - Skills and education.

4. **Write `master-resume.md`** in the required structure. Then verify the structure by reading it
   back: confirm it has a `## Experience` H2, one `### Company — Title` H3 per company, a
   `**Sub-role** — dates` line per tenure, and `- ` bullets under each sub-role. (The conjurer
   `stitch` step parses exactly this and will fail loudly later if the structure is wrong.)

Keep every entry truthful. Do not invent roles, numbers, or outcomes.
