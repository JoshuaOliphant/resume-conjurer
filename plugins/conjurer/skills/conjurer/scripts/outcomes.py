# ABOUTME: Records what happened after an application went out, and reports callback rate per variant.
# ABOUTME: One append-only `outcome.json` event log per application; the report groups by frame, mode, edits, and ATS.
"""Implementation of `python3 outcomes.py log|report ...`.

    python3 outcomes.py log <workspace> <slug> <status> [--date YYYY-MM-DD] [--note TEXT] [--manual]
        [--sent-resume FILE] [--sent-cover-letter FILE] [--ats VENDOR]
    python3 outcomes.py report <workspace> [--as-of YYYY-MM-DD] [--silence-days N]

`applications/<slug>/outcome.json` holds the events in date order:

    {"events": [{"date": "2026-10-19", "status": "applied"},
                {"date": "2026-10-24", "status": "screen", "note": "recruiter call"}],
     "variant": {"frame": "conviction", "mode": "fast", "edits": "as stitched", "ats": "ashby"},
     "sent": {"resume.md": "<sha256>", "cover_letter.md": "<sha256>"}}

Logging `applied` snapshots what went out: `variant` records the frame and selection mode, and
`sent` fingerprints the stitched documents. The report reads the snapshot, never the current
directory, so editing `outline.json` or re-curating after submission cannot move an outcome into
another group.

An application is a **callback** once it reaches `screen`, `interview`, or `offer`. It counts
against the rate when it was `rejected`, or when it has sat at `applied` for longer than the
silence window (21 days by default). Until then it is pending, and `withdrawn` without a callback
leaves the denominator, because the user stopped the experiment, not the employer.

The report groups applications by that snapshot: the outline's strategic frame, and the mode that
picked the lines. `fast` means every pick in `variants.md` is still the curator's choice from
`curation.json`; `fast+guided` means the user took over and changed at least one; `guided` means
there was no curator; `manual` is an application made outside the pipeline (`--manual`).
When what went out differs from the stitched files (a PDF reworded after export, a letter pasted
into a form), commit the submitted text into the application directory and pass it with
`--sent-resume` / `--sent-cover-letter`; the fingerprints and the edit check then use those files.

`ats` names the applicant tracking system that screened the application, detected from the
posting URL in `jd.txt` (`ats.py`) or given with `--ats` when the posting URL does not show it.
Records logged before `ats` existed report as `unknown`.

Separately, `edits` records whether the sent documents still contain every picked variant
verbatim (`as stitched`) or were reworded by hand after stitching (`hand-edited`), so a fast run
the user polished is not credited to the curator alone.

`--as-of` reports the state on that date: later events and later applications are ignored.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ats import UNKNOWN, app_ats
from stitch import COVER_LETTER_PREFIX, parse_variants_md

STATUSES = ("applied", "screen", "interview", "offer", "rejected", "withdrawn")
CALLBACK_STATUSES = {"screen", "interview", "offer"}
SENT_DOCUMENTS = {"resume": "resume.md", "cover_letter": "cover_letter.md"}
DEFAULT_SILENCE_DAYS = 21


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_event(record: dict, status: str, when: date, note: str | None = None) -> dict:
    """Return the record with one event appended, rejecting events that would make the log incoherent."""
    if status not in STATUSES:
        raise ValueError(f"Unknown status '{status}'. Use one of: {', '.join(STATUSES)}")
    events = list(record.get("events", []))
    applied = [e for e in events if e["status"] == "applied"]
    if status == "applied" and applied:
        raise ValueError(f"Already logged as applied on {applied[0]['date']}")
    if status != "applied" and not applied:
        raise ValueError("Log 'applied' first; every outcome is measured from the application date")
    if events and when < date.fromisoformat(events[-1]["date"]):
        raise ValueError(f"{when.isoformat()} is before the last logged event ({events[-1]['date']})")
    event = {"date": when.isoformat(), "status": status}
    if note:
        event["note"] = note
    return {**record, "events": [*events, event]}


def selection_mode(app_dir: Path) -> str:
    """Who chose the lines in variants.md: the curator agent, the user, or both."""
    variants = app_dir / "variants.md"
    if not variants.exists():
        return "manual"
    curation = app_dir / "curation.json"
    if not curation.exists():
        return "guided"
    curator = json.loads(curation.read_text()).get("picks", {})
    for unit in parse_variants_md(variants.read_text()):
        pick = unit.picked
        if pick is not None and curator.get(unit.unit_id) != pick.n:
            return "fast+guided"
    return "fast"


def _squash(text: str) -> str:
    return " ".join(text.split())


def edit_state(app_dir: Path, sent_files: dict[str, str] = SENT_DOCUMENTS) -> str:
    """Whether the sent documents still hold every picked variant word for word."""
    variants = app_dir / "variants.md"
    if not variants.exists():
        return "n/a"
    sent = {
        role: _squash((app_dir / name).read_text()) if (app_dir / name).exists() else ""
        for role, name in sent_files.items()
    }
    for unit in parse_variants_md(variants.read_text()):
        pick = unit.picked
        if pick is None:
            continue
        doc = "cover_letter" if unit.unit_id.startswith(COVER_LETTER_PREFIX) else "resume"
        if _squash(pick.content) not in sent[doc]:
            return "hand-edited"
    return "as stitched"


def snapshot_variant(app_dir: Path, sent_files: dict[str, str] = SENT_DOCUMENTS, ats: str | None = None) -> dict:
    outline = app_dir / "outline.json"
    frame = json.loads(outline.read_text()).get("strategic_frame", "none") if outline.exists() else "none"
    return {
        "frame": frame,
        "mode": selection_mode(app_dir),
        "edits": edit_state(app_dir, sent_files),
        "ats": ats or app_ats(app_dir),
    }


def log_outcome(
    workspace: Path,
    slug: str,
    status: str,
    when: date,
    note: str | None = None,
    manual: bool = False,
    sent_files: dict[str, str] | None = None,
    ats: str | None = None,
) -> Path:
    """Append one event. `sent_files` overrides which files in the app dir count as submitted.

    `ats` names the vendor when the posting URL in `jd.txt` does not; it is read only at `applied`.
    """
    overrides = sent_files or {}
    sent_files = {**SENT_DOCUMENTS, **overrides}
    app_dir = workspace / "applications" / slug
    if not app_dir.is_dir():
        if not manual:
            raise FileNotFoundError(
                f"No application '{slug}' in {workspace / 'applications'}. "
                "Pass --manual to track one made outside the pipeline."
            )
        app_dir.mkdir(parents=True)
    path = app_dir / "outcome.json"
    record = json.loads(path.read_text()) if path.exists() else {}
    record = add_event(record, status, when, note)
    if status == "applied":
        for name in overrides.values():
            if not (app_dir / name).is_file():
                raise FileNotFoundError(f"Sent file {app_dir / name} does not exist")
        record["variant"] = snapshot_variant(app_dir, sent_files, ats)
        sent = {name: _fingerprint(app_dir / name) for name in sent_files.values() if (app_dir / name).exists()}
        if sent:
            record["sent"] = sent
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


@dataclass(frozen=True)
class Application:
    slug: str
    frame: str
    mode: str
    edits: str
    ats: str
    result: str  # callback | no_callback | pending | withdrawn


def classify(events: list[dict], as_of: date, silence_days: int) -> str | None:
    """The application's result as of a date, or None when it had not been sent by then."""
    events = [e for e in events if date.fromisoformat(e["date"]) <= as_of]
    statuses = {e["status"] for e in events}
    if "applied" not in statuses:
        return None
    if statuses & CALLBACK_STATUSES:
        return "callback"
    if "withdrawn" in statuses:
        return "withdrawn"
    if "rejected" in statuses:
        return "no_callback"
    applied_on = date.fromisoformat(next(e["date"] for e in events if e["status"] == "applied"))
    return "no_callback" if (as_of - applied_on).days > silence_days else "pending"


def load_applications(workspace: Path, as_of: date, silence_days: int) -> list[Application]:
    apps = []
    for path in sorted((workspace / "applications").glob("*/outcome.json")):
        record = json.loads(path.read_text())
        result = classify(record.get("events", []), as_of, silence_days)
        if result is None:
            continue
        variant = record["variant"]
        ats = variant.get("ats", UNKNOWN)
        apps.append(Application(path.parent.name, variant["frame"], variant["mode"], variant["edits"], ats, result))
    return apps


def _table(title: str, apps: list[Application], key: str) -> list[str]:
    groups: dict[str, list[Application]] = defaultdict(list)
    for app in apps:
        groups[getattr(app, key)].append(app)
    lines = [f"## By {title}", "", f"| {title} | sent | callbacks | decided | pending | callback rate |", "|---|---|---|---|---|---|"]
    for name in sorted(groups):
        lines.append(_row(name, groups[name]))
    lines.append(_row("**all**", apps))
    return [*lines, ""]


def _row(name: str, apps: list[Application]) -> str:
    counts = defaultdict(int)
    for app in apps:
        counts[app.result] += 1
    decided = counts["callback"] + counts["no_callback"]
    rate = f"{counts['callback']}/{decided} ({counts['callback'] / decided:.0%})" if decided else "n/a"
    sent = len(apps) - counts["withdrawn"]
    return f"| {name} | {sent} | {counts['callback']} | {decided} | {counts['pending']} | {rate} |"


def report(apps: list[Application], as_of: date, silence_days: int) -> str:
    if not apps:
        return "No outcomes logged yet. Log one with: outcomes.py log <workspace> <slug> applied\n"
    lines = [
        f"# Callback rate as of {as_of.isoformat()}",
        "",
        f"A callback is a screen, interview, or offer. Decided means a callback, a rejection, or "
        f"more than {silence_days} days of silence; pending applications are not in the rate.",
        "",
        *_table("frame", apps, "frame"),
        *_table("mode", apps, "mode"),
        *_table("edits", apps, "edits"),
        *_table("ATS", apps, "ats"),
    ]
    pending = [app.slug for app in apps if app.result == "pending"]
    if pending:
        lines += ["Pending: " + ", ".join(pending), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Track application outcomes and report callback rate.")
    sub = parser.add_subparsers(dest="command", required=True)

    log = sub.add_parser("log", help="Append an outcome event to an application")
    log.add_argument("workspace", type=Path)
    log.add_argument("slug")
    log.add_argument("status", choices=STATUSES)
    log.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default today")
    log.add_argument("--note")
    log.add_argument("--manual", action="store_true", help="Create the application dir if it does not exist")
    log.add_argument("--sent-resume", help="File in the app dir holding the resume text actually submitted")
    log.add_argument("--sent-cover-letter", help="File in the app dir holding the cover letter text actually submitted")
    log.add_argument("--ats", help="ATS vendor (ashby, greenhouse, workday, ...) when jd.txt's posting URL does not show it")

    rep = sub.add_parser("report", help="Callback rate by strategic frame, mode, edits, and ATS")
    rep.add_argument("workspace", type=Path)
    rep.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default today")
    rep.add_argument("--silence-days", type=int, default=DEFAULT_SILENCE_DAYS)

    args = parser.parse_args(argv)
    if args.command == "log":
        when = args.date or date.today()
        try:
            overrides = {"resume": args.sent_resume, "cover_letter": args.sent_cover_letter}
            sent_files = {role: name for role, name in overrides.items() if name}
            path = log_outcome(
                args.workspace, args.slug, args.status, when, args.note, args.manual, sent_files, args.ats
            )
        except (ValueError, FileNotFoundError) as exc:
            parser.exit(1, f"{exc}\n")
        print(f"Logged {args.status} on {when.isoformat()} in {path}")
    else:
        as_of = args.as_of or date.today()
        print(report(load_applications(args.workspace, as_of, args.silence_days), as_of, args.silence_days), end="")


if __name__ == "__main__":
    main()
