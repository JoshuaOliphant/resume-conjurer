# ABOUTME: User-visible partial generation and failed-unit retry through real app routes.
# ABOUTME: Reuses the live-flow workspace and same-origin client fixtures.
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
import test_live_flow
from test_live_flow import SLUG, SameOriginClient

from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.verification_fake import NoVerificationPort
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.main import create_app
from app.runs import RunManager

workspace = test_live_flow.workspace


class FailsOnce(FakeGenerationPort):
    def __init__(self):
        super().__init__()
        self.failed = False
        self.calls = []
        self.gate = None

    async def variants(self, slug, unit, n=4):
        self.calls.append(unit.unit_id)
        if not self.failed:
            self.failed = True
            return []
        if self.gate is not None:
            await self.gate.wait()
        return await super().variants(slug, unit, n)


@pytest.fixture
def partial_application(workspace, caplog):
    repo = FsWorkspaceRepository(workspace)
    gen = FailsOnce()
    manager = RunManager(repo, gen, NoVerificationPort())
    async def generate():
        manager.start(SLUG)
        await manager.join(SLUG)
    asyncio.run(generate())
    assert "unit generation failed" in caplog.text
    app = create_app(repo, gen, manager, live=True)
    with SameOriginClient(app) as client:
        yield client, manager, repo, gen


def test_partial_results_offer_keyboard_retry_and_preserve_successful_picks(partial_application):
    client, manager, repo, gen = partial_application
    first, second = repo.load_application(SLUG).units[:2]
    repo.set_pick(SLUG, second.id, second.variants[0].id)
    before = repo.get_picks(SLUG)
    outline = client.get("/outline")
    assert outline.status_code == 200
    assert f"Retry {first.label}" in outline.text
    assert 'type="submit"' in outline.text and 'aria-live="polite"' in outline.text
    assert "4 variants" in outline.text
    assert "Retry" in client.get("/curate/0").text
    gen.calls.clear()
    response = client.post(f"/generate/retry/{first.id}")
    assert response.status_code == 200
    assert "Generating" in response.text
    client.portal.call(manager.join, SLUG)
    assert gen.calls == [first.id]
    assert manager.status(SLUG).state == "done"
    assert repo.get_picks(SLUG) == before
    assert "Review generated lines" in client.get("/generate/unit-status").text
    assert 'HX-Redirect' in client.get("/generate/status").headers


@pytest.mark.parametrize("path,headers,status", [
    ("cover_letter.opening", {}, 403),
    ("other-user/unit", {"sec-fetch-site": "same-origin"}, 404),
    ("cover_letter.p2", {"sec-fetch-site": "same-origin"}, 404),
])
def test_unavailable_and_cross_origin_targets_do_not_generate(partial_application, path, headers, status):
    client, manager, repo, gen = partial_application
    before = list(gen.calls)
    assert client.post(f"/generate/retry/{path}", headers=headers).status_code == status
    assert gen.calls == before


def test_duplicate_retry_shows_current_progress(partial_application):
    client, manager, repo, gen = partial_application
    gen.gate = asyncio.Event()
    before = len(gen.calls)
    client.post("/generate/retry/cover_letter.opening")
    response = client.post("/generate/retry/cover_letter.opening", headers={"origin": "http://testserver"})
    assert response.status_code == 200
    assert "Generating" in response.text
    client.portal.call(gen.gate.set)
    client.portal.call(manager.join, SLUG)
    assert len(gen.calls) == before + 1


def test_restart_preserves_drafts_picks_and_failed_unit_retry(partial_application):
    client, manager, repo, gen = partial_application
    first, good = repo.load_application(SLUG).units[:2]
    repo.set_pick(SLUG, good.id, good.variants[1].id)
    previous = repo.get_picks(SLUG)
    variants = repo.load_application(SLUG).units[1].variants
    resumed = RunManager(repo, FakeGenerationPort(), NoVerificationPort())
    assert resumed.status(SLUG).state == "partial"
    app = create_app(repo, FakeGenerationPort(), resumed, live=True)
    with SameOriginClient(app) as reopened:
        assert f"Retry {first.label}" in reopened.get("/outline").text
        assert repo.get_picks(SLUG) == previous
        assert repo.load_application(SLUG).units[1].variants == variants
        reopened.post(f"/generate/retry/{first.id}")
        assert reopened.portal is not None
        reopened.portal.call(resumed.join, SLUG)
        assert resumed.status(SLUG).state == "done"
        assert repo.get_picks(SLUG) == previous


def test_restart_marks_unfinished_attempt_retryable_without_generating(partial_application):
    client, manager, repo, gen = partial_application
    statuses = repo.load_generation_status(SLUG)
    target = statuses["cover_letter.opening"]
    target.state = "generating"
    target.error = None
    repo.save_generation_status(SLUG, statuses)
    resumed_gen = FakeGenerationPort()
    resumed = RunManager(repo, resumed_gen, NoVerificationPort())
    status = resumed.status(SLUG)
    assert status.state == "partial"
    assert status.units["cover_letter.opening"].state == "failed"
    error = status.units["cover_letter.opening"].error
    assert error is not None and "interrupted" in error
    assert resumed_gen._calls == 0
    app = create_app(repo, resumed_gen, resumed, live=True)
    with SameOriginClient(app) as reopened:
        page = reopened.get("/outline")
        assert "Retry Opening" in page.text
        assert "Generating Opening" not in page.text


def test_saved_result_survives_missed_status_update(partial_application):
    client, manager, repo, gen = partial_application
    target = "cover_letter.opening"
    async def complete():
        manager.retry_unit(SLUG, target)
        await manager.join(SLUG)
    asyncio.run(complete())
    statuses = repo.load_generation_status(SLUG)
    statuses[target].state = "generating"
    repo.save_generation_status(SLUG, statuses)
    resumed = RunManager(repo, FakeGenerationPort(), NoVerificationPort())
    assert resumed.status(SLUG).state == "done"
    assert resumed.status(SLUG).units[target].state == "succeeded"


@pytest.mark.parametrize("fault", ["json", "list", "outline", "ledger", "binding", "binding-type", "binding-format", "empty-ledger"])
def test_unreadable_or_stale_metadata_never_claims_active_generation(partial_application, caplog, fault):
    client, manager, repo, gen = partial_application
    path = repo.root / "applications" / SLUG / "generation.json"
    before = repo.get_picks(SLUG)
    if fault == "outline":
        outline = repo.load_outline(SLUG)
        repo.save_outline(SLUG, replace(outline, company="Different application"))
    elif fault == "json":
        path.write_text("{")
    elif fault == "list":
        path.write_text("[]")
    else:
        data = json.loads(path.read_text())
        if fault == "binding":
            data.pop("outline")
        elif fault == "binding-type":
            data["outline"] = []
        elif fault == "binding-format":
            data["outline"] = "bad-hash"
        elif fault == "empty-ledger":
            data["units"] = {}
        else:
            data.pop("units")
        path.write_text(json.dumps(data))
    resumed = RunManager(repo, FakeGenerationPort(), NoVerificationPort())
    status = resumed.status(SLUG)
    assert status.state == "error"
    assert all(u.state != "generating" for u in status.units.values())
    assert repo.get_picks(SLUG) == before
    if fault == "outline":
        assert all(not u.variants for u in repo.load_application(SLUG).units)
    else:
        assert repo.load_application(SLUG).units[1].variants
    assert "could not recover generation progress" in caplog.text


def test_legacy_workspace_recovers_from_stored_variants(partial_application):
    client, manager, repo, gen = partial_application
    (repo.root / "applications" / SLUG / "generation.json").unlink()
    resumed_gen = FakeGenerationPort()
    status = RunManager(repo, resumed_gen, NoVerificationPort()).status(SLUG)
    assert status.state == "partial"
    assert status.units_done == 5
    assert resumed_gen._calls == 0


def test_retry_does_not_launch_when_progress_cannot_be_stored(partial_application, monkeypatch, caplog):
    client, manager, repo, gen = partial_application
    path = repo.root / "applications" / SLUG / "generation.json"
    before = path.read_bytes()
    previous_calls = len(gen.calls)
    real_replace = os.replace
    def fails(source, target):
        if target == path:
            raise OSError("metadata storage unavailable")
        return real_replace(source, target)
    monkeypatch.setattr(os, "replace", fails)
    response = client.post("/generate/retry/cover_letter.opening")
    assert response.status_code == 200
    assert "Check workspace storage" in response.text
    assert len(gen.calls) == previous_calls
    assert path.read_bytes() == before
    assert "generation run failed" in caplog.text


@pytest.mark.parametrize("current_path", ["/curate/0", "/outline"])
def test_completed_retry_returns_to_the_current_unit(partial_application, current_path):
    client, manager, repo, gen = partial_application
    async def retry():
        manager.retry_unit(SLUG, "cover_letter.opening")
        await manager.join(SLUG)
    asyncio.run(retry())
    response = client.get("/generate/unit-status", headers={"HX-Current-URL": "http://testserver" + current_path})
    assert response.headers.get("HX-Redirect") == current_path
    assert "variant__radio" in client.get("/curate/0").text
    unsafe = client.get("/generate/unit-status", headers={"HX-Current-URL": "http://evil.example/steal"})
    assert "HX-Redirect" not in unsafe.headers


def test_progress_does_not_redirect_to_an_unrelated_local_path(partial_application):
    client, manager, repo, gen = partial_application
    response = client.get("/generate/unit-status", headers={"HX-Current-URL": "http://testserver/steal"})
    assert "HX-Redirect" not in response.headers


def test_retry_waits_for_an_inflight_recovery_snapshot(partial_application):
    client, manager, repo, gen = partial_application
    reading, release, completed = Event(), Event(), Event()
    class SlowRecovery(FsWorkspaceRepository):
        first = True
        def load_generation_status(self, slug):
            data = super().load_generation_status(slug)
            if self.first:
                self.first = False
                reading.set()
                assert release.wait(5)
            return data
    resumed = RunManager(SlowRecovery(repo.root), FakeGenerationPort(), NoVerificationPort())
    def retry():
        async def attempt():
            resumed.retry_unit(SLUG, "cover_letter.opening")
            await resumed.join(SLUG)
        asyncio.run(attempt())
        completed.set()
    with ThreadPoolExecutor(max_workers=2) as workers:
        snapshot = workers.submit(resumed.status, SLUG)
        assert reading.wait(5)
        action = workers.submit(retry)
        try:
            assert not completed.wait(0.1)
        finally:
            release.set()
        snapshot.result(timeout=5)
        action.result(timeout=5)
    assert resumed.status(SLUG).state == "done"


def test_complete_cli_drafts_remain_authoritative_with_failed_metadata(partial_application):
    client, manager, repo, gen = partial_application
    target = repo.load_application(SLUG).units[0]
    outline = repo.load_outline(SLUG)
    variants = asyncio.run(FakeGenerationPort().variants(SLUG, outline.units[0]))
    repo.save_unit_variants(SLUG, replace(target, variants=variants))
    repo.set_pick(SLUG, target.id, variants[1].id)
    before = repo.get_picks(SLUG)
    assert len(repo.load_application(SLUG).units[0].variants) == 4
    calls = len(gen.calls)
    assert client.post(f"/generate/retry/{target.id}").status_code == 404
    assert len(gen.calls) == calls
    assert repo.get_picks(SLUG) == before


def test_removed_outline_target_is_refused_without_server_error(partial_application):
    client, manager, repo, gen = partial_application
    outline = repo.load_outline(SLUG)
    repo.save_outline(SLUG, replace(outline, cover_letter_units=outline.cover_letter_units[1:]))
    calls = len(gen.calls)
    app = create_app(repo, gen, manager, live=True)
    with SameOriginClient(app, raise_server_exceptions=False) as reopened:
        assert reopened.post("/generate/retry/cover_letter.opening").status_code == 404
    assert len(gen.calls) == calls


def test_corrupt_optional_metrics_do_not_block_recovery_or_retry(partial_application, caplog):
    client, manager, repo, gen = partial_application
    (repo.root / "applications" / SLUG / "metrics.json").write_text("{")
    resumed = RunManager(repo, FakeGenerationPort(), NoVerificationPort())
    app = create_app(repo, FakeGenerationPort(), resumed, live=True)
    with SameOriginClient(app, raise_server_exceptions=False) as reopened:
        assert reopened.get("/outline").status_code == 200
        assert resumed.status(SLUG).state == "partial"
        assert resumed.metrics(SLUG) is not None
        reopened.post("/generate/retry/cover_letter.opening")
        assert reopened.portal is not None
        reopened.portal.call(resumed.join, SLUG)
        assert resumed.status(SLUG).state == "done"
    assert "could not recover generation metrics" in caplog.text
