---
description: Build or refine the workspace grimoire (encoded taste) by interview and by ingesting pointed-at material.
argument-hint: "[optional paths to a resume, LinkedIn export, prior cover letters, or writing samples]"
---

# Build the Grimoire

Produce or refine `grimoire.md` in the user's conjurer workspace. The grimoire encodes the user's
positioning and voice; the variant generator follows it for every claim.

Target schema (the template at the skill's `assets/grimoire.md` shows the full structure):
Identity, Voice, Glossary, Claim Discipline, Resume Bullet Patterns, Cover Letter Patterns (with
the four strategic frames), Anti-Patterns, Linter Checklist.

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

3. **Interview for the Glossary** (below). It reads `master-resume.md` from the same workspace;
   if there is none, say so, skip this step, and suggest `/conjurer:master-resume` first.

4. **Pre-fill the universal sections** (Voice rules, Anti-Patterns, Linter Checklist) from the
   template defaults. Present them and let the user tweak.

5. **Interview to fill the personal gaps**, one focused question at a time:
   - Identity: what do you do, what is the rare combination, what ownership level do you assume?
   - Strategic angle: which of scale / friction / conviction / multiplier fits your typical targets?
   - Strong bullets: confirm or supply 3-5 real bullets that exemplify your best work.

6. **Write `grimoire.md`** to the workspace. Show a diff or summary of what changed.

Keep every claim truthful to what the user actually said or what the ingested material supports.
Do not invent accomplishments to fill the template.

## Glossary interview

The Glossary maps each internal term in the master resume to a public description an outside
reader (a recruiter or hiring manager who never worked at the applicant's employer) understands.
The table holds no numbers. A scale fact lives only in the master resume, in every bullet that
names the term, so the claim check can cite it.

1. **Propose candidates.** Read every bullet of `<workspace>/master-resume.md` and collect the
   internal terms: service codenames, internal API, tool, and function names, team names,
   hostnames, release labels, and internal process jargon. Leave out widely known public
   technologies and products (Kafka, Kubernetes, FastAPI, PostgreSQL, AWS, and the like), and
   leave out terms the Glossary already lists as an internal term or alias. Group spellings that
   look like the same term under one candidate and name them as likely aliases. Show the whole
   list at once, each candidate with every bullet that uses it, quoted in full:

   ```
   1. MailAPI (also spelled: mail-api)
      - "Built MailAPI, the transactional email service, on Kafka and Kubernetes."
      - "Migrated 14 product teams onto the mail-api client library."
   2. syseng-oncall
      - "Created syseng-oncall, cutting mean time to acknowledge by half."
   ```

2. **Settle each candidate, one at a time.** Ask the applicant to confirm or reject it. For a
   confirmed term, ask in turn:
   - **Public description**: what the thing does plus an industry category, such as
     "transactional email API". If the answer contains a number, move the number to the scale fact
     and ask for the description without it.
   - **Aliases**: other spellings of the same term in their history, comma-separated, or none.
   - **Scale fact**: a number that gives the term its size (volume, users, teams), such as
     "40M msgs/day", or none. Take only a number the applicant states; never estimate one.

3. **Write the confirmed rows** into the `## Glossary` table of `grimoire.md`, one row per term:
   `| <internal term> | <aliases, comma-separated> | <public description> |`, with the Aliases cell
   empty when there are none. Keep the table's header and separator rows. Remove the template's
   fictional example row (`Ledgerline`) and the comment beneath it. A cell must not contain `|`.
   Rejected terms are not written. Then confirm the table parses cleanly:

   ```bash
   python3 -c "import sys; sys.path.insert(0, '<SKILL_DIR>/scripts'); from glossary import parse_glossary; entries, warnings = parse_glossary(open('<workspace>/grimoire.md').read()); print(len(entries), 'entries'); print(*warnings, sep='\n')"
   ```

   Every confirmed term must be counted and no warning printed; fix any row a warning names.

4. **Work each scale fact into the master resume, one bullet at a time.** For each term with a
   scale fact, find every master-resume bullet that names the term or one of its aliases (as a
   whole word, ignoring case, spaces, and hyphens). Skip a bullet that already states the scale
   fact. For each remaining bullet, show the current bullet and the edited bullet, prefilled with
   the scale fact in parentheses right after the term:

   ```
   Current: - Built MailAPI, the transactional email service, on Kafka and Kubernetes.
   Edited:  - Built MailAPI (40M msgs/day), the transactional email service, on Kafka and Kubernetes.
   ```

   Ask the applicant to approve it, edit the wording, or skip it. Write a bullet to
   `master-resume.md` only after the applicant approves its final wording, and change nothing else
   in the file. The master resume keeps the internal term; only generated documents must not.
