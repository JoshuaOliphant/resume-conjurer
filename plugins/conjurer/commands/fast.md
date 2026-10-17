---
description: Fast mode. Run the whole conjurer pipeline for one job description with agents making the choices, then hand back finished drafts and a report of every decision.
argument-hint: "<job description: a file path, a URL, or pasted text> [slug]"
---

# Conjurer Fast Mode

Run the conjurer pipeline end to end for one application without stopping to ask. Agents stand in
for the user at every judgment step: the outline's strategic frame, the curation picks, and the
lint fixes. The grimoire is the user's taste written down, so every judgment follows it.

Fast mode changes **who decides**, never **what may be claimed**. Claim discipline from the
conjurer skill holds in full: nothing is invented, every picked line cites the master resume or
evidence, and claim-check and glossary flags are reported rather than hidden.

The output is the same `applications/<slug>/` directory the guided flow writes, so the user can
take over at any point: open `variants.md`, change a `- [x] Pick`, and ask the conjurer skill to
re-stitch. Nothing fast mode does is a dead end.

`<SKILL_DIR>` below is the conjurer skill's directory (`skills/conjurer/` in this plugin).

## Ground rules

- **No questions.** Do not ask the user anything between steps 1 and 9. Where the guided flow
  would ask, decide using the grimoire and record the decision in the report. The only stops are
  the preconditions in step 1.
- **Hard caps.** 4 variants per unit, one generation pass (never regenerate a unit to chase a
  better variant), at most 3 lint-fix rounds.
- **Edits stay in `variants.md`.** Any fix to wording is made to the picked variant in
  `variants.md` and then re-stitched, so `variants.md` remains the single source of the picks and
  of the final text.

## Procedure

1. **Preconditions.** Resolve the workspace exactly as the conjurer skill's "Workspace" section
   says (current directory, or explicit paths the user gave). Stop and tell the user to run the
   guided setup (`/conjurer:grimoire`, `/conjurer:master-resume`) if `grimoire.md` or
   `master-resume.md` is missing or still a template (`FILL THIS IN`, `Acme Corp`, `Globex`). Fast
   mode never interviews. Stop and ask for the job description if `$ARGUMENTS` holds none.

2. **Init.** Pick a slug from the second argument, or derive `<company>-<role>` in kebab case from
   the JD. Run `python3 <SKILL_DIR>/scripts/init_app.py <slug> <workspace>`; if the directory
   already exists, choose a new slug by appending `-2`, `-3`, and so on, rather than overwriting.
   Write the JD into `applications/<slug>/jd.txt` (read a file path with Read, fetch a URL with
   WebFetch, or use pasted text as given). Leave `evidence.md` as the template unless the user's
   message supplied extra evidence; never write evidence the user did not give you.

3. **Outline.** Read the grimoire, master resume, JD, and evidence, and write `outline.json`
   exactly as step 3 of the conjurer skill and `references/pipeline.md` describe. Choose the
   strategic frame yourself, using the grimoire's guidance on which frame fits which kind of
   company. Use only unit ids that `composer.resume_unit_ids` would return.

4. **Variants.** Same as step 4 of the conjurer skill: one `variant-generator` subagent per unit,
   N = 4, all dispatched in a single tool-use block so they run in parallel. Assemble
   `variants.md`. If a unit's block does not parse (no `## Unit:` marker or no `### Variant`
   headers), dispatch that one unit once more; if it fails again, stop and report which unit failed.

5. **Checks.** Run the claim check and the glossary leak check, saving the leak report for the
   curator:

   ```bash
   python3 <SKILL_DIR>/scripts/verify.py applications/<slug> <workspace>
   python3 <SKILL_DIR>/scripts/leaks.py applications/<slug> <workspace> > applications/<slug>/leaks.txt
   ```

   `leaks.py` exits 1 when it finds a leak; that is a finding, not a failure. Without
   `TYPESAFE_API_KEY` the claim check is skipped; carry on and say so in the report.

6. **Curate.** Dispatch one `variant-curator` subagent with the paths to `grimoire.md`,
   `master-resume.md`, and the application's `jd.txt`, `outline.json`, `variants.md`, `leaks.txt`,
   and `support.json` (when it exists). Write its JSON block verbatim to
   `applications/<slug>/curation.json`, then mark the picks:

   ```bash
   python3 <SKILL_DIR>/scripts/picks.py applications/<slug> applications/<slug>/curation.json
   ```

   If `picks.py` rejects the JSON or reports units with no pick, send the curator the error once
   and retry; if it fails again, stop and report.

7. **Stitch, lint, fix.** Stitch, then lint:

   ```bash
   python3 <SKILL_DIR>/scripts/stitch.py applications/<slug> <workspace>/master-resume.md
   python3 <SKILL_DIR>/scripts/lint.py applications/<slug> <workspace>
   ```

   For each finding, edit the picked variant's text in `variants.md` with the smallest rewording
   that clears it (a `glossary-leak` takes the glossary's public description; a length finding is
   cleared by trimming picked paragraphs). Rewording may remove but never add a fact, number, or
   technology. A finding on a resume line no unit targeted comes from the master resume itself:
   never edit the master resume in fast mode; report the line instead. Re-stitch with
   `--overwrite` and lint again. Stop after 3 rounds and carry any remaining findings into the
   report.

8. **Check the picks.** `python3 <SKILL_DIR>/scripts/verify.py applications/<slug> <workspace> --picks`.
   Any picked line it flags goes in the report's review list; do not reword it further.

9. **Export.** `python3 <SKILL_DIR>/scripts/export_docs.py applications/<slug> pdf docx`. If pandoc
   is missing, the markdown is the deliverable.

10. **Report.** Write `applications/<slug>/fast-report.md`:

    ```markdown
    # Fast run: <company>, <role title>

    Strategic frame: `<frame>`. <frame_rationale from outline.json>

    ## Review these first
    - <unit_id>: <why: a needs_review note, a claim-check flag on the pick, a leftover lint finding>

    ## Picks
    | Unit | Pick | Why |
    |---|---|---|
    | cover_letter.opening | Variant 2 | <reason from curation.json> |

    ## Checks
    - Claim check: <ran, N picked lines flagged | skipped, no TYPESAFE_API_KEY>
    - Glossary leaks in picks: <none | list>
    - Lint: <clean after N rounds | remaining findings>
    - Export: <files written | markdown only>
    ```

    "Review these first" says `- Nothing flagged.` when it is empty. Then tell the user, in a few
    lines: where the documents are, how many units need review and which, and that they can swap
    any pick in `variants.md` and ask to re-stitch, or say "curate <slug>" to walk the guided
    curation over the same variants.
