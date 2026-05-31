# ABOUTME: Route and flow tests for the Conjurer web UI.
# ABOUTME: Covers every screen renders, the curate flow stores picks, and review reflects them.

import pytest
from fastapi.testclient import TestClient

from app.data import get_application
from app.main import SELECTIONS, app


@pytest.fixture
def client():
    SELECTIONS.clear()
    with TestClient(app) as c:
        yield c
    SELECTIONS.clear()


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


def test_pick_stores_selection_and_advances(client):
    r = client.post("/curate/0", data={"variant_id": "cover-open-2"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/curate/1"
    assert SELECTIONS["cover-open"] == "cover-open-2"


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


def test_export_renders(client):
    r = client.get("/export")
    assert r.status_code == 200
    assert "pandoc" in r.text


def test_reset_clears_selections(client):
    client.post("/curate/0", data={"variant_id": "cover-open-1"}, follow_redirects=False)
    assert SELECTIONS
    r = client.post("/reset", follow_redirects=False)
    assert r.status_code == 303
    assert not SELECTIONS
