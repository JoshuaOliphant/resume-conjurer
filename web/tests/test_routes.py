# ABOUTME: Route and flow tests for the Conjurer web UI.
# ABOUTME: Covers every screen renders, the curate flow stores picks, and review reflects them.

import pytest
from fastapi.testclient import TestClient

from app.deps import SESSION_COOKIE, get_application, get_store
from app.main import app
from app.providers.fixtures import EVIDENCE, _variant
from app.selections import InMemorySelectionStore


@pytest.fixture
def client():
    # Inject a fresh store per test through the port's override seam, rather than
    # reaching past the SelectionStore abstraction to reset a module global. This
    # is exactly how a different adapter would be swapped in, so the tests stay
    # honest to the port.
    test_store = InMemorySelectionStore()
    app.dependency_overrides[get_store] = lambda: test_store
    with TestClient(app) as c:
        c.app_store = test_store
        yield c
    app.dependency_overrides.clear()


def picks(client) -> dict[str, str]:
    """The picks stored for this client's session (its cookie identifies it)."""
    return client.app_store.all(client.cookies.get(SESSION_COOKIE))


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


def test_pick_rejects_variant_not_in_unit(client):
    r = client.post("/curate/0", data={"variant_id": "not-a-real-id"}, follow_redirects=False)
    assert r.status_code == 422
    assert "cover-open" not in picks(client)  # nothing stored on rejection


def test_pick_out_of_range_idx_returns_404(client):
    r = client.post("/curate/999", data={"variant_id": "cover-open-1"}, follow_redirects=False)
    assert r.status_code == 404
    assert not picks(client)


def test_pick_stores_selection_and_advances(client):
    r = client.post("/curate/0", data={"variant_id": "cover-open-2"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/curate/1"
    assert picks(client)["cover-open"] == "cover-open-2"


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


def test_selections_are_scoped_per_session(client):
    # Two browsers (separate cookie jars) must not share picks.
    client.post("/curate/0", data={"variant_id": "cover-open-4"}, follow_redirects=False)
    with TestClient(app) as other:
        r = other.get("/review")
        # The second session never picked, so it sees the first variant, not "cover-open-4".
        assert "Forty seconds to two." not in r.text
    # And the first session still has its pick.
    assert picks(client)["cover-open"] == "cover-open-4"


def test_blank_session_cookie_mints_a_fresh_session(client):
    # A cleared/proxy-stripped cookie arrives as "" — it must mint a fresh id, not
    # collapse every such client into one shared "" pick bucket.
    r = client.post(
        "/curate/0",
        data={"variant_id": "cover-open-1"},
        headers={"Cookie": f"{SESSION_COOKIE}="},
        follow_redirects=False,
    )
    assert r.status_code == 303
    new_sid = r.cookies.get(SESSION_COOKIE)
    assert new_sid  # a real, non-empty id was issued
    assert client.app_store.all("") == {}  # nothing stored under the empty key
    assert client.app_store.all(new_sid)["cover-open"] == "cover-open-1"


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
    # Integrity sweep: every trace shown is a real Evidence object from the pool.
    for unit in get_application().units:
        for v in unit.variants:
            assert all(e in EVIDENCE.values() for e in v.evidence)


def test_variant_builder_rejects_unknown_evidence_id():
    # The provider's builder owns id->Evidence resolution and rejects bad citations.
    with pytest.raises(ValueError, match="unknown evidence"):
        _variant("bad", "x", "does-not-exist")
    # sanity: a real id constructs fine and resolves to the pooled Evidence
    real_id = next(iter(EVIDENCE))
    v = _variant("ok", "x", real_id)
    assert v.evidence == (EVIDENCE[real_id],)


def test_export_renders(client):
    r = client.get("/export")
    assert r.status_code == 200
    assert "pandoc" in r.text


def test_reset_clears_selections(client):
    client.post("/curate/0", data={"variant_id": "cover-open-1"}, follow_redirects=False)
    assert picks(client)
    r = client.post("/reset", follow_redirects=False)
    assert r.status_code == 303
    assert not picks(client)
