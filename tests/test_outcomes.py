# ABOUTME: Tests for application outcome logging and the callback-rate report.
# ABOUTME: Covers event-log validation, sent-document fingerprints, classification, grouping, and the CLI.
import hashlib
import json
from datetime import date

import pytest

import outcomes

D = date.fromisoformat


VARIANTS_MD = """# Conjurer Variants

## Unit: cover_letter.opening
<!-- conjurer:unit id=cover_letter.opening -->

### Variant 1: master-resume.md L3

First wording.

- [{one}] Pick

### Variant 2: master-resume.md L3

Second wording.

- [{two}] Pick

## Unit: cover_letter.closing
<!-- conjurer:unit id=cover_letter.closing -->

### Variant 1: master-resume.md L4

Closing.

- [ ] Pick
"""


def write_variants(app, pick):
    marks = {"one": "x" if pick == 1 else " ", "two": "x" if pick == 2 else " "}
    (app / "variants.md").write_text(VARIANTS_MD.format(**marks))


def make_app(workspace, slug, *, frame=None, mode="guided"):
    app = workspace / "applications" / slug
    app.mkdir(parents=True)
    if frame:
        (app / "outline.json").write_text(json.dumps({"strategic_frame": frame}))
    if mode in ("guided", "fast"):
        write_variants(app, 1)
    if mode == "fast":
        (app / "curation.json").write_text(json.dumps({"picks": {"cover_letter.opening": 1}}))
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


# --- selection mode / snapshot --------------------------------------------


def test_selection_mode_fast_when_every_pick_is_the_curators(tmp_path):
    app = make_app(tmp_path, "a", mode="fast")
    assert outcomes.selection_mode(app) == "fast"


def test_selection_mode_fast_plus_guided_after_a_takeover_changes_a_pick(tmp_path):
    app = make_app(tmp_path, "a", mode="fast")
    write_variants(app, 2)
    assert outcomes.selection_mode(app) == "fast+guided"


def test_selection_mode_guided_and_manual(tmp_path):
    assert outcomes.selection_mode(make_app(tmp_path, "g")) == "guided"
    assert outcomes.selection_mode(make_app(tmp_path, "m", mode="manual")) == "manual"


def test_attribution_is_snapshotted_at_applied(tmp_path):
    app = make_app(tmp_path, "a", frame="conviction", mode="fast")
    log(tmp_path, "a", "applied", "2026-10-01")
    log(tmp_path, "a", "screen", "2026-10-03")
    (app / "outline.json").write_text(json.dumps({"strategic_frame": "scale"}))
    write_variants(app, 2)
    (app / "curation.json").unlink()

    [result] = outcomes.load_applications(tmp_path, D("2026-10-05"), 21)
    assert (result.frame, result.mode, result.result) == ("conviction", "fast", "callback")


# --- classify / load_applications -----------------------------------------


@pytest.mark.parametrize(
    ("statuses", "as_of", "expected"),
    [
        (["applied", "screen", "rejected"], "2026-10-02", "callback"),
        (["applied", "withdrawn"], "2026-10-02", "withdrawn"),
        (["applied", "rejected"], "2026-10-02", "no_callback"),
        (["applied"], "2026-10-22", "pending"),
        (["applied"], "2026-10-23", "no_callback"),
        (["applied"], "2026-09-30", None),
    ],
)
def test_classify(statuses, as_of, expected):
    events = [{"date": "2026-10-01", "status": s} for s in statuses]
    assert outcomes.classify(events, D(as_of), 21) == expected


@pytest.mark.parametrize("later", ["screen", "rejected", "withdrawn"])
def test_classify_ignores_events_after_the_cutoff(later):
    events = [{"date": "2026-10-01", "status": "applied"}, {"date": "2026-10-24", "status": later}]
    assert outcomes.classify(events, D("2026-10-10"), 21) == "pending"


def test_load_applications_reads_the_snapshot_and_skips_unsent(tmp_path):
    make_app(tmp_path, "a-fast", frame="conviction", mode="fast")
    make_app(tmp_path, "b-guided", frame="multiplier")
    make_app(tmp_path, "c-not-applied")
    make_app(tmp_path, "d-no-frame")
    make_app(tmp_path, "f-applied-later")
    for slug in ("a-fast", "b-guided", "d-no-frame"):
        log(tmp_path, slug, "applied", "2026-10-01")
    log(tmp_path, "e-manual", "applied", "2026-10-01", manual=True)
    log(tmp_path, "f-applied-later", "applied", "2026-10-09")
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
        App("a", "conviction", "fast", "as stitched", "ashby", "callback"),
        App("b", "conviction", "fast", "as stitched", "ashby", "no_callback"),
        App("c", "multiplier", "guided", "hand-edited", "greenhouse", "pending"),
        App("d", "multiplier", "guided", "as stitched", "greenhouse", "withdrawn"),
        App("e", "conviction", "guided", "hand-edited", "greenhouse", "callback"),
    ]
    text = outcomes.report(apps, D("2026-10-19"), 21)
    assert "| conviction | 3 | 2 | 3 | 0 | 2/3 (67%) |" in text
    assert "| multiplier | 1 | 0 | 0 | 1 | n/a |" in text
    assert "| fast | 2 | 1 | 2 | 0 | 1/2 (50%) |" in text
    assert "| **all** | 4 | 2 | 3 | 1 | 2/3 (67%) |" in text
    assert "| ashby | 2 | 1 | 2 | 0 | 1/2 (50%) |" in text
    assert "| greenhouse | 2 | 1 | 1 | 1 | 1/1 (100%) |" in text
    assert "Pending: c" in text


def test_report_omits_pending_line_when_nothing_is_pending():
    apps = [outcomes.Application("a", "scale", "fast", "as stitched", "unknown", "callback")]
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


# --- edit state ------------------------------------------------------------


def test_edit_state_as_stitched_when_every_pick_is_in_the_sent_text(tmp_path):
    app = make_app(tmp_path, "a")
    (app / "cover_letter.md").write_text("First\n  wording.\n")
    assert outcomes.edit_state(app) == "as stitched"


def test_edit_state_hand_edited_when_a_pick_was_reworded(tmp_path):
    app = make_app(tmp_path, "a")
    (app / "cover_letter.md").write_text("A reworded opening.\n")
    assert outcomes.edit_state(app) == "hand-edited"


def test_edit_state_hand_edited_when_the_sent_document_is_missing(tmp_path):
    assert outcomes.edit_state(make_app(tmp_path, "a")) == "hand-edited"


def test_edit_state_checks_resume_picks_against_resume_md(tmp_path):
    app = make_app(tmp_path, "a", mode="manual")
    (app / "variants.md").write_text(
        "## Unit: resume.acme.bullet_1\n<!-- conjurer:unit id=resume.acme.bullet_1 -->\n\n"
        "### Variant 1: master-resume.md L8\n\n- Led the migration.\n\n- [x] Pick\n"
    )
    (app / "resume.md").write_text("# Resume\n\n- Led the migration.\n")
    assert outcomes.edit_state(app) == "as stitched"


def test_edit_state_not_applicable_without_variants(tmp_path):
    assert outcomes.edit_state(make_app(tmp_path, "m", mode="manual")) == "n/a"


def test_report_has_an_edits_table():
    apps = [outcomes.Application("a", "scale", "fast", "hand-edited", "unknown", "callback")]
    assert "| hand-edited | 1 | 1 | 1 | 0 | 1/1 (100%) |" in outcomes.report(apps, D("2026-10-19"), 21)


# --- sent-file overrides ---------------------------------------------------


def test_log_fingerprints_and_checks_the_submitted_files_when_given(tmp_path):
    app = make_app(tmp_path, "a")
    (app / "cover_letter.md").write_text("Stitched.\n")
    (app / "submitted-letter.md").write_text("First wording.\n")
    path = log(tmp_path, "a", "applied", "2026-10-01", sent_files={"cover_letter": "submitted-letter.md"})
    record = json.loads(path.read_text())
    assert record["sent"] == {"submitted-letter.md": hashlib.sha256(b"First wording.\n").hexdigest()}
    assert record["variant"]["edits"] == "as stitched"


def test_log_rejects_a_missing_sent_file(tmp_path):
    make_app(tmp_path, "a")
    with pytest.raises(FileNotFoundError, match="Sent file .*nope.md does not exist"):
        log(tmp_path, "a", "applied", "2026-10-01", sent_files={"resume": "nope.md"})


def test_cli_sent_overrides(tmp_path, capsys):
    app = make_app(tmp_path, "a")
    (app / "sent-resume.md").write_text("r\n")
    (app / "sent-letter.md").write_text("First wording.\n")
    outcomes.main(
        ["log", str(tmp_path), "a", "applied", "--date", "2026-10-01",
         "--sent-resume", "sent-resume.md", "--sent-cover-letter", "sent-letter.md"]
    )
    record = json.loads((app / "outcome.json").read_text())
    assert set(record["sent"]) == {"sent-resume.md", "sent-letter.md"}


# --- ATS ---------------------------------------------------------------------


def test_applied_snapshots_the_ats_from_the_posting_url(tmp_path):
    app = make_app(tmp_path, "a")
    (app / "jd.txt").write_text("Source: https://jobs.ashbyhq.com/elicit/d27d51d7\n")
    path = log(tmp_path, "a", "applied", "2026-10-01")
    assert json.loads(path.read_text())["variant"]["ats"] == "ashby"


def test_ats_override_wins_and_missing_jd_is_unknown(tmp_path):
    make_app(tmp_path, "a")
    make_app(tmp_path, "b")
    outcomes.main(["log", str(tmp_path), "a", "applied", "--date", "2026-10-01", "--ats", "workday"])
    log(tmp_path, "b", "applied", "2026-10-01")
    apps = outcomes.load_applications(tmp_path, D("2026-10-05"), 21)
    assert [(a.slug, a.ats) for a in apps] == [("a", "workday"), ("b", "unknown")]


def test_records_logged_before_ats_existed_report_as_unknown(tmp_path):
    app = tmp_path / "applications" / "old"
    app.mkdir(parents=True)
    record = {
        "events": [{"date": "2026-10-01", "status": "applied"}],
        "variant": {"frame": "scale", "mode": "manual", "edits": "n/a"},
    }
    (app / "outcome.json").write_text(json.dumps(record))
    [result] = outcomes.load_applications(tmp_path, D("2026-10-05"), 21)
    assert result.ats == "unknown"
