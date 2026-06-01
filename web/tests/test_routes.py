# ABOUTME: Route and flow tests for the Conjurer web UI.
# ABOUTME: Covers every screen renders, the curate flow stores picks, and review reflects them.

import pytest
from fastapi.testclient import TestClient

from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.data import EVIDENCE, _v, get_application
from app.main import SLUG, create_app
from app.runs import RunManager


@pytest.fixture
def repo():
    return FakeWorkspaceRepository()


@pytest.fixture
def client(repo):
    gen = FakeGenerationPort()
    app = create_app(repo=repo, gen=gen, run_manager=RunManager(repo=repo, gen=gen), live=False)
    with TestClient(app) as c:
        yield c


def test_entry_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Tailor your resume" in r.text
    assert "Staff Platform Engineer" in r.text


def test_start_redirects_to_outline(client):
    r = client.post("/start", data={"source": "reuse", "jd": "x"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/outline"


def test_outline_lists_units_and_frame(client):
    r = client.get("/outline")
    assert r.status_code == 200
    assert "Frame · Scale" in r.text
    for unit in get_application().units:
        assert unit.label in r.text


def test_curate_start_redirects_to_first_unit(client):
    r = client.get("/curate", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/curate/0"


def test_curate_renders_four_variants_with_evidence(client):
    r = client.get("/curate/0")
    assert r.status_code == 200
    assert "Line 1 of" in r.text
    assert r.text.count('name="variant_id"') == 4
    assert "Evidence" in r.text


def test_curate_shows_limited_evidence_note(client):
    units = get_application().units
    idx = next(i for i, u in enumerate(units) if u.grounding_note)
    r = client.get(f"/curate/{idx}")
    assert "Limited evidence" in r.text


def test_curate_out_of_range_goes_to_review(client):
    r = client.get("/curate/999", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/review"


def test_pick_rejects_variant_not_in_unit(client, repo):
    r = client.post("/curate/0", data={"variant_id": "not-a-real-id"}, follow_redirects=False)
    assert r.status_code == 422
    assert "cover-open" not in repo.get_picks(SLUG)  # nothing stored on rejection


def test_pick_out_of_range_idx_returns_404(client, repo):
    r = client.post("/curate/999", data={"variant_id": "cover-open-1"}, follow_redirects=False)
    assert r.status_code == 404
    assert repo.get_picks(SLUG) == {}


def test_pick_stores_selection_and_advances(client, repo):
    r = client.post("/curate/0", data={"variant_id": "cover-open-2"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/curate/1"
    assert repo.get_picks(SLUG)["cover-open"] == "cover-open-2"


def test_last_pick_advances_to_review(client):
    units = get_application().units
    last = len(units) - 1
    last_unit = units[last]
    r = client.post(
        f"/curate/{last}",
        data={"variant_id": last_unit.variants[0].id},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/review"


def test_review_reflects_chosen_variant(client):
    client.post("/curate/0", data={"variant_id": "cover-open-4"}, follow_redirects=False)
    r = client.get("/review")
    assert r.status_code == 200
    assert "Forty seconds to two." in r.text  # text of cover-open-4
    assert "Style check" in r.text


def test_review_incomplete_banner_when_not_all_picked(client):
    r = client.get("/review")
    assert "haven’t chosen every line yet" in r.text


def test_review_complete_hides_incomplete_banner(client):
    units = get_application().units
    for idx, unit in enumerate(units):
        client.post(
            f"/curate/{idx}",
            data={"variant_id": unit.variants[0].id},
            follow_redirects=False,
        )
    r = client.get("/review")
    assert "haven’t chosen every line yet" not in r.text


def test_review_unselected_unit_shows_first_variant(client):
    # Pin the documented fallback: an uncurated unit renders its variant[0].
    units = get_application().units
    bullet = next(u for u in units if u.kind == "resume_bullet")
    r = client.get("/review")  # nothing selected
    assert bullet.variants[0].text in r.text


def test_review_word_count_is_computed_not_hardcoded(client):
    # The old fixture hardcoded "312 words"; the count must reflect the real text.
    units = get_application().units
    cover = [u for u in units if u.kind == "cover_paragraph"]
    expected = sum(len(u.variants[0].text.split()) for u in cover)
    r = client.get("/review")
    assert "312 words" not in r.text
    assert f"{expected} words." in r.text


def test_every_variant_resolves_its_evidence(client):
    # Integrity sweep: every variant carries resolved evidence drawn from the pool.
    pool = get_application().evidence
    for unit in get_application().units:
        for v in unit.variants:
            traces = v.evidence()
            assert traces == list(v.evidence_items)
            assert all(pool.get(e.id) is e for e in traces)


def test_variant_builder_rejects_unknown_evidence_id():
    # The trust invariant now lives in the adapter that resolves ids, not the type.
    with pytest.raises(ValueError, match="unknown evidence"):
        _v("bad", "x", "does-not-exist")
    # sanity: a real id resolves fine
    real_id = next(iter(EVIDENCE))
    assert _v("ok", "x", real_id).evidence_items[0].id == real_id


def test_review_skips_zero_variant_unit_without_500(repo):
    # A unit that arrives with no variants must not crash review (it can't be indexed);
    # it is silently skipped, and the other units still render.
    from app.domain import Application, Frame, Unit, Variant

    empty_unit = Unit(
        id="resume.empty.bullet_1",
        kind="resume_bullet",
        label="Empty bullet",
        context="No variants were generated for this line.",
        variants=[],
    )
    full_unit = Unit(
        id="resume.full.bullet_1",
        kind="resume_bullet",
        label="Full bullet",
        context="A normal line.",
        variants=[Variant(id="resume.full.bullet_1#1", text="A real bullet.", evidence_items=())],
    )
    app_data = Application(
        slug=SLUG,
        company="Globex",
        role="Staff Platform Engineer",
        jd_excerpt="x",
        frame=Frame(name="Scale", rationale="why"),
        units=[empty_unit, full_unit],
    )

    class _StubRepo(FakeWorkspaceRepository):
        def load_application(self, slug: str) -> Application:
            return app_data

    stub = _StubRepo()
    gen = FakeGenerationPort()
    app = create_app(repo=stub, gen=gen, run_manager=RunManager(repo=stub, gen=gen), live=False)
    with TestClient(app) as c:
        r = c.get("/review")
    assert r.status_code == 200
    assert "A real bullet." in r.text


def test_curate_renders_zero_variant_unit_without_500(repo):
    # A zero-variant unit renders an empty radiogroup rather than crashing the curate screen.
    from app.domain import Application, Frame, Unit

    empty_unit = Unit(
        id="resume.empty.bullet_1",
        kind="resume_bullet",
        label="Empty bullet",
        context="No variants were generated for this line.",
        variants=[],
    )
    app_data = Application(
        slug=SLUG,
        company="Globex",
        role="Staff Platform Engineer",
        jd_excerpt="x",
        frame=Frame(name="Scale", rationale="why"),
        units=[empty_unit],
    )

    class _StubRepo(FakeWorkspaceRepository):
        def load_application(self, slug: str) -> Application:
            return app_data

    stub = _StubRepo()
    gen = FakeGenerationPort()
    app = create_app(repo=stub, gen=gen, run_manager=RunManager(repo=stub, gen=gen), live=False)
    with TestClient(app) as c:
        r = c.get("/curate/0")
    assert r.status_code == 200
    assert "Empty bullet" in r.text


def test_export_renders(client):
    r = client.get("/export")
    assert r.status_code == 200
    assert "pandoc" in r.text


def test_reset_clears_selections(client, repo):
    client.post("/curate/0", data={"variant_id": "cover-open-1"}, follow_redirects=False)
    assert repo.get_picks(SLUG)
    r = client.post("/reset", follow_redirects=False)
    assert r.status_code == 303
    assert repo.get_picks(SLUG) == {}


def test_entry_is_honest_and_has_no_dead_upload(client):
    # Fake config: the Start screen states the bundled sample, with no fabricated
    # "last updated"/count copy and no non-functional upload affordance.
    r = client.get("/")
    assert "Using the bundled sample resume." in r.text
    assert "2 days ago" not in r.text
    assert "7 evidence entries" not in r.text
    assert "Upload a different one" not in r.text
