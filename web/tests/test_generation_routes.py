# ABOUTME: User-visible partial generation and failed-unit retry through real app routes.
# ABOUTME: Reuses the live-flow workspace and same-origin client fixtures.
import asyncio

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
    assert f"Retry {first.id}" in outline.text
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
