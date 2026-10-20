---
description: Log what happened to an application (applied, screen, interview, offer, rejected, withdrawn), or report callback rate by strategic frame and by mode.
argument-hint: "<slug> <status> [YYYY-MM-DD] [note]  |  report"
---

# Application Outcomes

Conjurer produces variants; this closes the loop by recording which ones got callbacks. Each
application keeps an append-only event log in `applications/<slug>/outcome.json`, written only by
`scripts/outcomes.py`. Never hand-edit it.

`<SKILL_DIR>` below is the conjurer skill's directory (`skills/conjurer/` in this plugin).
Resolve `<workspace>` as the conjurer skill's "Workspace" section says.

## Log an event

Parse `$ARGUMENTS` as `<slug> <status> [date] [note]`. Status is one of `applied`, `screen`,
`interview`, `offer`, `rejected`, `withdrawn`; map the user's words onto it ("recruiter call" is
`screen`, "onsite" is `interview`, "they passed" is `rejected`, "I pulled out" is `withdrawn`).
Date defaults to today.

```bash
python3 <SKILL_DIR>/scripts/outcomes.py log <workspace> <slug> <status> [--date YYYY-MM-DD] [--note "..."]
```

- Log `applied` only when the user says the application went out, with the date they give. It
  snapshots the strategic frame, the selection mode (`fast`, `fast+guided` when the user changed
  any of the curator's picks, `guided`, or `manual`), and whether the sent text was hand-edited
  after stitching, and fingerprints `resume.md` and `cover_letter.md`, so later edits to the
  application never change how this outcome is counted. Logging never submits or contacts
  anyone.
- If what was submitted differs from `resume.md` or `cover_letter.md` (a PDF reworded after
  export, a letter pasted into a form field), do not log against the stitched files. Commit the
  submitted text into the application directory first, then pass
  `--sent-resume <file>` and/or `--sent-cover-letter <file>` so the fingerprints and the edit check
  use what actually went out. If the submitted text is not available yet, wait.
- If the slug is not an application directory, list the slugs under `applications/` and ask which
  one was meant. For an application made before or outside conjurer, pass `--manual`; it creates
  `applications/<slug>/` holding only `outcome.json`, reported under mode `manual`.
- The script refuses an event before `applied`, a second `applied`, or a date earlier than the
  last event. Relay its message rather than working around it.

## Report

When `$ARGUMENTS` is `report` (or the user asks how applications are doing):

```bash
python3 <SKILL_DIR>/scripts/outcomes.py report <workspace>
```

Show the tables as printed, then say in a line or two what they do and do not support. A callback
is a screen, interview, or offer; an application sitting at `applied` for more than 21 days counts
as no callback, and younger ones are pending and left out of the rate. With fewer than about five
decided applications in a group, say the difference between groups is noise, not a finding.
