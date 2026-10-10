# ABOUTME: Tests for the in-memory FakeWorkspaceRepository used by the default (offline) config.
# ABOUTME: Conformance to the port, fixture hydration, and the pick round-trip via the in-memory store.

from app.adapters.scripts_path import ensure_scripts_on_path
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.data import get_application
from app.generation_status import UnitGenerationStatus
from app.ports import WorkspaceRepository

ensure_scripts_on_path()

import verify  # noqa: E402


def test_fake_repository_conforms_to_port():
    assert isinstance(FakeWorkspaceRepository(), WorkspaceRepository)


def test_load_application_returns_the_fixture_app():
    repo = FakeWorkspaceRepository()
    app_data = repo.load_application("globex-staff-platform")
    assert app_data == get_application()
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


def test_load_support_serves_the_fixture_overreaches():
    support = FakeWorkspaceRepository().load_support("globex-staff-platform")
    assert set(support) == {"cover-open-1", "bullet-kubernetes-1"}
    assert {s.verdict for s in support.values()} == {"adds_detail"}
    assert all(s.note == verify.note_for("adds_detail", []) for s in support.values())


def test_targeted_write_preserves_other_picks_and_fixture():
    repo = FakeWorkspaceRepository()
    slug = "globex-staff-platform"
    first, second = repo.load_application(slug).units[:2]
    repo.set_pick(slug, second.id, second.variants[0].id)
    repo.save_unit_variants(slug, first)
    assert repo.get_picks(slug) == {second.id: second.variants[0].id}
    assert repo.load_application(slug).units[0] == first
    assert repo.load_application(slug).units[1] == second


def test_saved_progress_is_isolated_from_the_callers_objects():
    repo = FakeWorkspaceRepository()
    assert repo.load_generation_status("app") is None
    states = {"u": UnitGenerationStatus("u", "failed")}
    repo.save_generation_status("app", states)
    states["u"].state = "succeeded"
    loaded = repo.load_generation_status("app")
    assert loaded is not None
    assert loaded["u"].state == "failed"
    loaded["u"].state = "pending"
    saved = repo.load_generation_status("app")
    assert saved is not None and saved["u"].state == "failed"
