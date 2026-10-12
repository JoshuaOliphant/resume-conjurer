# ABOUTME: Tests for the Jev VerificationPort: resolving each variant's cited lines, and the concurrency bound.
# ABOUTME: Offline tests inject a fake check callable; the `live` test asks the real Jev API.

import asyncio
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

import verify  # on sys.path once app.adapters.workspace_fs is imported
from app.adapters.verification_jev import JevVerificationPort
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.domain import Evidence, Unit, Variant
from glossary import GlossaryEntry

FIXTURE = Path(__file__).parent / "fixtures" / "workspace"
SLUG = "globex-staff-platform"
POOL = FsWorkspaceRepository(FIXTURE).load_inputs(SLUG).evidence_pool
PAGING_LINE = (
    "- Owned the billing on-call rotation; cut paging volume 60% by adding idempotency keys"
    " and a dead-letter replay tool."
)
MAILAPI = GlossaryEntry("MailAPI", ("Mail API",), "transactional email API")
MAILAPI_ROW = "MailAPI is a transactional email API"
GLOSSARY = (
    "\n## Glossary\n\n| Internal term | Aliases | Public description |\n|---|---|---|\n"
    "| MailAPI | Mail API | transactional email API |\n"
)


def _variant(variant_id: str, text: str, citation: str) -> Variant:
    # Generated variants carry their raw citation as ungrounded evidence (generation_sdk).
    return Variant(
        id=variant_id,
        text=text,
        evidence_items=(Evidence(id=citation, text=citation, source=citation, grounded=False),),
    )


def _unit(*variants: Variant) -> Unit:
    return Unit(
        id="resume.northwind.billing.bullet_3",
        kind="resume_bullet",
        label="Bullet 3",
        context="Surface the on-call work.",
        variants=list(variants),
    )


def _row(verdict: str, unsourced: list[str], fingerprint: str = "f" * 64) -> dict:
    return {
        "verdict": verdict,
        "relation": "contradicts",
        "relation_confidence": 0.6,
        "unstated": 0.97,
        "unsourced_numbers": unsourced,
        "fingerprint": fingerprint,
    }


def test_verify_checks_each_variant_against_its_resolved_cited_lines():
    calls = []

    def check(claim, cited, pool, api_key, *, glossary):
        calls.append((claim, cited, pool, api_key, glossary))
        return _row("conflicts" if cited else "untraced", [])

    unit = _unit(
        _variant("v1", "Cut paging volume 80%.", "master-resume.md L18"),
        _variant("v2", "Ran a billing guild.", "master-resume.md L999"),
    )
    verdicts = asyncio.run(JevVerificationPort("ts-key", check=check).verify(unit, POOL, (MAILAPI,)))

    assert {vid: s.verdict for vid, s in verdicts.items()} == {"v1": "conflicts", "v2": "untraced"}
    pool_lines = [evidence.text for evidence in POOL.values()]
    assert sorted(calls) == [
        ("Cut paging volume 80%.", [PAGING_LINE], pool_lines, "ts-key", (MAILAPI,)),
        ("Ran a billing guild.", [], pool_lines, "ts-key", (MAILAPI,)),
    ]


@pytest.mark.parametrize(
    ("options", "variants", "bound"),
    [({}, 12, 8), ({"concurrency": 2}, 6, 2)],
    ids=["default-bound-is-eight", "explicit-bound"],
)
def test_verify_runs_at_most_concurrency_checks_at_once(options: dict, variants: int, bound: int):
    lock = threading.Lock()
    in_flight = 0
    peak = 0

    def check(claim, cited, pool, api_key, *, glossary):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return _row("traced", [])

    unit = _unit(
        *(_variant(f"v{i}", "Led the migration.", "master-resume.md L16") for i in range(variants))
    )
    verdicts = asyncio.run(JevVerificationPort("ts-key", check=check, **options).verify(unit, POOL, ()))

    assert len(verdicts) == variants
    assert peak == bound


def test_verify_sends_jev_the_same_glossary_evidence_and_fingerprints_as_the_cli(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    shutil.copytree(FIXTURE, workspace)
    master = workspace / "master-resume.md"
    master.write_text(master.read_text().replace("billing on-call rotation", "MailAPI on-call rotation"))
    grimoire = workspace / "grimoire.md"
    grimoire.write_text(grimoire.read_text() + GLOSSARY)
    repo = FsWorkspaceRepository(workspace)
    unit = _unit(
        _variant("resume.northwind.billing.bullet_3#1", "Cut MailAPI paging volume 60%.", "master-resume.md L18"),
        _variant("resume.northwind.billing.bullet_3#2", "Led the billing migration.", "master-resume.md L16"),
    )
    repo.save_unit_variants(SLUG, unit)
    inputs = repo.load_inputs(SLUG)
    requests = []

    def ask_jev(state, questions, api_key, url=verify.JEV_URL, timeout=5.0):
        (question,) = questions
        requests.append((state["claim"], question, tuple(state["evidence"])))
        if question == "relation":
            return {"relation": {"choice": "supports", "confidence": 1.0}}
        return {"unstated": {"noul": 0.1}}

    monkeypatch.setattr(verify, "ask_jev", ask_jev)
    web = asyncio.run(JevVerificationPort("ts-key").verify(unit, inputs.evidence_pool, inputs.glossary))
    web_requests = sorted(requests)
    requests.clear()
    cli = verify.verify_app_dir(workspace / "applications" / SLUG, workspace, "ts-key")["variants"]

    assert sorted(requests) == web_requests
    assert {vid: support.fingerprint for vid, support in web.items()} == {
        vid: row["fingerprint"] for vid, row in cli.items()
    }
    relation = {claim: evidence for claim, question, evidence in web_requests if question == "relation"}
    pools = {claim: evidence for claim, question, evidence in web_requests if question == "unstated"}
    mailapi_line = inputs.evidence_pool["master-resume.md L18"].text
    assert relation["Cut MailAPI paging volume 60%."] == (mailapi_line, MAILAPI_ROW)
    assert pools["Cut MailAPI paging volume 60%."][-1] == MAILAPI_ROW
    assert MAILAPI_ROW not in relation["Led the billing migration."] + pools["Led the billing migration."]


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="no TYPESAFE_API_KEY")
def test_live_jev_classifies_supported_and_unsupported_claims():
    unit = _unit(
        _variant("supported-60", PAGING_LINE, "master-resume.md L18"),
        _variant(
            "planted-80",
            "Owned the billing on-call rotation; cut paging volume 80% by adding idempotency keys"
            " and a dead-letter replay tool.",
            "master-resume.md L18",
        ),
        _variant("team-25", "Led a team of 25 engineers who cut paging volume 60%.", "master-resume.md L18"),
        _variant("increased-60", "Increased paging volume 60%.", "master-resume.md L18"),
        _variant("missing-trace", PAGING_LINE, "master-resume.md L999"),
    )
    port = JevVerificationPort(os.environ["TYPESAFE_API_KEY"])
    verdicts = asyncio.run(port.verify(unit, POOL, ()))
    planted = verdicts["planted-80"]
    assert planted.verdict in {"conflicts", "adds_detail"}, planted
    assert planted.unsourced_numbers == ("80",)
    assert verdicts["supported-60"].verdict == "traced", verdicts["supported-60"]
    assert verdicts["supported-60"].unsourced_numbers == ()
    assert verdicts["team-25"].verdict == "adds_detail", verdicts["team-25"]
    assert verdicts["team-25"].unsourced_numbers == ("25",)
    assert verdicts["increased-60"].verdict == "conflicts", verdicts["increased-60"]
    assert verdicts["missing-trace"].verdict == "untraced", verdicts["missing-trace"]
