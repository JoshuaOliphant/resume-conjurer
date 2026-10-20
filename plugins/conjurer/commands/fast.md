---
description: Fast mode. Run the whole conjurer pipeline for one job description with agents making the choices, then hand back finished drafts and a report of every decision.
argument-hint: "<job description: a file path, a URL, or pasted text> [slug] [--force]"
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

- **No questions.** Do not ask the user anything between steps 1 and 11. Where the guided flow
  would ask, decide using the grimoire and record the decision in the report. The only stops are
  the preconditions in step 1 and the fit gate in step 3.
- **Fail fast.** A job the evidence cannot honestly serve is decided before any outline, variant,
  or cover letter work, not discovered in the report at the end. `--force` in `$ARGUMENTS` runs
  the full pipeline anyway; it is not a slug.
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
   The one exception: with `--force`, a directory the fit gate stopped (it holds `fit.json` and no
   `outline.json`) is reused as is, so a forced rerun continues the stopped application.
   Write the JD into `applications/<slug>/jd.txt` (read a file path with Read, fetch a URL with
   WebFetch, or use pasted text as given). Leave `evidence.md` as the template unless the user's
   message supplied extra evidence; never write evidence the user did not give you.

3. **Fit gate.** Before any outline work, decide whether the evidence can serve this job. Read the
   JD, master resume, evidence, and grimoire (its Identity section says what the user is
   positioning for), and write `applications/<slug>/fit.json`:

   ```json
   {"requirements": [
     {"requirement": "Hands-on production LLM agents or AI developer tools", "core": true,
      "status": "met", "evidence": "master-resume.md L14; L18"},
     {"requirement": "Proficiency in JAX, PyTorch, or XLA/MLIR", "core": true,
      "status": "missing", "evidence": ""}
   ]}
   ```

   List the JD's must-haves only, 3 to 12 of them, one ask per entry (split "Python and JAX" in
   two when the evidence covers one half). Leave preferred and nice-to-have items out. Mark
   `core: true` for the work the role exists to do: the subject of the title and the central
   responsibilities, not years of experience, degrees, or general traits. `status` is `met` when
   the evidence states it, `partial` when it shows adjacent or smaller-scale work, and `missing`
   otherwise; a skill the evidence only shows in an older role is `partial` at most, never current
   fluency. `evidence` cites lines in the same grammar variants use. Judge with claim
   discipline: what the evidence states, never what the user could plausibly ramp into.

   The gate is a cheap early stop for clear mismatches, not a role-fit review. A `pass` means
   only that drafting is worth the cost; any separate fit review still happens on the drafts.

   ```bash
   python3 <SKILL_DIR>/scripts/fit.py applications/<slug> <workspace>
   ```

   It prints `Fit: pass` or `Fit: stop` with the coverage, the missing core requirements, and any
   claim it counted as missing for lack of a grounded citation. It stops when half or more of the
   core requirements are missing or coverage is under 0.5. Exit 2 means `fit.json` is malformed:
   fix it once from the error and rerun; if it fails again, stop and report.

   On `stop` without `--force`, end the run here. Write `applications/<slug>/fast-report.md`:

   ```markdown
   # Fast run stopped: <company>, <role title>

   Fit gate: stop. <one or two sentences: what the role centers on, and what the evidence covers>

   ## Missing
   - <each missing core requirement, then each other missing one, from fit.py's output>

   ## What it would take
   <whether evidence the master resume lacks would change the verdict: add it to evidence.md
   and rerun, or run again with `--force` to draft anyway>
   ```

   Then tell the user in two or three lines: the verdict, the core gaps, and the `--force` rerun
   command. With `--force`, or on `pass`, carry on, and put any missing core requirement under
   "Review these first" in the final report.

4. **Outline.** Read the grimoire, master resume, JD, and evidence, and write `outline.json`
   exactly as step 3 of the conjurer skill and `references/pipeline.md` describe. Choose the
   strategic frame yourself, using the grimoire's guidance on which frame fits which kind of
   company. Use only unit ids that `composer.resume_unit_ids` would return.

   Then run `python3 <SKILL_DIR>/scripts/glossary_check.py units <workspace>` and add every unit it
   prints to `resume_units`, if the outline does not already target it, with a description telling
   the generator to use the glossary's public description. Each printed unit is a master-resume
   bullet that names an internal term; a bullet no unit targets is copied into `resume.md`
   verbatim, and fast mode never edits the master resume, so targeting it is the only way the leak
   leaves the resume.

5. **Variants.** Same as step 4 of the conjurer skill: one `variant-generator` subagent per unit,
   N = 4, all dispatched in a single tool-use block so they run in parallel. Assemble
   `variants.md`. If a unit's block does not parse (no `## Unit:` marker or no `### Variant`
   headers), dispatch that one unit once more; if it fails again, stop and report which unit failed.

6. **Checks.** Run the claim check and the glossary leak check, saving the leak report for the
   curator:

   ```bash
   python3 <SKILL_DIR>/scripts/verify.py applications/<slug> <workspace>
   python3 <SKILL_DIR>/scripts/leaks.py applications/<slug> <workspace> > applications/<slug>/leaks.txt
   ```

   `leaks.py` exits 1 when it finds a leak; that is a finding, not a failure. Without
   `TYPESAFE_API_KEY` the claim check is skipped; carry on and say so in the report.

7. **Curate.** Dispatch one `variant-curator` subagent with the paths to `grimoire.md`,
   `master-resume.md`, and the application's `jd.txt`, `outline.json`, `variants.md`, `leaks.txt`,
   and `support.json` (when it exists). Write its JSON block verbatim to
   `applications/<slug>/curation.json`, then mark the picks:

   ```bash
   python3 <SKILL_DIR>/scripts/picks.py applications/<slug> applications/<slug>/curation.json
   ```

   If `picks.py` rejects the JSON or reports units with no pick, send the curator the error once
   and retry; if it fails again, stop and report.

8. **Stitch, lint, fix.** Stitch, then lint:

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

9. **Check the picks.** `python3 <SKILL_DIR>/scripts/verify.py applications/<slug> <workspace> --picks`.
   Any picked line it flags goes in the report's review list; do not reword it further.

10. **Export.** `python3 <SKILL_DIR>/scripts/export_docs.py applications/<slug> pdf docx`. It prints
   one line per target; a target pandoc could not write (pandoc missing, or no PDF engine) reads
   `skipped`, and the markdown stays the deliverable for it. Report each line as given.

11. **Report.** Write `applications/<slug>/fast-report.md`:

    ```markdown
    # Fast run: <company>, <role title>

    Strategic frame: `<frame>`. <frame_rationale from outline.json>

    Fit gate: <pass | stop, forced>. <fit.py's first line>

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
