# ABOUTME: Tests for the async RunManager that orchestrates live generation off the API.
# ABOUTME: Drives the state machine directly under asyncio.run with a FakeGenerationPort + FsRepo.

import asyncio
import shutil
from pathlib import Path

import pytest

from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.domain import OutlineUnit
from app.runs import RunManager

SLUG = "globex-staff-platform"
FIXTURE = Path(__file__).parent / "fixtures" / "workspace"


@pytest.fixture
def workspace(tmp_path):
    dest = tmp_path / "workspace"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_run_reaches_done_and_persists_outputs(workspace):
    repo = FsWorkspaceRepository(workspace)
    manager = RunManager(repo=repo, gen=FakeGenerationPort())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    status = manager.status(SLUG)
    assert status.state == "done"
    assert status.units_total == status.units_done
    assert status.units_total > 0
    assert status.error is None

    app_dir = workspace / "applications" / SLUG
    assert (app_dir / "outline.json").exists()
    assert (app_dir / "variants.md").exists()
    # The persisted variants load back into a hydrated application.
    loaded = repo.load_application(SLUG)
    assert len(loaded.units) == status.units_total


def test_status_for_unstarted_slug_is_idle(workspace):
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort())
    status = manager.status(SLUG)
    assert status.state == "idle"
    assert status.units_done == 0
    assert status.units_total == 0


def test_start_sets_running_synchronously_and_guards_double_start(workspace):
    repo = FsWorkspaceRepository(workspace)
    gate = asyncio.Event()

    class GatedGen(FakeGenerationPort):
        async def outline(self, slug):
            await gate.wait()
            return await super().outline(slug)

    manager = RunManager(repo=repo, gen=GatedGen())

    async def go():
        manager.start(SLUG)
        # Synchronously marked running before the background task does any work.
        assert manager.status(SLUG).state == "running"
        # A second start while running is a no-op (same single task).
        manager.start(SLUG)
        gate.set()
        await manager.join(SLUG)

    asyncio.run(go())
    assert manager.status(SLUG).state == "done"


def test_error_path_sets_state_error_with_message(workspace):
    class BrokenGen(FakeGenerationPort):
        async def outline(self, slug):
            raise RuntimeError("the summoning failed")

    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=BrokenGen())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    status = manager.status(SLUG)
    assert status.state == "error"
    assert "the summoning failed" in status.error


def test_join_on_unstarted_slug_is_a_noop(workspace):
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort())
    asyncio.run(manager.join(SLUG))  # no task; returns immediately
    assert manager.status(SLUG).state == "idle"


def test_progress_advances_per_unit(workspace):
    repo = FsWorkspaceRepository(workspace)
    seen: list[tuple[int, int]] = []

    class CountingGen(FakeGenerationPort):
        async def variants(self, slug, unit: OutlineUnit, n: int = 4):
            result = await super().variants(slug, unit, n)
            seen.append((manager.status(slug).units_done, manager.status(slug).units_total))
            return result

    manager = RunManager(repo=repo, gen=CountingGen())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())
    # Total is fixed once the outline is known; done climbs from 0 upward.
    totals = {t for _, t in seen}
    assert totals == {manager.status(SLUG).units_total}
    assert seen[0][0] == 0


def test_aclose_after_completion_skips_cancel(workspace):
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)
        assert manager.status(SLUG).state == "done"
        await manager.aclose()  # done task: cancel is skipped, the await returns cleanly

    asyncio.run(go())


def test_can_close_cancels_pending_runs(workspace):
    repo = FsWorkspaceRepository(workspace)
    gate = asyncio.Event()

    class GatedGen(FakeGenerationPort):
        async def outline(self, slug):
            await gate.wait()
            return await super().outline(slug)

    manager = RunManager(repo=repo, gen=GatedGen())

    async def go():
        manager.start(SLUG)
        assert manager.status(SLUG).state == "running"
        await manager.aclose()  # cancels the still-gated task cleanly

    asyncio.run(go())
