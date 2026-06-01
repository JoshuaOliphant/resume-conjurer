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
from app.adapters.composition import ScriptCompositionPort
from app.main import (
    build_composition,
    build_generation,
    build_repository,
    build_run_manager,
    create_app,
)
from app.runs import RunManager, RunStatus

SLUG = "globex-staff-platform"
FIXTURE = Path(__file__).parent / "fixtures" / "workspace"


def _live_outline():
    """A minimal outline whose ids token-match the fixture master-resume sub-roles.

    ``resume.northwind.billing.bullet_1`` matches the master-resume "Billing Platform"
    sub-role, so the composer (stitch) can slot it during the live /review test.
    """
    from app.domain import Outline, OutlineUnit

    return Outline(
        strategic_frame="multiplier",
        frame_rationale="Globex is a platform company; lead with leverage over many teams.",
        company="Globex",
        role_title="Staff Platform Engineer",
        cover_letter_units=(
            OutlineUnit(
                unit_id="cover_letter.opening",
                kind="cover_paragraph",
                description="Open on the platform migration as the proof of leverage.",
            ),
        ),
        resume_units=(
            OutlineUnit(
                unit_id="resume.northwind.billing.bullet_1",
                kind="resume_bullet",
                description="Surface the monolith-to-events migration.",
            ),
        ),
    )


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


def test_live_landing_tolerates_ungenerated_workspace(live_client):
    # The fixture workspace has jd.txt + evidence.md but NO outline.json. The live landing
    # must render the Start form (which POSTs /start), not 500 on a missing application.
    client, _ = live_client
    r = client.get("/")
    assert r.status_code == 200
    assert 'action="/start"' in r.text  # the form that kicks off generation
    assert "Tailor your resume" in r.text


@pytest.mark.parametrize("path", ["/outline", "/curate", "/curate/0", "/review", "/export"])
def test_live_pre_generation_steps_redirect_home(live_client, path):
    # Before generation has produced an outline, the later steps redirect to / (303)
    # instead of calling load_application and 500-ing on the missing outline.
    client, _ = live_client
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_live_curate_renders_unverified_note_for_ungrounded_citation(workspace):
    # An ungrounded (unresolvable) citation must render a muted "unverified" note, never a
    # fabricated quote, on the curate screen.
    from app.domain import Evidence, Unit, Variant
    from app.adapters.workspace_fs import FsWorkspaceRepository

    repo = FsWorkspaceRepository(workspace)
    repo.save_outline(SLUG, _live_outline())
    repo.save_variants(
        SLUG,
        [
            Unit(
                id="cover_letter.opening",
                kind="cover_paragraph",
                label="Opening",
                context="Open on the migration.",
                variants=[
                    Variant(
                        id="cover_letter.opening#1",
                        text="A grounded paragraph.",
                        evidence_items=(
                            Evidence(
                                id="evidence.md - made up", text="x", source="y", grounded=False
                            ),
                        ),
                    )
                ],
            )
        ],
    )
    gen = FakeGenerationPort()
    app = create_app(repo=repo, gen=gen, run_manager=RunManager(repo=repo, gen=gen), live=True)
    with TestClient(app) as c:
        r = c.get("/curate/0")
    assert r.status_code == 200
    assert "Unverified citation:" in r.text
    # The fabricated citation string must not be presented as a quoted evidence line.
    assert "“evidence.md - made up”" not in r.text


def _prepare_picked_live_workspace(workspace):
    """Save an outline + variants and pick every unit, so stitch has full input.

    Returns a live-configured app whose composition port runs the real stitch/lint/export
    over this workspace.
    """
    from app.domain import Unit, Variant

    repo = FsWorkspaceRepository(workspace)
    repo.save_outline(SLUG, _live_outline())
    repo.save_variants(
        SLUG,
        [
            Unit(
                id="cover_letter.opening",
                kind="cover_paragraph",
                label="Opening",
                context="Open on the migration.",
                variants=[
                    Variant(
                        id="cover_letter.opening#1",
                        text="I led the billing migration end to end.",
                        evidence_items=(),
                    )
                ],
            ),
            Unit(
                id="resume.northwind.billing.bullet_1",
                kind="resume_bullet",
                label="Bullet 1",
                context="Surface the migration.",
                variants=[
                    Variant(
                        id="resume.northwind.billing.bullet_1#1",
                        text="- Led the billing platform migration to event-driven services.",
                        evidence_items=(),
                    )
                ],
            ),
        ],
    )
    repo.set_pick(SLUG, "cover_letter.opening", "cover_letter.opening#1")
    repo.set_pick(SLUG, "resume.northwind.billing.bullet_1", "resume.northwind.billing.bullet_1#1")
    gen = FakeGenerationPort()
    comp = ScriptCompositionPort(workspace)
    app = create_app(
        repo=repo, gen=gen, run_manager=RunManager(repo=repo, gen=gen), live=True, comp=comp
    )
    return app


def test_live_review_stitches_and_lints_the_real_docs(workspace):
    app = _prepare_picked_live_workspace(workspace)
    with TestClient(app) as c:
        r = c.get("/review")
    assert r.status_code == 200
    assert "Style check" in r.text
    # Stitch wrote the real documents to the workspace.
    app_dir = workspace / "applications" / SLUG
    assert (app_dir / "cover_letter.md").exists()
    assert (app_dir / "resume.md").exists()
    # The picked content is in the stitched cover letter.
    assert "billing migration end to end" in (app_dir / "cover_letter.md").read_text()


def test_live_export_reports_the_written_or_skipped_map(workspace):
    import shutil as _shutil

    app = _prepare_picked_live_workspace(workspace)
    with TestClient(app) as c:
        c.get("/review")  # stitch first so export has docs
        r = c.get("/export")
    assert r.status_code == 200
    assert "Exported files" in r.text
    # The reported status matches the real environment: written iff pandoc is installed.
    have_pandoc = _shutil.which("pandoc") is not None
    if have_pandoc:
        assert "written" in r.text
    else:
        assert "skipped" in r.text


def test_build_composition_is_none_offline(monkeypatch):
    monkeypatch.delenv("CONJURER_BACKEND", raising=False)
    assert build_composition() is None


def test_build_composition_live_is_script_port(monkeypatch, workspace):
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.setenv("CONJURER_WORKSPACE", str(workspace))
    assert isinstance(build_composition(), ScriptCompositionPort)


def test_live_reset_redirects_without_clearing(live_client):
    # In live config the on-disk variants.md is the source of truth; reset just returns home.
    client, _ = live_client
    r = client.post("/reset", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
