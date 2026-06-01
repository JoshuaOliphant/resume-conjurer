# ABOUTME: Tests for the in-memory FakeWorkspaceRepository used by the default (offline) config.
# ABOUTME: Conformance to the port, fixture hydration, and the pick round-trip via the in-memory store.

from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.data import get_application
from app.ports import WorkspaceRepository


def test_fake_repository_conforms_to_port():
    assert isinstance(FakeWorkspaceRepository(), WorkspaceRepository)


def test_load_application_returns_the_fixture_app():
    repo = FakeWorkspaceRepository()
    app_data = repo.load_application("globex-staff-platform")
    assert app_data is get_application()
    assert app_data.company == "Globex"


def test_picks_round_trip_through_the_in_memory_store():
    repo = FakeWorkspaceRepository()
    slug = "globex-staff-platform"
    assert repo.get_picks(slug) == {}
    repo.set_pick(slug, "cover-open", "cover-open-2")
    repo.set_pick(slug, "bullet-migration", "bullet-migration-1")
    assert repo.get_picks(slug) == {
        "cover-open": "cover-open-2",
        "bullet-migration": "bullet-migration-1",
    }
    # Setting a unit again replaces its single pick.
    repo.set_pick(slug, "cover-open", "cover-open-4")
    assert repo.get_picks(slug)["cover-open"] == "cover-open-4"


def test_picks_are_scoped_per_slug():
    repo = FakeWorkspaceRepository()
    repo.set_pick("a", "u1", "v1")
    assert repo.get_picks("b") == {}


def test_clear_drops_a_slugs_picks():
    repo = FakeWorkspaceRepository()
    repo.set_pick("a", "u1", "v1")
    repo.clear("a")
    assert repo.get_picks("a") == {}
