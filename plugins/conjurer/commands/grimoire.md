---
description: Build or refine the workspace grimoire (encoded taste) by interview and by ingesting pointed-at material.
argument-hint: "[optional paths to a resume, LinkedIn export, prior cover letters, or writing samples]"
---

# Build the Grimoire

Produce or refine `grimoire.md` in the user's conjurer workspace. The grimoire encodes the user's
positioning and voice; the variant generator follows it for every claim.

Target schema (the template at the skill's `assets/grimoire.md` shows the full structure):
Identity, Voice, Claim Discipline, Resume Bullet Patterns, Cover Letter Patterns (with the four
strategic frames), Anti-Patterns, Linter Checklist.

## Procedure

1. **Locate the workspace grimoire.** Ask for the workspace path if unknown. If no `grimoire.md`
   exists, start from the skill's `assets/grimoire.md` template.

2. **Ingest (if material was provided in `$ARGUMENTS` or the user points at files).** Read the
   resume, LinkedIn export, prior cover letters, or writing samples. Handle formats: read a PDF
   with the Read tool; convert a `.docx` with `python3 <SKILL_DIR>/scripts/extract_text.py <file>`;
   read markdown or text directly. Extract:
   - Positioning and the rare combination the user brings (-> Identity)
   - Recurring strong claims and quantified accomplishments (-> Bullet Pattern examples)
   - Voice tendencies and any phrases the user clearly favors or avoids (-> Voice)

3. **Pre-fill the universal sections** (Voice rules, Anti-Patterns, Linter Checklist) from the
   template defaults. Present them and let the user tweak.

4. **Interview to fill the personal gaps**, one focused question at a time:
   - Identity: what do you do, what is the rare combination, what ownership level do you assume?
   - Strategic angle: which of scale / friction / conviction / multiplier fits your typical targets?
   - Strong bullets: confirm or supply 3-5 real bullets that exemplify your best work.

5. **Write `grimoire.md`** to the workspace. Show a diff or summary of what changed.

Keep every claim truthful to what the user actually said or what the ingested material supports.
Do not invent accomplishments to fill the template.
