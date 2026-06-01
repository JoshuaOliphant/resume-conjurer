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


def test_run_aggregates_metrics_and_persists_them(workspace):
    repo = FsWorkspaceRepository(workspace)
    manager = RunManager(repo=repo, gen=FakeGenerationPort())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    metrics = manager.metrics(SLUG)
    assert metrics is not None
    assert metrics.slug == SLUG
    # One "outline" step plus one StepMetrics per generated unit.
    names = [s.name for s in metrics.steps]
    assert names[0] == "outline"
    units_total = manager.status(SLUG).units_total
    assert len(metrics.steps) == units_total + 1
    assert metrics.line_count == units_total
    # Totals aggregate across every step.
    assert metrics.total_cost_usd > 0
    assert metrics.total_input_tokens > 0
    # The warm-cache variant calls give a non-trivial variant cache hit rate.
    assert metrics.variant_cache_hit_pct > 0

    # Metrics were persisted to the workspace and load back equal.
    assert (workspace / "applications" / SLUG / "metrics.json").exists()
    assert repo.load_metrics(SLUG) == metrics


def test_metrics_for_unstarted_slug_is_none(workspace):
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort())
    assert manager.metrics(SLUG) is None


def test_metrics_keep_partial_steps_on_error(workspace):
    # A run that fails mid-loop still records metrics for the steps that completed before the
    # failure (best-effort), so the surfaced figures reflect how far the summoning got.
    class RaiseOnSecondUnit(FakeGenerationPort):
        calls = 0

        async def variants(self, slug, unit: OutlineUnit, n: int = 4):
            type(self).calls += 1
            if type(self).calls == 2:
                raise RuntimeError("the summoning failed mid-flight")
            return await super().variants(slug, unit, n)

    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=RaiseOnSecondUnit())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    assert manager.status(SLUG).state == "error"
    metrics = manager.metrics(SLUG)
    assert metrics is not None
    # outline + the one variant step that completed before the second raised.
    assert [s.name for s in metrics.steps][0] == "outline"
    assert metrics.line_count == 1


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


def test_zero_variant_unit_fails_the_run_honestly(workspace):
    # A unit that comes back with no variants is a real failure: the run must end in
    # state="error" with a useful message, not silently persist an empty unit.
    empty_unit_id: list[str] = []

    class EmptyOnSecondUnit(FakeGenerationPort):
        calls = 0

        async def variants(self, slug, unit: OutlineUnit, n: int = 4):
            type(self).calls += 1
            if type(self).calls == 2:
                empty_unit_id.append(unit.unit_id)
                return []
            return await super().variants(slug, unit, n)

    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=EmptyOnSecondUnit())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    status = manager.status(SLUG)
    assert status.state == "error"
    assert "No variants generated for" in status.error
    assert status.error.endswith(empty_unit_id[0])


def test_error_mid_loop_keeps_partial_progress_snapshot(workspace):
    # If variants() raises partway through, the error snapshot must keep the progress
    # counts the run reached (it failed after summoning some lines), not reset to zero.
    class RaiseOnSecondUnit(FakeGenerationPort):
        calls = 0

        async def variants(self, slug, unit: OutlineUnit, n: int = 4):
            type(self).calls += 1
            if type(self).calls == 2:
                raise RuntimeError("the summoning failed mid-flight")
            return await super().variants(slug, unit, n)

    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=RaiseOnSecondUnit())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    status = manager.status(SLUG)
    assert status.state == "error"
    assert "the summoning failed mid-flight" in status.error
    # One unit completed before the second raised; the total is the full outline.
    assert status.units_done == 1
    assert status.units_total == len(manager._gen._outline_units)


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
