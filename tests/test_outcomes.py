# ABOUTME: Tests for application outcome logging and the callback-rate report.
# ABOUTME: Covers event-log validation, sent-document fingerprints, classification, grouping, and the CLI.
import hashlib
import json
from datetime import date

import pytest

import outcomes

D = date.fromisoformat


def make_app(workspace, slug, *, frame=None, mode="guided"):
    app = workspace / "applications" / slug
    app.mkdir(parents=True)
    if frame:
        (app / "outline.json").write_text(json.dumps({"strategic_frame": frame}))
    if mode in ("guided", "fast"):
        (app / "variants.md").write_text("# Conjurer Variants\n")
    if mode == "fast":
        (app / "curation.json").write_text('{"picks": {}}')
    return app


def log(workspace, slug, status, day, **kwargs):
    return outcomes.log_outcome(workspace, slug, status, D(day), **kwargs)


# --- add_event -------------------------------------------------------------


def test_add_event_rejects_unknown_status():
    with pytest.raises(ValueError, match="Unknown status 'ghosted'"):
        outcomes.add_event({}, "ghosted", D("2026-10-19"))


def test_add_event_requires_applied_first():
    with pytest.raises(ValueError, match="Log 'applied' first"):
        outcomes.add_event({}, "screen", D("2026-10-19"))


def test_add_event_rejects_a_second_applied():
    record = outcomes.add_event({}, "applied", D("2026-10-01"))
    with pytest.raises(ValueError, match="Already logged as applied on 2026-10-01"):
        outcomes.add_event(record, "applied", D("2026-10-02"))


def test_add_event_rejects_going_back_in_time():
    record = outcomes.add_event({}, "applied", D("2026-10-10"))
    with pytest.raises(ValueError, match="2026-10-09 is before the last logged event"):
        outcomes.add_event(record, "rejected", D("2026-10-09"))


def test_add_event_keeps_note_only_when_given():
    record = outcomes.add_event({"sent": {"resume.md": "abc"}}, "applied", D("2026-10-10"))
    record = outcomes.add_event(record, "screen", D("2026-10-12"), note="recruiter call")
    assert record == {
        "sent": {"resume.md": "abc"},
        "events": [
            {"date": "2026-10-10", "status": "applied"},
            {"date": "2026-10-12", "status": "screen", "note": "recruiter call"},
        ],
    }


# --- log_outcome -----------------------------------------------------------


def test_log_applied_fingerprints_the_stitched_documents(tmp_path):
    app = make_app(tmp_path, "acme-sre")
    (app / "resume.md").write_text("# Resume\n")
    path = log(tmp_path, "acme-sre", "applied", "2026-10-19")
    record = json.loads(path.read_text())
    assert record["sent"] == {"resume.md": hashlib.sha256(b"# Resume\n").hexdigest()}
    assert record["events"] == [{"date": "2026-10-19", "status": "applied"}]


def test_log_without_stitched_documents_records_no_sent_block(tmp_path):
    make_app(tmp_path, "acme-sre")
    path = log(tmp_path, "acme-sre", "applied", "2026-10-19")
    assert "sent" not in json.loads(path.read_text())


def test_log_later_events_keep_the_original_fingerprint(tmp_path):
    app = make_app(tmp_path, "acme-sre")
    (app / "resume.md").write_text("v1\n")
    log(tmp_path, "acme-sre", "applied", "2026-10-01")
    (app / "resume.md").write_text("v2, re-stitched\n")
    path = log(tmp_path, "acme-sre", "screen", "2026-10-05")
    assert json.loads(path.read_text())["sent"]["resume.md"] == hashlib.sha256(b"v1\n").hexdigest()


def test_log_missing_application_needs_manual(tmp_path):
    with pytest.raises(FileNotFoundError, match="Pass --manual"):
        log(tmp_path, "workday", "applied", "2026-08-01")
    path = log(tmp_path, "workday", "applied", "2026-08-01", manual=True)
    assert path == tmp_path / "applications" / "workday" / "outcome.json"


# --- classify / load_applications -----------------------------------------


@pytest.mark.parametrize(
    ("statuses", "as_of", "expected"),
    [
        (["applied", "screen", "rejected"], "2026-10-02", "callback"),
        (["applied", "withdrawn"], "2026-10-02", "withdrawn"),
        (["applied", "rejected"], "2026-10-02", "no_callback"),
        (["applied"], "2026-10-22", "pending"),
        (["applied"], "2026-10-23", "no_callback"),
    ],
)
def test_classify(statuses, as_of, expected):
    events = [{"date": "2026-10-01", "status": s} for s in statuses]
    assert outcomes.classify(events, D(as_of), 21) == expected


def test_load_applications_reads_frame_and_mode(tmp_path):
    make_app(tmp_path, "a-fast", frame="conviction", mode="fast")
    make_app(tmp_path, "b-guided", frame="multiplier")
    make_app(tmp_path, "c-not-applied")
    make_app(tmp_path, "d-no-frame")
    for slug in ("a-fast", "b-guided", "d-no-frame"):
        log(tmp_path, slug, "applied", "2026-10-01")
    log(tmp_path, "e-manual", "applied", "2026-10-01", manual=True)
    (tmp_path / "applications" / "c-not-applied" / "outcome.json").write_text("{}")

    apps = outcomes.load_applications(tmp_path, D("2026-10-05"), 21)
    assert [(a.slug, a.frame, a.mode, a.result) for a in apps] == [
        ("a-fast", "conviction", "fast", "pending"),
        ("b-guided", "multiplier", "guided", "pending"),
        ("d-no-frame", "none", "guided", "pending"),
        ("e-manual", "none", "manual", "pending"),
    ]


# --- report ----------------------------------------------------------------


def test_report_with_no_outcomes():
    assert outcomes.report([], D("2026-10-19"), 21).startswith("No outcomes logged yet.")


def test_report_rates_by_frame_and_mode():
    App = outcomes.Application
    apps = [
        App("a", "conviction", "fast", "callback"),
        App("b", "conviction", "fast", "no_callback"),
        App("c", "multiplier", "guided", "pending"),
        App("d", "multiplier", "guided", "withdrawn"),
        App("e", "conviction", "guided", "callback"),
    ]
    text = outcomes.report(apps, D("2026-10-19"), 21)
    assert "| conviction | 3 | 2 | 3 | 0 | 2/3 (67%) |" in text
    assert "| multiplier | 1 | 0 | 0 | 1 | n/a |" in text
    assert "| fast | 2 | 1 | 2 | 0 | 1/2 (50%) |" in text
    assert "| **all** | 4 | 2 | 3 | 1 | 2/3 (67%) |" in text
    assert "Pending: c" in text


def test_report_omits_pending_line_when_nothing_is_pending():
    apps = [outcomes.Application("a", "scale", "fast", "callback")]
    assert "Pending:" not in outcomes.report(apps, D("2026-10-19"), 21)


# --- CLI -------------------------------------------------------------------


def test_cli_log_and_report(tmp_path, capsys):
    make_app(tmp_path, "acme-sre", frame="scale")
    outcomes.main(["log", str(tmp_path), "acme-sre", "applied", "--date", "2026-10-01"])
    outcomes.main(["log", str(tmp_path), "acme-sre", "screen", "--date", "2026-10-03", "--note", "call"])
    outcomes.main(["report", str(tmp_path), "--as-of", "2026-10-19"])
    out = capsys.readouterr().out
    assert "Logged applied on 2026-10-01" in out
    assert "| scale | 1 | 1 | 1 | 0 | 1/1 (100%) |" in out


def test_cli_defaults_to_today(tmp_path, capsys):
    make_app(tmp_path, "acme-sre")
    outcomes.main(["log", str(tmp_path), "acme-sre", "applied"])
    outcomes.main(["report", str(tmp_path), "--silence-days", "0"])
    out = capsys.readouterr().out
    assert f"Logged applied on {date.today().isoformat()}" in out
    assert f"# Callback rate as of {date.today().isoformat()}" in out


def test_cli_log_error_exits_1(tmp_path, capsys):
    make_app(tmp_path, "acme-sre")
    with pytest.raises(SystemExit) as exc:
        outcomes.main(["log", str(tmp_path), "acme-sre", "offer"])
    assert exc.value.code == 1
    assert "Log 'applied' first" in capsys.readouterr().err
