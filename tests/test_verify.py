# ABOUTME: Tests for the claim check: the verdict policy, number check, fingerprint, and Jev client.
# ABOUTME: Jev is a local http.server on 127.0.0.1 serving answers recorded from the live probe.
import hashlib
import json
import logging
import runpy
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import verify
from verify import Reading

MIGRATION = "- Led the migration of the billing platform from a monolith to event-driven services; invoice generation dropped from ~40s to under 2s."
ONCALL = "- Owned the billing on-call rotation; cut paging volume 60% by adding idempotency keys and a dead-letter replay tool."
TEMPLATE = "- Built an internal service template and CI pipeline adopted by 9 teams, cutting new-service setup from two days to under an hour."
MENTORSHIP = "- Mentored four engineers; two were promoted to senior within a year. Ran the weekly design-review forum."
COST_RECEIPT = "- Cost: billing infrastructure spend reduced 35% via right-sizing and spot capacity for batch reconciliation."

MASTER_RESUME = f"""# Jordan Rivera

## Experience

### Northwind — Senior Engineer

**Billing Platform** — 2021 to present
{MIGRATION}
{ONCALL}
{TEMPLATE}

## Leadership

{MENTORSHIP}
"""

EVIDENCE_MD = f"""# Evidence for globex-staff-platform

## Project receipts

{COST_RECEIPT}
"""

TEMPLATE_CLAIM = "Built an internal service template and CI pipeline adopted by 9 teams, cutting new-service setup from two days to under an hour."
TEAM_SIZE_CLAIM = "Led a team of 12 engineers through the migration of the billing platform to event-driven services, dropping invoice generation from 40s to under 2s."
PAGING_CLAIM = "Cut billing on-call paging volume 80% by introducing idempotency keys and a dead-letter replay tool."
COST_CLAIM = "Reduced billing infrastructure spend 35% by right-sizing consumers and moving batch reconciliation to spot capacity."
UNRESOLVED_CLAIM = "Mentored engineers across three teams."

VARIANTS_MD = f"""# Conjurer Variants

## Unit: cover_letter.opening
<!-- conjurer:unit id=cover_letter.opening -->
*opening paragraph*

### Variant 1: master-resume.md L10

{TEMPLATE_CLAIM}

*Axis: platform*

- [x] Pick

### Variant 2: master-resume.md L8

{TEAM_SIZE_CLAIM}

*Axis: leadership*

- [ ] Pick

## Unit: resume.northwind.billing.bullet_1
<!-- conjurer:unit id=resume.northwind.billing.bullet_1 -->
*reliability bullet*

### Variant 1: master-resume.md L9

- {PAGING_CLAIM}

*Axis: reliability*

- [ ] Pick

### Variant 2: master-resume.md L14

- {COST_CLAIM}

*Axis: cost*

- [x] Pick

### Variant 3: evidence.md - mentoring

- {UNRESOLVED_CLAIM}

*Axis: people*

- [ ] Pick
"""


def relation_response(choice, confidence, probabilities, input_tokens=520):
    return {
        "model": "jev-1.13.0",
        "answers": {"relation": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": probabilities}},
        "usage": {"input_tokens": input_tokens, "output_tokens": 55},
    }


def unstated_response(noul, input_tokens=905):
    return {
        "model": "jev-1.13.0",
        "answers": {"unstated": {"type": "noul", "noul": noul}},
        "usage": {"input_tokens": input_tokens, "output_tokens": 72},
    }


# Readings recorded live from jev-1.13.0 in the #8 probe, keyed by (question, claim).
RECORDED = {
    ("relation", TEMPLATE_CLAIM): relation_response("supports", 1.0, {"says_nothing": 0.0, "partly_supports": 0.0, "supports": 1.0, "contradicts": 0.0}),
    ("unstated", TEMPLATE_CLAIM): unstated_response(0.04),
    ("relation", TEAM_SIZE_CLAIM): relation_response("partly_supports", 1.0, {"supports": 0.0, "partly_supports": 1.0, "contradicts": 0.0, "says_nothing": 0.0}, 532),
    ("unstated", TEAM_SIZE_CLAIM): unstated_response(0.94, 913),
    ("relation", f"- {PAGING_CLAIM}"): relation_response("contradicts", 0.67, {"partly_supports": 0.24, "says_nothing": 0.0, "supports": 0.0, "contradicts": 0.76}),
    ("unstated", f"- {PAGING_CLAIM}"): unstated_response(0.97, 903),
    ("relation", f"- {COST_CLAIM}"): relation_response("says_nothing", 1.0, {"says_nothing": 1.0, "partly_supports": 0.0, "supports": 0.0, "contradicts": 0.0}, 510),
    ("unstated", f"- {COST_CLAIM}"): unstated_response(0.1, 900),
    ("unstated", f"- {UNRESOLVED_CLAIM}"): unstated_response(0.3),
}


class JevStub:
    """What the local Jev server answers, and every request it received."""

    def __init__(self, url):
        self.url = url
        self.responses = dict(RECORDED)
        self.status = 200
        self.raw_body = None
        self.delay = 0.0
        self.requests = []

    def questions_for(self, claim):
        return [r["body"] for r in self.requests if r["body"]["state"]["claim"] == claim]


@pytest.fixture
def jev():
    stub = None

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            stub.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
            time.sleep(stub.delay)
            (question,) = body["questions"]
            payload = stub.raw_body or json.dumps(stub.responses[(question, body["state"]["claim"])]).encode()
            self.send_response(stub.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stub = JevStub(f"http://127.0.0.1:{server.server_address[1]}/v1/systemone")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield stub
    server.shutdown()
    server.server_close()


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "master-resume.md").write_text(MASTER_RESUME)
    app_dir = tmp_path / "applications" / "globex-staff-platform"
    app_dir.mkdir(parents=True)
    (app_dir / "evidence.md").write_text(EVIDENCE_MD)
    (app_dir / "variants.md").write_text(VARIANTS_MD)
    return tmp_path, app_dir


# (relation, relation_confidence, unstated, has_trace, verdict). The first 20 rows are the #8
# probe, the next 12 the held-out run; expected verdicts follow the policy on #11.
VERDICT_TABLE = [
    pytest.param("supports", 0.7, 0.18, True, "traced", id="probe-clean-mig-1"),
    pytest.param("partly_supports", 0.46, 0.2, True, "traced", id="probe-clean-mig-3"),
    pytest.param("partly_supports", 0.53, 0.16, True, "traced", id="probe-clean-rel-1"),
    pytest.param("supports", 0.39, 0.18, True, "traced", id="probe-clean-rel-2"),
    pytest.param("supports", 1.0, 0.04, True, "traced", id="probe-clean-plat-1"),
    pytest.param("supports", 0.74, 0.22, True, "traced", id="probe-clean-plat-3"),
    pytest.param("supports", 0.51, 0.22, True, "traced", id="probe-clean-cover-2"),
    pytest.param("partly_supports", 0.98, 0.13, True, "adds_detail", id="probe-clean-close-1"),
    pytest.param("partly_supports", 0.98, 0.24, True, "adds_detail", id="probe-fixture-cover-1-three-years"),
    pytest.param("partly_supports", 0.55, 0.35, True, "traced", id="probe-fixture-rel-4-most-pages"),
    pytest.param("partly_supports", 0.86, 0.64, True, "adds_detail", id="probe-fixture-k8s-1"),
    pytest.param("partly_supports", 0.42, 0.42, True, "traced", id="probe-fixture-mig-4-20x"),
    pytest.param("contradicts", 0.67, 0.97, True, "conflicts", id="probe-adv-number-paging-80"),
    pytest.param("contradicts", 0.8, 0.97, True, "conflicts", id="probe-adv-number-40-teams"),
    pytest.param("partly_supports", 1.0, 0.94, True, "adds_detail", id="probe-adv-added-team-size"),
    pytest.param("partly_supports", 0.96, 0.41, True, "adds_detail", id="probe-adv-kafka-linkage"),
    pytest.param("partly_supports", 1.0, 0.89, True, "adds_detail", id="probe-adv-k8s-inflated"),
    pytest.param("contradicts", 0.56, 0.93, True, "conflicts", id="probe-adv-contradict-downtime"),
    pytest.param("says_nothing", 1.0, 0.1, True, "wrong_trace", id="probe-adv-wrong-citation"),
    pytest.param("partly_supports", 0.81, 0.2, True, "adds_detail", id="probe-adv-vague"),
    pytest.param("supports", 0.98, 0.07, True, "traced", id="heldout-clean-reword-mig"),
    pytest.param("supports", 0.93, 0.11, True, "traced", id="heldout-clean-reword-roll"),
    pytest.param("supports", 0.99, 0.04, True, "traced", id="heldout-clean-reword-tmpl"),
    pytest.param("supports", 0.95, 0.07, True, "traced", id="heldout-clean-reword-spend"),
    pytest.param("supports", 0.4, 0.31, True, "traced", id="heldout-clean-reword-oncall"),
    pytest.param("contradicts", 0.42, 0.97, True, "conflicts", id="heldout-adv-wrong-number"),
    pytest.param("contradicts", 0.6, 0.97, True, "conflicts", id="heldout-adv-extra-region"),
    pytest.param("partly_supports", 0.99, 0.84, True, "adds_detail", id="heldout-adv-added-tech"),
    pytest.param("contradicts", 0.4, 0.97, True, "conflicts", id="heldout-adv-inflated-scope"),
    pytest.param("partly_supports", 1.0, 0.94, True, "adds_detail", id="heldout-adv-invented-outcome"),
    pytest.param("says_nothing", 0.94, 0.06, True, "wrong_trace", id="heldout-adv-wrong-trace"),
    pytest.param("partly_supports", 0.99, 0.75, True, "adds_detail", id="heldout-adv-soft-overreach"),
    pytest.param("partly_supports", 0.8, 0.1, True, "adds_detail", id="partly-at-exact-min-confidence"),
    pytest.param("partly_supports", 0.79, 0.1, True, "traced", id="partly-just-below-min-confidence"),
    pytest.param("supports", 0.95, 0.5, True, "adds_detail", id="supports-with-unstated-at-flag"),
    pytest.param("supports", 0.95, 0.49, True, "traced", id="supports-with-unstated-just-below-flag"),
    pytest.param("says_nothing", 0.9, 0.5, True, "not_covered", id="says-nothing-and-pool-lacks-fact"),
    pytest.param(None, None, 0.5, False, "adds_detail", id="no-trace-states-unstated-fact"),
    pytest.param(None, None, 0.49, False, "untraced", id="no-trace-nothing-unstated"),
    pytest.param(None, None, None, True, "unchecked", id="no-reading-with-trace"),
    pytest.param(None, None, None, False, "unchecked", id="no-reading-without-trace"),
]


@pytest.mark.parametrize("relation, confidence, unstated, has_trace, expected", VERDICT_TABLE)
def test_verdict_for(relation, confidence, unstated, has_trace, expected):
    assert verify.verdict_for(Reading(relation, confidence, unstated), has_trace) == expected


@pytest.mark.parametrize(
    "claim, cited_text, expected",
    [
        pytest.param("Led a team of 12 engineers.", MIGRATION, ["12"], id="added-team-size"),
        pytest.param("Took invoices from forty seconds to under two.", "invoice generation dropped from ~40s to under 2s", [], id="number-words-match-digits"),
        pytest.param("Dropped invoicing 20x (40s to <2s).", "invoice generation dropped from ~40s to under 2s", ["20"], id="derived-multiplier-false-fires"),
        pytest.param("Served 1,200 customers in 3 regions and 3 zones.", "1200 customers", ["3"], id="thousands-separator-and-repeats"),
        pytest.param("Cut spend 55% and paging 80%.", COST_RECEIPT, ["55", "80"], id="in-claim-order"),
        pytest.param("Cut billing spend 35% via right-sizing.", COST_RECEIPT, [], id="all-sourced"),
    ],
)
def test_unsourced_numbers(claim, cited_text, expected):
    assert verify.unsourced_numbers(claim, cited_text) == expected


def test_fingerprint_hashes_claim_then_cited_lines():
    expected = hashlib.sha256(f"{COST_CLAIM}\n{MIGRATION}\n{ONCALL}".encode()).hexdigest()
    assert verify.fingerprint(COST_CLAIM, [MIGRATION, ONCALL]) == expected
    assert verify.fingerprint(COST_CLAIM, [ONCALL, MIGRATION]) != expected


@pytest.mark.parametrize(
    "verdict, numbers, expected",
    [
        pytest.param("traced", ["12"], "", id="traced-says-nothing"),
        pytest.param("untraced", [], "", id="untraced-says-nothing"),
        pytest.param("adds_detail", ["12"], "Adds detail your evidence doesn't state: 12", id="adds-detail-names-number"),
        pytest.param("adds_detail", [], "Adds detail your evidence doesn't state", id="adds-detail-without-number"),
        pytest.param("conflicts", ["80", "55"], "Conflicts with your evidence: 80, 55", id="conflicts-names-numbers"),
        pytest.param("wrong_trace", ["35"], "Your evidence supports this, but not the line it cites", id="wrong-trace-never-names-numbers"),
        pytest.param("not_covered", [], "The cited line doesn't cover this", id="not-covered"),
        pytest.param("unchecked", ["12"], "Couldn't check this line", id="unchecked"),
    ],
)
def test_note_for(verdict, numbers, expected):
    assert verify.note_for(verdict, numbers) == expected


def test_ask_jev_posts_the_pinned_model_and_returns_answers(jev):
    answers = verify.ask_jev(
        {"claim": TEMPLATE_CLAIM, "evidence": [TEMPLATE]}, {"relation": verify.RELATION_QUESTION}, "sk-test", url=jev.url
    )
    assert answers == RECORDED[("relation", TEMPLATE_CLAIM)]["answers"]
    (request,) = jev.requests
    assert request["path"] == "/v1/systemone"
    assert request["headers"]["Authorization"] == "Bearer sk-test"
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["body"] == {
        "model": "jev-1.13.0",
        "state": {"claim": TEMPLATE_CLAIM, "evidence": [TEMPLATE]},
        "questions": {"relation": verify.RELATION_QUESTION},
    }


def test_ask_jev_times_out(jev):
    jev.delay = 0.5
    with pytest.raises(TimeoutError):
        verify.ask_jev({"claim": TEMPLATE_CLAIM, "evidence": []}, {"unstated": verify.UNSTATED_QUESTION}, "sk-test", url=jev.url, timeout=0.1)


def test_check_variant_reads_cited_lines_then_pool(jev):
    pool = [MIGRATION, ONCALL, TEMPLATE]
    row = verify.check_variant(TEAM_SIZE_CLAIM, [MIGRATION], pool, "sk-test", url=jev.url)
    assert row == {
        "verdict": "adds_detail",
        "relation": "partly_supports",
        "relation_confidence": 1.0,
        "unstated": 0.94,
        "unsourced_numbers": ["12"],
        "fingerprint": verify.fingerprint(TEAM_SIZE_CLAIM, [MIGRATION]),
    }
    states = [body["state"] for body in jev.questions_for(TEAM_SIZE_CLAIM)]
    assert sorted(states, key=len) == sorted(
        [{"claim": TEAM_SIZE_CLAIM, "evidence": [MIGRATION]}, {"claim": TEAM_SIZE_CLAIM, "evidence": pool}], key=len
    )


def test_check_variant_without_a_grounded_line_asks_only_the_pool(jev):
    row = verify.check_variant(f"- {UNRESOLVED_CLAIM}", [], [MIGRATION], "sk-test", url=jev.url)
    assert row["verdict"] == "untraced"
    assert (row["relation"], row["relation_confidence"], row["unstated"]) == (None, None, 0.3)
    assert [list(r["body"]["questions"]) for r in jev.requests] == [["unstated"]]


@pytest.mark.parametrize(
    "status, raw_body, error",
    [
        pytest.param(500, b'{"error": "internal"}', "HTTP Error 500", id="server-error"),
        pytest.param(200, b"<html>gateway</html>", "Expecting value", id="malformed-body"),
        pytest.param(200, b'{"model": "jev-1.13.0", "usage": {}}', "'answers'", id="missing-answers"),
    ],
)
def test_check_variant_records_a_failed_request_as_unchecked(jev, caplog, status, raw_body, error):
    jev.status, jev.raw_body = status, raw_body
    with caplog.at_level(logging.WARNING, logger="verify"):
        row = verify.check_variant(TEAM_SIZE_CLAIM, [MIGRATION], [MIGRATION], "sk-test", url=jev.url)
    assert row["verdict"] == "unchecked"
    assert (row["relation"], row["relation_confidence"], row["unstated"]) == (None, None, None)
    assert row["unsourced_numbers"] == ["12"]
    (record,) = caplog.records
    assert "Claim check failed" in record.getMessage()
    assert error in record.getMessage()


def test_verify_app_dir_writes_one_row_per_variant(jev, workspace):
    root, app_dir = workspace
    document = verify.verify_app_dir(app_dir, root, "sk-test", url=jev.url)

    assert json.loads((app_dir / "support.json").read_text()) == document
    assert document["model"] == "jev-1.13.0"
    rows = document["variants"]
    assert {variant_id: row["verdict"] for variant_id, row in rows.items()} == {
        "cover_letter.opening#1": "traced",
        "cover_letter.opening#2": "adds_detail",
        "resume.northwind.billing.bullet_1#1": "conflicts",
        "resume.northwind.billing.bullet_1#2": "wrong_trace",
        "resume.northwind.billing.bullet_1#3": "untraced",
    }
    assert rows["resume.northwind.billing.bullet_1#1"]["unsourced_numbers"] == ["80"]
    wrong_trace = rows["resume.northwind.billing.bullet_1#2"]
    assert wrong_trace["fingerprint"] == verify.fingerprint(f"- {COST_CLAIM}", [MENTORSHIP])
    (relation_state,) = [body["state"] for body in jev.questions_for(f"- {COST_CLAIM}") if "relation" in body["questions"]]
    assert relation_state["evidence"] == [MENTORSHIP]
    pool_evidence = next(r["body"]["state"]["evidence"] for r in jev.requests if "unstated" in r["body"]["questions"])
    assert "**Billing Platform** — 2021 to present" in pool_evidence
    assert COST_RECEIPT in pool_evidence


def test_verify_app_dir_picks_only_checks_picks_and_keeps_other_rows(jev, workspace):
    root, app_dir = workspace
    verify.verify_app_dir(app_dir, root, "sk-test", url=jev.url)
    jev.requests.clear()
    jev.responses[("unstated", TEMPLATE_CLAIM)] = unstated_response(0.9)

    document = verify.verify_app_dir(app_dir, root, "sk-test", picks_only=True, url=jev.url)

    assert {r["body"]["state"]["claim"] for r in jev.requests} == {TEMPLATE_CLAIM, f"- {COST_CLAIM}"}
    assert document["variants"]["cover_letter.opening#1"]["verdict"] == "adds_detail"
    assert document["variants"]["resume.northwind.billing.bullet_1#1"]["verdict"] == "conflicts"
    assert len(document["variants"]) == 5


@pytest.mark.parametrize(
    "previous",
    [
        pytest.param(None, id="no-earlier-support-json"),
        pytest.param({"model": "jev-1.12.0", "variants": {"resume.northwind.billing.bullet_1#1": {"verdict": "traced"}}}, id="earlier-rows-from-another-model"),
    ],
)
def test_verify_app_dir_picks_only_writes_just_the_picks(jev, workspace, previous):
    root, app_dir = workspace
    if previous is not None:
        (app_dir / "support.json").write_text(json.dumps(previous))

    document = verify.verify_app_dir(app_dir, root, "sk-test", picks_only=True, url=jev.url)

    assert sorted(document["variants"]) == ["cover_letter.opening#1", "resume.northwind.billing.bullet_1#2"]


def test_main_prints_each_flagged_variant_with_its_note(jev, workspace, monkeypatch, capsys):
    root, app_dir = workspace
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test")

    verify.main([str(app_dir), str(root)], url=jev.url)

    assert capsys.readouterr().out.splitlines() == [
        "cover_letter.opening#2: Adds detail your evidence doesn't state: 12",
        "resume.northwind.billing.bullet_1#1: Conflicts with your evidence: 80",
        "resume.northwind.billing.bullet_1#2: Your evidence supports this, but not the line it cites",
        f"Claim check: 3 of 5 variants flagged. Wrote {app_dir / 'support.json'}",
    ]


def test_main_with_picks_prints_only_the_picked_flags(jev, workspace, monkeypatch, capsys):
    root, app_dir = workspace
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test")

    verify.main([str(app_dir), str(root)], url=jev.url)
    capsys.readouterr()
    verify.main([str(app_dir), str(root), "--picks"], url=jev.url)

    assert capsys.readouterr().out.splitlines() == [
        "resume.northwind.billing.bullet_1#2: Your evidence supports this, but not the line it cites",
        f"Claim check: 1 of 2 variants flagged. Wrote {app_dir / 'support.json'}",
    ]


@pytest.mark.parametrize("key", [pytest.param(None, id="key-unset"), pytest.param("", id="key-empty")])
def test_script_without_a_key_skips_and_writes_nothing(workspace, monkeypatch, capsys, key):
    root, app_dir = workspace
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    if key is not None:
        monkeypatch.setenv("TYPESAFE_API_KEY", key)
    monkeypatch.setattr("sys.argv", ["verify.py", str(app_dir), str(root)])

    runpy.run_path(verify.__file__, run_name="__main__")

    assert capsys.readouterr().out == "Claim check skipped: set TYPESAFE_API_KEY to check variants against your evidence.\n"
    assert not (app_dir / "support.json").exists()
