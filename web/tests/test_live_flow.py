# ABOUTME: Route tests for the live generation flow, wired with a FakeGenerationPort + temp FsRepo.
# ABOUTME: Exercises POST /start (live), the status partial's render branches, and the env composition.

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.generation_sdk import SdkGenerationPort
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.main import build_generation, build_repository, build_run_manager, create_app
from app.runs import RunManager, RunStatus

SLUG = "globex-staff-platform"
FIXTURE = Path(__file__).parent / "fixtures" / "workspace"


@pytest.fixture
def workspace(tmp_path):
    dest = tmp_path / "workspace"
    shutil.copytree(FIXTURE, dest)
    return dest


@pytest.fixture
def live_client(workspace):
    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen)
    app = create_app(repo=repo, gen=gen, run_manager=manager, live=True)
    with TestClient(app) as c:
        yield c, manager


def test_live_start_renders_the_progress_page(live_client):
    client, _ = live_client
    # The progress markup is rendered synchronously inside the handler from the status
    # set by start(), before the event loop steps the background task. The synchronous
    # "running" state itself is pinned deterministically in test_runs.py.
    r = client.post("/start", data={"source": "reuse", "jd": "x"})
    assert r.status_code == 200
    assert "Summoning" in r.text


def test_status_partial_running_keeps_polling(live_client):
    client, manager = live_client
    manager._status[SLUG] = RunStatus(state="running", units_done=2, units_total=6)
    r = client.get("/generate/status")
    assert r.status_code == 200
    assert "Summoned 2 of 6" in r.text
    assert "hx-trigger" in r.text  # still polling


def test_status_partial_done_redirects_to_outline(live_client):
    client, manager = live_client
    manager._status[SLUG] = RunStatus(state="done", units_done=6, units_total=6)
    r = client.get("/generate/status")
    assert r.status_code == 200
    assert r.headers["HX-Redirect"] == "/outline"


def test_status_partial_error_states_the_failure_honestly(live_client):
    client, manager = live_client
    manager._status[SLUG] = RunStatus(state="error", error="the model refused")
    r = client.get("/generate/status")
    assert r.status_code == 200
    assert "the model refused" in r.text
    assert "hx-trigger" not in r.text  # stop polling on error


def test_status_partial_idle_before_start(live_client):
    client, _ = live_client
    r = client.get("/generate/status")
    assert r.status_code == 200
    assert "Summoning" in r.text


def test_live_outline_renders_from_persisted_workspace(workspace):
    # Run generation to completion deterministically (no background race), then render
    # /outline from the persisted workspace through the same live-configured app.
    import asyncio

    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen)

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())
    assert manager.status(SLUG).state == "done"

    app = create_app(repo=repo, gen=gen, run_manager=manager, live=True)
    with TestClient(app) as c:
        r = c.get("/outline")
    assert r.status_code == 200
    assert "Globex" in r.text


# --- Composition root (env-keyed) -----------------------------------------


def test_build_repository_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("CONJURER_BACKEND", raising=False)
    assert isinstance(build_repository(), FakeWorkspaceRepository)


def test_build_repository_live_is_filesystem(monkeypatch, workspace):
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.setenv("CONJURER_WORKSPACE", str(workspace))
    assert isinstance(build_repository(), FsWorkspaceRepository)


def test_build_generation_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("CONJURER_BACKEND", raising=False)
    assert isinstance(build_generation(), FakeGenerationPort)


def test_build_generation_live_is_sdk(monkeypatch, workspace):
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.setenv("CONJURER_WORKSPACE", str(workspace))
    assert isinstance(build_generation(), SdkGenerationPort)


def test_build_run_manager_pairs_repo_and_gen(monkeypatch, workspace):
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.setenv("CONJURER_WORKSPACE", str(workspace))
    manager = build_run_manager()
    assert isinstance(manager, RunManager)


def test_live_repository_falls_back_to_the_fixture_workspace(monkeypatch):
    # Live config with no CONJURER_WORKSPACE resolves the bundled fixture workspace.
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.delenv("CONJURER_WORKSPACE", raising=False)
    repo = build_repository()
    assert isinstance(repo, FsWorkspaceRepository)
    assert repo.root.name == "workspace"


def test_live_reset_redirects_without_clearing(live_client):
    # In live config the on-disk variants.md is the source of truth; reset just returns home.
    client, _ = live_client
    r = client.post("/reset", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
