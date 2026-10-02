# ABOUTME: Route tests for the live generation flow, wired with a FakeGenerationPort + temp FsRepo.
# ABOUTME: Exercises POST /start (live), the status partial's render branches, and the env composition.

import asyncio
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from app.adapters.composition import ScriptCompositionPort
from app.adapters.finals_fs import FinalDocuments
from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.generation_sdk import SdkGenerationPort
from app.adapters.verification_fake import FakeVerificationPort, NoVerificationPort
from app.adapters.verification_jev import JevVerificationPort
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.deps import (
    build_composition,
    build_generation,
    build_repository,
    build_verification,
)
from app.document_store import ConflictError, DocumentStore
from app.domain import Evidence, Variant
from app.main import create_app
from app.runs import RunManager, RunStatus
from fastapi.testclient import TestClient

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
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())
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
    assert "drafting options from your evidence" in r.text
    assert "Nothing is invented" not in r.text


def test_source_save_finishes_before_generation_can_start(workspace, monkeypatch):
    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())
    documents = DocumentStore(workspace)
    revision = documents.revision("master-resume.md")
    saving = Event()
    release_save = Event()
    start_called = Event()
    real_save = documents.save
    real_start = manager.start

    def held_save(name, text, expected_revision):
        saving.set()
        assert release_save.wait(5)
        return real_save(name, text, expected_revision)

    def observed_start(slug):
        start_called.set()
        return real_start(slug)

    monkeypatch.setattr(documents, "save", held_save)
    monkeypatch.setattr(manager, "start", observed_start)
    app = create_app(repo=repo, gen=gen, run_manager=manager, documents=documents, live=True)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as workers:
        save = workers.submit(client.post, "/documents/save", data={
            "document_name": "master-resume.md", "text": "# Saved before generation\n", "revision": revision,
        }, follow_redirects=False)
        assert saving.wait(5)
        start = workers.submit(client.post, "/start", data={"jd": "New JD"})
        try:
            assert not start_called.wait(0.2)
        finally:
            release_save.set()
        assert save.result(timeout=5).status_code == 303
        assert start.result(timeout=5).status_code == 200
        assert start_called.is_set()
    assert documents.read("master-resume.md") == "# Saved before generation\n"


def test_repeated_start_does_not_change_job_description_during_generation(live_client, workspace):
    client, manager = live_client
    jd_path = workspace / "applications" / SLUG / "jd.txt"
    original = jd_path.read_text()
    manager._status[SLUG] = RunStatus(state="running")
    response = client.post("/start", data={"jd": "Later JD"})
    assert response.status_code == 200
    assert jd_path.read_text() == original


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
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())

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


def _ran_live_app(workspace):
    """Run a fake generation to completion, then return a live app over that same manager.

    Reusing the manager (rather than building a fresh one) is what makes metrics(SLUG)
    populated, so /metrics and the /review summary have a real run to surface.
    """
    import asyncio

    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())
    assert manager.status(SLUG).state == "done"
    app = create_app(repo=repo, gen=gen, run_manager=manager, live=True)
    return app, manager


def test_metrics_endpoint_returns_run_metrics_after_a_run(workspace):
    app, manager = _ran_live_app(workspace)
    with TestClient(app) as c:
        r = c.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == SLUG
    assert body["line_count"] == manager.status(SLUG).units_total
    assert body["total_cost_usd"] > 0
    assert body["steps"][0]["name"] == "outline"


def test_metrics_endpoint_is_empty_before_any_run(live_client):
    client, _ = live_client
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.json() == {}


def test_review_shows_the_run_summary_line(workspace):
    app, _ = _ran_live_app(workspace)
    with TestClient(app) as c:
        r = c.get("/review")
    assert r.status_code == 200
    assert "This résumé" in r.text
    assert "from cache" in r.text
    assert "tokens" in r.text


def test_review_omits_the_summary_when_no_run(live_client):
    # The fake config has no run, so the review summary line is absent.
    client, _ = live_client
    # A fresh live workspace redirects /review home until generation runs; the offline fake
    # config (default) renders /review with no run, so assert the summary is omitted there.
    from app.main import create_app as _create_app

    repo = FakeWorkspaceRepository()
    gen = FakeGenerationPort()
    app = _create_app(repo=repo, gen=gen, run_manager=RunManager(repo=repo, gen=gen, verifier=NoVerificationPort()), live=False)
    with TestClient(app) as c:
        r = c.get("/review")
    assert r.status_code == 200
    assert "This résumé" not in r.text


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


def test_build_verification_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("CONJURER_BACKEND", raising=False)
    assert isinstance(build_verification(), FakeVerificationPort)


@pytest.mark.parametrize(
    ("verifier", "api_key", "expected"),
    [
        pytest.param("jev", "ts-key", JevVerificationPort, id="jev-with-key-checks-claims"),
        pytest.param(None, "ts-key", NoVerificationPort, id="unset-checks-nothing"),
    ],
)
def test_build_verification_live_follows_conjurer_verifier(monkeypatch, verifier, api_key, expected):
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.delenv("CONJURER_WORKSPACE", raising=False)
    if verifier is None:
        monkeypatch.delenv("CONJURER_VERIFIER", raising=False)
    else:
        monkeypatch.setenv("CONJURER_VERIFIER", verifier)
    monkeypatch.setenv("TYPESAFE_API_KEY", api_key)
    assert isinstance(build_verification(), expected)


@pytest.mark.parametrize(
    ("verifier", "message"),
    [
        pytest.param("jev", "TYPESAFE_API_KEY", id="jev-without-key-refuses-to-start"),
        pytest.param("jevv", "must be 'jev' or unset", id="unknown-verifier-refuses-to-start"),
    ],
)
def test_build_verification_live_refuses_a_verifier_it_cannot_run(monkeypatch, verifier, message):
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.setenv("CONJURER_VERIFIER", verifier)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=message):
        build_verification()


def test_live_repository_requires_workspace_env(monkeypatch):
    # No silent fallback to the tracked test fixture: a live run without CONJURER_WORKSPACE
    # would otherwise write generated JD/outline/variants/metrics into it.
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.delenv("CONJURER_WORKSPACE", raising=False)
    with pytest.raises(RuntimeError, match="CONJURER_WORKSPACE"):
        build_repository()


def test_live_generation_requires_workspace_env(monkeypatch):
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.delenv("CONJURER_WORKSPACE", raising=False)
    with pytest.raises(RuntimeError, match="CONJURER_WORKSPACE"):
        build_generation()


def test_live_composition_requires_workspace_env(monkeypatch):
    monkeypatch.setenv("CONJURER_BACKEND", "live")
    monkeypatch.delenv("CONJURER_WORKSPACE", raising=False)
    with pytest.raises(RuntimeError, match="CONJURER_WORKSPACE"):
        build_composition()


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
    from app.adapters.workspace_fs import FsWorkspaceRepository
    from app.domain import Evidence, Unit, Variant

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
    app = create_app(repo=repo, gen=gen, run_manager=RunManager(repo=repo, gen=gen, verifier=NoVerificationPort()), live=True)
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
        repo=repo, gen=gen, run_manager=RunManager(repo=repo, gen=gen, verifier=NoVerificationPort()), live=True, comp=comp,
        finals=FinalDocuments(workspace, SLUG),
    )
    return app


def _compose_live_documents(client):
    response = client.post("/review/compose", data={"cover_revision": "", "resume_revision": ""}, follow_redirects=False)
    assert response.status_code == 303


def test_live_review_stitches_and_lints_the_real_docs(workspace):
    app = _prepare_picked_live_workspace(workspace)
    with TestClient(app) as c:
        r = c.get("/review")
        assert 'action="/review/compose"' in r.text
        assert not (workspace / "applications" / SLUG / "cover_letter.md").exists()
        _compose_live_documents(c)
        r = c.get("/review")
    assert r.status_code == 200
    assert "Style check" in r.text
    assert "No style issues found. This does not verify facts." in r.text
    assert "Résumé · final document" in r.text
    assert "- Led the billing platform migration to event-driven services." in r.text
    # Stitch wrote the real documents to the workspace.
    app_dir = workspace / "applications" / SLUG
    assert (app_dir / "cover_letter.md").exists()
    assert (app_dir / "resume.md").exists()
    # The picked content is in the stitched cover letter.
    assert "billing migration end to end" in (app_dir / "cover_letter.md").read_text()
    assert "- Led the billing platform migration to event-driven services." in (app_dir / "resume.md").read_text()
    assert "- Led the billing platform migration to event-driven services." in (app_dir / "variants.md").read_text()


def test_live_review_get_preserves_manual_final_documents(workspace):
    app = _prepare_picked_live_workspace(workspace)
    app_dir = workspace / "applications" / SLUG
    (app_dir / "cover_letter.md").write_text("Manual letter with a careful claim.\n")
    (app_dir / "resume.md").write_text("# Manual résumé\n- Verified result: 42%.\n")
    with TestClient(app) as client:
        response = client.get("/review")
    assert response.status_code == 200
    assert (app_dir / "cover_letter.md").read_text() == "Manual letter with a careful claim.\n"
    assert (app_dir / "resume.md").read_text() == "# Manual résumé\n- Verified result: 42%.\n"


def test_review_waits_for_both_final_documents_during_compose(workspace, monkeypatch):
    _prepare_picked_live_workspace(workspace)
    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    finals = FinalDocuments(workspace, SLUG)
    app = create_app(repo=repo, gen=gen,
                     run_manager=RunManager(repo=repo, gen=gen, verifier=NoVerificationPort()),
                     live=True, comp=ScriptCompositionPort(workspace), finals=finals)
    cover_written = Event()
    resume_allowed = Event()
    review_sent = Event()
    review_done = Event()
    real_save = finals.store.save

    def hold_after_cover_write(name, text, revision):
        saved_revision = real_save(name, text, revision)
        if name == "cover_letter.md":
            cover_written.set()
            assert resume_allowed.wait(5)
        return saved_revision

    def read_review(client):
        review_sent.set()
        response = client.get("/review")
        review_done.set()
        return response

    monkeypatch.setattr(finals.store, "save", hold_after_cover_write)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as workers:
        compose = workers.submit(client.post, "/review/compose", data={"cover_revision": "", "resume_revision": ""},
                                 follow_redirects=False)
        assert cover_written.wait(5)
        assert finals.store.revision("cover_letter.md")
        assert not finals.store.revision("resume.md")
        review = workers.submit(read_review, client)
        assert review_sent.wait(5)
        try:
            assert not review_done.wait(0.2)
        finally:
            resume_allowed.set()
        assert compose.result(timeout=5).status_code == 303
        page = review.result(timeout=5)
    assert page.status_code == 200
    assert "Résumé · final document" in page.text
    assert finals.state().resume_text in page.text


def test_final_edit_survives_review_export_and_reload_without_changing_sources(workspace):
    app = _prepare_picked_live_workspace(workspace)
    app_dir = workspace / "applications" / SLUG
    master_before = (workspace / "master-resume.md").read_bytes()
    variants_before = (app_dir / "variants.md").read_bytes()
    finals = FinalDocuments(workspace, SLUG)
    with TestClient(app) as client:
        _compose_live_documents(client)
        original = finals.state()
        editor = client.get("/finals?name=resume.md")
        assert editor.status_code == 200
        assert f'name="revision" value="{original.resume_revision}"' in editor.text
        edited = "# Carefully edited résumé\n- Reduced billing latency 42%.\n"
        saved = client.post("/finals/save", data={"document_name": "resume.md", "text": edited,
                                                    "revision": original.resume_revision}, follow_redirects=False)
        assert saved.status_code == 303
        assert saved.headers["location"] == "/finals?name=resume.md&saved=true"
        assert 'role="status">Saved final text.' in client.get(saved.headers["location"]).text
        assert edited.strip() in client.get("/finals?name=resume.md").text
        review = client.get("/review")
        assert edited.strip() in review.text
        assert "support is unchecked" in review.text
        export = client.get("/export")
        assert 'href="/export/download/resume.md"' in export.text
        assert client.get("/export/download/resume.md").content == edited.encode()
    assert finals.state().edited
    assert original.resume_revision in finals.store.history("resume.md")
    assert (workspace / "master-resume.md").read_bytes() == master_before
    assert (app_dir / "variants.md").read_bytes() == variants_before


def test_final_edit_invalidates_older_derived_downloads(workspace):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    with TestClient(app) as client:
        _compose_live_documents(client)
        for extension in ("pdf", "docx"):
            (finals.app_dir / f"resume.{extension}").write_bytes(b"older export")
        revision = finals.state().resume_revision
        saved = client.post("/finals/save", data={"document_name": "resume.md",
                                                 "text": "# Revised résumé\n", "revision": revision})
        assert saved.status_code == 200
        for extension in ("pdf", "docx"):
            assert (finals.app_dir / f"resume.{extension}").read_bytes() == b"older export"
            assert client.get(f"/export/download/resume.{extension}").status_code == 404


def test_source_change_marks_final_stale_until_explicit_rebuild(workspace):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    with TestClient(app) as client:
        _compose_live_documents(client)
        old = finals.state()
        (workspace / "master-resume.md").write_text((workspace / "master-resume.md").read_text() + "\n- Added source fact.\n")
        review = client.get("/review")
        assert "picks or source documents changed" in review.text
        assert finals.state().stale
        assert finals.state().resume_text == old.resume_text
        (finals.app_dir / "cover_letter.pdf").write_bytes(b"older export")
        (finals.app_dir / "resume.docx").write_bytes(b"older export")
        rebuilt = client.post("/review/compose", data={"cover_revision": old.cover_revision,
                                                         "resume_revision": old.resume_revision}, follow_redirects=False)
        assert rebuilt.status_code == 303
        assert not finals.state().stale
        assert (finals.app_dir / "cover_letter.pdf").read_bytes() == b"older export"
        assert (finals.app_dir / "resume.docx").read_bytes() == b"older export"
        assert client.get("/export/download/cover_letter.pdf").status_code == 404
        assert client.get("/export/download/resume.docx").status_code == 404
    assert old.resume_revision in finals.store.history("resume.md")
    assert old.cover_revision in finals.store.history("cover_letter.md")


def test_changed_pick_marks_saved_final_stale_without_changing_it(workspace):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    repo = FsWorkspaceRepository(workspace)
    with TestClient(app) as client:
        _compose_live_documents(client)
        before = finals.state()
        units = repo.load_application(SLUG).units
        units[0].variants.append(Variant(id="cover_letter.opening#2", text="A different opening.", evidence_items=()))
        repo.save_variants(SLUG, units)
        repo.set_pick(SLUG, units[0].id, "cover_letter.opening#2")
        repo.set_pick(SLUG, units[1].id, units[1].variants[0].id)
        review = client.get("/review")
        assert "picks or source documents changed" in review.text
        assert before.cover_text in review.text
        assert finals.state().cover_text == before.cover_text
        rebuilt = client.post("/review/compose", data={"cover_revision": before.cover_revision,
                                                         "resume_revision": before.resume_revision}, follow_redirects=False)
        assert rebuilt.status_code == 303
    assert finals.state().cover_text == "A different opening.\n"


def test_final_save_conflict_recovers_submitted_text_and_rejects_invalid_name(workspace):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    with TestClient(app) as client:
        assert client.get("/finals?name=../master-resume.md").status_code == 400
        assert client.get("/finals?name=resume.md").status_code == 409
        _compose_live_documents(client)
        revision = finals.state().resume_revision
        finals.save("resume.md", "# Another tab\n", revision)
        conflict = client.post("/finals/save", data={"document_name": "resume.md",
                                                      "text": "# Keep my text\n", "revision": revision})
        assert conflict.status_code == 409
        assert "# Keep my text" in conflict.text
        assert f'name="revision" value="{revision}"' in conflict.text
        assert "Reload saved document" in conflict.text
        repeated = client.post("/finals/save", data={"document_name": "resume.md",
                                                    "text": "# Keep my text\n", "revision": revision})
        assert repeated.status_code == 409
        assert finals.store.read("resume.md") == "# Another tab\n"
        invalid = client.post("/finals/save", data={"document_name": "../master-resume.md",
                                                     "text": "x", "revision": "x"})
        assert invalid.status_code == 400


def test_final_compose_rejects_stale_revisions_without_replacing_saved_docs(workspace):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    with TestClient(app) as client:
        _compose_live_documents(client)
        old = finals.state()
        finals.save("cover_letter.md", "Manual cover.\n", old.cover_revision)
        response = client.post("/review/compose", data={"cover_revision": old.cover_revision,
                                                       "resume_revision": old.resume_revision})
        assert response.status_code == 409
        assert "revision is stale" in response.text
        assert finals.store.read("cover_letter.md") == "Manual cover.\n"


@pytest.mark.parametrize("prior_final", [False, True], ids=["first-compose", "rebuild"])
def test_failed_second_document_write_restores_prior_finals(workspace, monkeypatch, prior_final):
    _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    if prior_final:
        finals.compose("", "")
        current = finals.state()
        finals.save("cover_letter.md", "Manual cover.\n", current.cover_revision)
        finals.save("resume.md", "# Manual résumé\n", current.resume_revision)
    before = finals.state()
    real_save = finals.store.save
    failed = False

    def fail_resume_once(name, text, revision):
        nonlocal failed
        if name == "resume.md" and not failed:
            failed = True
            raise OSError("resume write failed")
        return real_save(name, text, revision)

    monkeypatch.setattr(finals.store, "save", fail_resume_once)
    with pytest.raises(OSError, match="resume write failed"):
        finals.compose(before.cover_revision, before.resume_revision)
    assert finals.state().cover_text == before.cover_text
    assert finals.state().resume_text == before.resume_text


def test_compose_recovery_preserves_a_concurrent_final_edit(workspace, monkeypatch):
    _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    finals.compose("", "")
    initial = finals.state()
    finals.save("cover_letter.md", "Manual cover.\n", initial.cover_revision)
    before = finals.state()
    real_save = finals.store.save
    failed = False

    def competing_edit_on_resume_failure(name, text, revision):
        nonlocal failed
        if name == "resume.md" and not failed:
            failed = True
            real_save("cover_letter.md", "Another editor's cover.\n", finals.store.revision("cover_letter.md"))
            raise OSError("resume write failed")
        return real_save(name, text, revision)

    monkeypatch.setattr(finals.store, "save", competing_edit_on_resume_failure)
    with pytest.raises(ConflictError, match="changed during composition recovery"):
        finals.compose(before.cover_revision, before.resume_revision)
    assert finals.store.read("cover_letter.md") == "Another editor's cover.\n"


def test_changed_inputs_during_staging_refuse_composition(workspace, monkeypatch):
    import app.adapters.finals_fs as final_module

    _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    real_stitch = final_module.stitch_app_dir

    def change_job_after_stitch(*args, **kwargs):
        result = real_stitch(*args, **kwargs)
        (finals.app_dir / "jd.txt").write_text("Changed job description")
        return result

    monkeypatch.setattr(final_module, "stitch_app_dir", change_job_after_stitch)
    with pytest.raises(ConflictError, match="sources changed"):
        finals.compose("", "")
    assert not finals.state().complete


@pytest.mark.parametrize(
    "metadata",
    ["{broken", "[]", '{"fingerprint":"abc","composed_revisions":[]}'],
    ids=["invalid-json", "wrong-shape", "invalid-revisions"],
)
def test_unreadable_composition_metadata_and_missing_source_mark_finals_stale(workspace, metadata):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    finals.compose("", "")
    before = finals.state()
    (finals.app_dir / ".final-composition.json").write_text(metadata)
    assert finals.state().stale
    with TestClient(app) as client:
        review = client.get("/review")
        assert review.status_code == 200
        assert "Composition record is invalid" in review.text
        assert "Claim support is unchecked" in review.text
        assert before.resume_text in review.text
        assert client.get("/export").status_code == 200
    (workspace / "master-resume.md").unlink()
    assert finals.state().stale


def test_composition_metadata_directory_preserves_saved_finals_and_shows_recovery(workspace):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    with TestClient(app) as client:
        _compose_live_documents(client)
        before = finals.state()
        path = finals.app_dir / ".final-composition.json"
        path.unlink()
        path.mkdir()
        review = client.get("/review")
        assert review.status_code == 200
        assert "Composition record could not be read" in review.text
        assert "Claim support is unchecked" in review.text
        assert before.cover_text in review.text
        assert before.resume_text in review.text
        assert client.get("/export").status_code == 200
        assert client.get("/export/download/resume.md").content == before.resume_text.encode()


def test_non_utf8_composition_record_preserves_saved_finals(workspace):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    with TestClient(app) as client:
        _compose_live_documents(client)
        saved = finals.state().resume_text
        (finals.app_dir / ".final-composition.json").write_bytes(b"\xff")
        review = client.get("/review")
        assert review.status_code == 200
        assert "Composition record could not be read" in review.text
        assert saved in review.text


def test_compose_failure_reports_error_without_creating_final_documents(workspace, monkeypatch):
    import app.adapters.finals_fs as final_module

    app = _prepare_picked_live_workspace(workspace)

    def fail_stitch(*args, **kwargs):
        raise OSError("staged write failed")

    monkeypatch.setattr(final_module, "stitch_app_dir", fail_stitch)
    with TestClient(app) as client:
        response = client.post("/review/compose", data={}, follow_redirects=False)
    assert response.status_code == 503
    assert "staged write failed" in response.text
    assert not FinalDocuments(workspace, SLUG).state().complete


def test_final_save_rejects_empty_text_without_changing_saved_document(workspace):
    app = _prepare_picked_live_workspace(workspace)
    finals = FinalDocuments(workspace, SLUG)
    with TestClient(app) as client:
        missing = client.post("/finals/save", data={"document_name": "resume.md", "text": "Draft",
                                                    "revision": ""})
        assert missing.status_code == 409
        _compose_live_documents(client)
        revision = finals.state().resume_revision
        invalid = client.post("/finals/save", data={"document_name": "resume.md", "text": "  ",
                                                    "revision": revision})
        assert invalid.status_code == 400
        assert "Document must not be empty" in invalid.text
        assert f'name="revision" value="{revision}"' in invalid.text
        assert finals.state().resume_revision == revision


@pytest.mark.parametrize("path", ["/review/compose", "/finals/save"])
@pytest.mark.parametrize("headers", [{"origin": "https://other.example"}, {"sec-fetch-site": "cross-site"}])
def test_final_mutations_reject_cross_origin_requests(workspace, path, headers):
    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())
    app = create_app(repo=repo, gen=gen, run_manager=manager, live=True,
                     comp=ScriptCompositionPort(workspace), finals=FinalDocuments(workspace, SLUG))
    with TestClient(app) as client:
        response = client.post(path, data={"document_name": "resume.md", "text": "Draft", "revision": ""}, headers=headers)
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/review/compose", "/finals/save", "/curate/0"])
def test_final_mutations_wait_for_generation(workspace, path):
    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())
    manager._status[SLUG] = RunStatus(state="running")
    app = create_app(repo=repo, gen=gen, run_manager=manager, live=True,
                     comp=ScriptCompositionPort(workspace), finals=FinalDocuments(workspace, SLUG))
    with TestClient(app) as client:
        response = client.post(path, data={"document_name": "resume.md", "text": "Draft", "revision": "",
                                           "variant_id": "cover_letter.opening#1"})
    assert response.status_code == 409
    assert "Wait for generation" in response.text


@pytest.mark.parametrize("path", ["/export", "/export/download/resume.md"])
def test_export_waits_for_generation_before_reading_saved_finals(workspace, path):
    _prepare_picked_live_workspace(workspace)
    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())
    manager._status[SLUG] = RunStatus(state="running")
    app = create_app(repo=repo, gen=gen, run_manager=manager, live=True,
                     comp=ScriptCompositionPort(workspace), finals=FinalDocuments(workspace, SLUG))
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 409
    assert "Wait for generation" in response.text


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="no TYPESAFE_API_KEY")
def test_real_jev_verdict_persists_and_reaches_live_curate_and_review(workspace):
    app = _prepare_picked_live_workspace(workspace)
    repo = FsWorkspaceRepository(workspace)
    units = repo.load_application(SLUG).units
    unit = units[1]
    citation = "master-resume.md L18"
    variant = Variant(
        id=f"{unit.id}#1",
        text="- Led a team of 25 engineers who cut paging volume 60%.",
        evidence_items=(Evidence(id=citation, text=citation, source=citation, grounded=False),),
    )
    unit.variants = [variant]
    repo.save_variants(SLUG, units)
    for chosen_unit in units:
        repo.set_pick(SLUG, chosen_unit.id, chosen_unit.variants[0].id)
    pool = repo.load_inputs(SLUG).evidence_pool
    verifier = JevVerificationPort(os.environ["TYPESAFE_API_KEY"])
    verdicts = asyncio.run(verifier.verify(unit, pool))
    assert verdicts[variant.id].verdict == "adds_detail", verdicts[variant.id]
    assert verdicts[variant.id].unsourced_numbers == ("25",)

    repo.save_support(SLUG, verdicts, units, pool)
    assert FsWorkspaceRepository(workspace).load_support(SLUG) == verdicts
    hydrated = repo.load_application(SLUG).units[1].variants[0]
    assert hydrated.support == verdicts[variant.id]

    with TestClient(app) as client:
        curate = client.get("/curate/1")
        review = client.get("/review")
    for response in (curate, review):
        assert response.status_code == 200
        assert "Led a team of 25 engineers" in response.text
        assert "Adds detail your evidence doesn" in response.text
        assert "25" in response.text


@pytest.mark.parametrize("route", ["/curate/0", "/review"])
def test_unreadable_support_does_not_block_live_pages(workspace, caplog, route):
    app = _prepare_picked_live_workspace(workspace)
    (workspace / "applications" / SLUG / "support.json").mkdir()

    with TestClient(app) as client:
        response = client.get(route)

    assert response.status_code == 200
    assert "I led the billing migration end to end." in response.text
    assert f"unreadable support.json for slug={SLUG}" in caplog.text


def test_live_review_with_incomplete_picks_does_not_stitch_or_500(workspace):
    # A live user can open /review mid-curation. stitch needs one pick per unit, so when the
    # picks are incomplete we must NOT stitch (it would 500); we show the in-memory lint and
    # the incomplete banner instead, the same calm surface as the fake config.
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
                    Variant("cover_letter.opening#1", "I led the billing migration.", ())
                ],
            ),
            Unit(
                id="resume.northwind.billing.bullet_1",
                kind="resume_bullet",
                label="Bullet 1",
                context="Surface the migration.",
                variants=[
                    Variant(
                        "resume.northwind.billing.bullet_1#1",
                        "- Led the billing platform migration.",
                        (),
                    )
                ],
            ),
        ],
    )
    # Pick only the cover unit, leaving the resume bullet unpicked (incomplete).
    repo.set_pick(SLUG, "cover_letter.opening", "cover_letter.opening#1")
    gen = FakeGenerationPort()
    comp = ScriptCompositionPort(workspace)
    app = create_app(
        repo=repo, gen=gen, run_manager=RunManager(repo=repo, gen=gen, verifier=NoVerificationPort()), live=True, comp=comp,
        finals=FinalDocuments(workspace, SLUG),
    )
    with TestClient(app) as c:
        r = c.get("/review")
        incomplete = c.post("/review/compose", data={}, follow_redirects=False)
    assert r.status_code == 200
    assert incomplete.status_code == 409
    assert "Choose every line" in incomplete.text
    assert "haven’t chosen every line yet" in r.text
    # No stitched documents were written, since stitch was (correctly) not run.
    assert not (workspace / "applications" / SLUG / "cover_letter.md").exists()


def test_live_export_reports_the_written_or_skipped_map(workspace):
    import shutil as _shutil

    app = _prepare_picked_live_workspace(workspace)
    with TestClient(app) as c:
        _compose_live_documents(c)
        r = c.get("/export")
    assert r.status_code == 200
    assert "Exported files" in r.text
    # The reported status matches the real environment: written iff pandoc is installed.
    have_pandoc = _shutil.which("pandoc") is not None
    if have_pandoc:
        assert "written" in r.text
    else:
        assert "skipped" in r.text


def test_live_export_downloads_the_stitched_markdown(workspace):
    app = _prepare_picked_live_workspace(workspace)
    with TestClient(app) as client:
        _compose_live_documents(client)
        page = client.get("/export")
        assert "Plain text from your saved documents." in page.text
        assert 'href="#"' not in page.text
        for filename in ("cover_letter.md", "resume.md"):
            assert f'href="/export/download/{filename}" hx-boost="false" download' in page.text
            response = client.get(f"/export/download/{filename}")
            assert response.status_code == 200
            assert response.content == (workspace / "applications" / SLUG / filename).read_bytes()
            assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'


def test_live_export_without_documents_has_no_download_links(workspace):
    app = _prepare_picked_live_workspace(workspace)
    with TestClient(app) as client:
        page = client.get("/export")
        assert "/export/download/" not in page.text
        assert "No Markdown files available." in page.text
        assert client.get("/export/download/resume.md").status_code == 404


def test_live_export_downloads_written_formats_and_hides_skipped_artifacts(workspace, monkeypatch):
    app = _prepare_picked_live_workspace(workspace)
    app_dir = workspace / "applications" / SLUG

    def export_artifacts(directory, formats):
        (directory / "resume.pdf").write_bytes(b"real-pdf-artifact")
        (directory / "resume.docx").write_bytes(b"older-artifact")
        return {"resume.pdf": "written", "resume.docx": "skipped: no exporter", "cover_letter.pdf": "written"}

    monkeypatch.setattr("app.adapters.composition.export_app_dir", export_artifacts)
    with TestClient(app) as client:
        _compose_live_documents(client)
        page = client.get("/export")
        assert 'href="/export/download/resume.pdf"' in page.text
        assert 'href="/export/download/resume.docx"' not in page.text
        assert 'href="/export/download/cover_letter.pdf"' not in page.text
        response = client.get("/export/download/resume.pdf")
        assert response.content == (app_dir / "resume.pdf").read_bytes()
        assert response.headers["content-type"] == "application/pdf"
        (app_dir / "resume.pdf").write_bytes(b"changed artifact")
        assert client.get("/export/download/resume.pdf").status_code == 404


@pytest.mark.parametrize("filename", ["evidence.md", "metrics.json", "resume.html"])
def test_live_download_rejects_workspace_sources(workspace, filename):
    app = _prepare_picked_live_workspace(workspace)
    assert not FinalDocuments(workspace, SLUG).can_download(filename)
    with TestClient(app) as client:
        assert client.get(f"/export/download/{filename}").status_code == 404


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


def test_live_landing_states_honest_master_resume_source(live_client):
    # The Start screen must tell the truth: reuse the workspace master resume, with no
    # fabricated "last updated"/evidence-count copy and no non-functional upload control.
    client, _ = live_client
    r = client.get("/")
    assert "Reusing master-resume.md from your workspace." in r.text
    assert "2 days ago" not in r.text
    assert "evidence entries" not in r.text
    assert "Upload a different one" not in r.text


def test_live_start_writes_the_pasted_jd_to_the_workspace(workspace):
    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())
    app = create_app(repo=repo, gen=gen, run_manager=manager, live=True)
    with TestClient(app) as c:
        r = c.post("/start", data={"jd": "Widget Wrangler at Globex. Unique-JD-Marker-42."})
    assert r.status_code == 200
    jd_txt = (workspace / "applications" / SLUG / "jd.txt").read_text()
    assert "Unique-JD-Marker-42." in jd_txt


def test_live_start_with_blank_jd_keeps_the_existing_jd(workspace):
    jd_path = workspace / "applications" / SLUG / "jd.txt"
    original = jd_path.read_text()
    repo = FsWorkspaceRepository(workspace)
    gen = FakeGenerationPort()
    manager = RunManager(repo=repo, gen=gen, verifier=NoVerificationPort())
    app = create_app(repo=repo, gen=gen, run_manager=manager, live=True)
    with TestClient(app) as c:
        r = c.post("/start", data={"jd": "   "})  # whitespace-only -> not written
    assert r.status_code == 200
    assert jd_path.read_text() == original
