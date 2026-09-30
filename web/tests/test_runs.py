# ABOUTME: Tests for the async RunManager that orchestrates live generation off the API.
# ABOUTME: Drives the state machine directly under asyncio.run with a FakeGenerationPort + FsRepo.

import asyncio
import shutil
from pathlib import Path

import pytest

from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.verification_fake import FakeVerificationPort, NoVerificationPort
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.domain import OutlineUnit, Support
from app.runs import RunManager

import verify  # on sys.path once app.adapters.workspace_fs is imported

SLUG = "globex-staff-platform"
FIXTURE = Path(__file__).parent / "fixtures" / "workspace"


@pytest.fixture
def workspace(tmp_path):
    dest = tmp_path / "workspace"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_run_reaches_done_and_persists_outputs(workspace):
    repo = FsWorkspaceRepository(workspace)
    manager = RunManager(repo=repo, gen=FakeGenerationPort(), verifier=NoVerificationPort())

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
    manager = RunManager(repo=repo, gen=FakeGenerationPort(), verifier=NoVerificationPort())

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
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort(), verifier=NoVerificationPort())
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

    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=RaiseOnSecondUnit(), verifier=NoVerificationPort())

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
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort(), verifier=NoVerificationPort())
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

    manager = RunManager(repo=repo, gen=GatedGen(), verifier=NoVerificationPort())

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

    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=BrokenGen(), verifier=NoVerificationPort())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    status = manager.status(SLUG)
    assert status.state == "error"
    assert status.error is not None
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

    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=EmptyOnSecondUnit(), verifier=NoVerificationPort())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    status = manager.status(SLUG)
    assert status.state == "error"
    assert status.error is not None
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

    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=RaiseOnSecondUnit(), verifier=NoVerificationPort())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    status = manager.status(SLUG)
    assert status.state == "error"
    assert status.error is not None
    assert "the summoning failed mid-flight" in status.error
    # One unit completed before the second raised; the total is the full outline.
    assert status.units_done == 1
    gen = manager._gen
    assert isinstance(gen, FakeGenerationPort)
    assert status.units_total == len(gen._outline_units)


def test_join_on_unstarted_slug_is_a_noop(workspace):
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort(), verifier=NoVerificationPort())
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

    manager = RunManager(repo=repo, gen=CountingGen(), verifier=NoVerificationPort())

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())
    # Total is fixed once the outline is known; done climbs from 0 upward.
    totals = {t for _, t in seen}
    assert totals == {manager.status(SLUG).units_total}
    assert seen[0][0] == 0


def test_aclose_after_completion_skips_cancel_and_closes_the_verifier(workspace):
    class ClosingVerifier(FakeVerificationPort):
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    verifier = ClosingVerifier()
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort(), verifier=verifier)

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)
        assert manager.status(SLUG).state == "done"
        await manager.aclose()  # done task: cancel is skipped, the await returns cleanly

    asyncio.run(go())
    assert verifier.closed


FLAGGED = Support(
    verdict="adds_detail", note="Adds detail your evidence doesn't state: 12", unsourced_numbers=("12",)
)
TRACED = Support(verdict="traced")


def test_run_verifies_each_unit_after_its_variants_and_saves_support_after_variants(workspace):
    events: list[tuple[str, str]] = []
    pools: list[set[str]] = []

    class LoggingGen(FakeGenerationPort):
        async def variants(self, slug, unit: OutlineUnit, n: int = 4):
            events.append(("variants", unit.unit_id))
            return await super().variants(slug, unit, n)

    class LoggingVerifier(FakeVerificationPort):
        async def verify(self, unit, pool):
            events.append(("verify", unit.id))
            pools.append(set(pool))
            return await super().verify(unit, pool)

    class LoggingRepo(FsWorkspaceRepository):
        def save_variants(self, slug, units):
            events.append(("save_variants", slug))
            super().save_variants(slug, units)

        def save_support(self, slug, support):
            events.append(("save_support", slug))
            super().save_support(slug, support)

    scripted = {"cover_letter.opening#1": FLAGGED, "resume.fixture.bullet_1#2": TRACED}
    repo = LoggingRepo(workspace)
    manager = RunManager(repo=repo, gen=LoggingGen(), verifier=LoggingVerifier(scripted))

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    asyncio.run(go())

    assert manager.status(SLUG).state == "done"
    unit_ids = [unit_id for step, unit_id in events if step == "variants"]
    per_unit = [event for unit_id in unit_ids for event in (("variants", unit_id), ("verify", unit_id))]
    assert events == per_unit + [("save_variants", SLUG), ("save_support", SLUG)]
    assert pools == [set(repo.load_inputs(SLUG).evidence_pool)] * len(unit_ids)
    assert repo.load_support(SLUG) == scripted


def test_failing_verifier_marks_its_unit_unchecked_and_the_run_still_finishes(workspace, caplog):
    class FailsOnOpening(FakeVerificationPort):
        async def verify(self, unit, pool):
            if unit.id == "cover_letter.opening":
                raise TimeoutError("jev timed out")
            return await super().verify(unit, pool)

    repo = FsWorkspaceRepository(workspace)
    verifier = FailsOnOpening({"resume.fixture.bullet_1#1": TRACED})
    manager = RunManager(repo=repo, gen=FakeGenerationPort(), verifier=verifier)

    async def go():
        manager.start(SLUG)
        await manager.join(SLUG)

    with caplog.at_level("WARNING"):
        asyncio.run(go())

    assert manager.status(SLUG).state == "done"
    [failure] = [r for r in caplog.records if r.levelname == "WARNING"]
    assert SLUG in failure.getMessage()
    assert "cover_letter.opening" in failure.getMessage()
    assert "jev timed out" in failure.getMessage()

    units = {unit.id: unit for unit in repo.load_application(SLUG).units}
    opening = units["cover_letter.opening"].variants
    assert len(opening) == 4
    for variant in opening:
        # Attached on load, so its fingerprint matches the variant as saved to variants.md.
        assert variant.support is not None
        assert (variant.support.verdict, variant.support.note) == ("unchecked", verify.NOTES["unchecked"])
    assert repo.load_support(SLUG)["resume.fixture.bullet_1#1"] == TRACED


def test_log_task_exception_logs_a_real_uncaught_exception(workspace, caplog):
    # _run catches every exception it can raise today, so the done-callback's "real
    # exception" branch is unreachable through the normal start()/_run() path — this is
    # exactly the defense-in-depth the callback exists for if that invariant ever breaks.
    # Exercise it directly rather than excluding the line from coverage.
    manager = RunManager(repo=FsWorkspaceRepository(workspace), gen=FakeGenerationPort(), verifier=NoVerificationPort())

    async def boom():
        raise RuntimeError("a future bug broke _run's exception safety")

    async def go():
        task = asyncio.create_task(boom())
        with pytest.raises(RuntimeError):
            await task
        manager._log_task_exception(task)

    with caplog.at_level("ERROR"):
        asyncio.run(go())

    assert "run task raised uncaught" in caplog.text


def test_can_close_cancels_pending_runs(workspace):
    repo = FsWorkspaceRepository(workspace)
    gate = asyncio.Event()

    class GatedGen(FakeGenerationPort):
        async def outline(self, slug):
            await gate.wait()
            return await super().outline(slug)

    manager = RunManager(repo=repo, gen=GatedGen(), verifier=NoVerificationPort())

    async def go():
        manager.start(SLUG)
        assert manager.status(SLUG).state == "running"
        await manager.aclose()  # cancels the still-gated task cleanly

    asyncio.run(go())


def test_cancel_mid_variants_loop_leaves_a_running_snapshot_not_an_error(workspace):
    # Cancellation partway through the per-unit loop (not just mid-outline) must leave the
    # run's last snapshot as-is: asyncio.CancelledError is a BaseException in modern Python,
    # so _run's `except Exception` must NOT catch it and record state="error" — that would
    # misreport a clean shutdown as a generation failure.
    repo = FsWorkspaceRepository(workspace)
    gate = asyncio.Event()

    class GatedOnSecondUnit(FakeGenerationPort):
        calls = 0

        async def variants(self, slug, unit: OutlineUnit, n: int = 4):
            type(self).calls += 1
            if type(self).calls == 2:
                await gate.wait()
            return await super().variants(slug, unit, n)

    manager = RunManager(repo=repo, gen=GatedOnSecondUnit(), verifier=NoVerificationPort())

    async def go():
        manager.start(SLUG)
        while manager.status(SLUG).units_done < 1:
            await asyncio.sleep(0)
        assert manager.status(SLUG).state == "running"
        await manager.aclose()  # cancels the task gated inside the second unit's variants()

    asyncio.run(go())

    status = manager.status(SLUG)
    assert status.state == "running"  # not "error": cancellation isn't a generation failure
    assert status.units_done == 1


def test_concurrent_runs_across_slugs_stay_isolated(workspace):
    # Two slugs racing through RunManager must not share state: one slug finishing (or
    # progressing) must not be visible through the other slug's status/metrics.
    repo = FsWorkspaceRepository(workspace)
    other_slug = "other-app"
    shutil.copytree(workspace / "applications" / SLUG, workspace / "applications" / other_slug)
    gate_a = asyncio.Event()
    gate_b = asyncio.Event()

    class GatedGen(FakeGenerationPort):
        async def outline(self, slug):
            await (gate_a if slug == SLUG else gate_b).wait()
            return await super().outline(slug)

    manager = RunManager(repo=repo, gen=GatedGen(), verifier=NoVerificationPort())

    async def go():
        manager.start(SLUG)
        manager.start(other_slug)
        # Both in flight, neither has reached the outline yet.
        assert manager.status(SLUG).state == "running"
        assert manager.status(other_slug).state == "running"
        assert manager.status(SLUG).units_total == 0
        assert manager.status(other_slug).units_total == 0

        # Release only other_slug; it must run to completion while SLUG stays gated and
        # untouched by other_slug's progress.
        gate_b.set()
        await manager.join(other_slug)
        assert manager.status(other_slug).state == "done"
        assert manager.status(SLUG).state == "running"
        assert manager.status(SLUG).units_total == 0

        gate_a.set()
        await manager.join(SLUG)

    asyncio.run(go())

    assert manager.status(SLUG).state == "done"
    assert manager.status(other_slug).state == "done"
    metrics_a = manager.metrics(SLUG)
    metrics_b = manager.metrics(other_slug)
    assert metrics_a is not None and metrics_a.slug == SLUG
    assert metrics_b is not None and metrics_b.slug == other_slug
    assert (workspace / "applications" / SLUG / "outline.json").exists()
    assert (workspace / "applications" / other_slug / "outline.json").exists()
