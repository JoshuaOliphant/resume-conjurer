# ABOUTME: Async RunManager — orchestrates a live generation run and tracks per-unit progress.
# ABOUTME: Kicks outline + variants off as a background task; the UI polls status() while it works.

"""Generate complete unit drafts, retain partial progress, and retry failed units."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import RLock

from app.domain import Evidence, Support, Unit, label_for_unit_id
from app.generation_status import (
    GenerationStatusConflict,
    UnitGenerationStatus,
    validate_unit_variants,
)
from app.metrics import CallMetrics, RunMetrics, StepMetrics
from app.ports import GenerationPort, VerificationPort, WorkspaceRepository

logger = logging.getLogger(__name__)

RunState = str


@dataclass
class RunStatus:
    """A snapshot of one slug's run, safe to render in the progress partial."""

    state: RunState = "idle"
    units_done: int = 0
    units_total: int = 0
    error: str | None = None
    units: dict[str, UnitGenerationStatus] = field(default_factory=dict)


class RunManager:
    """Sequences outline + variant generation for a slug, tracking progress."""

    def __init__(
        self, repo: WorkspaceRepository, gen: GenerationPort, verifier: VerificationPort, timeout_s: float = 300
    ) -> None:
        self._lock = RLock()
        self._timeout_s = timeout_s
        self._repo = repo
        self._gen = gen
        self._verifier = verifier
        self._status: dict[str, RunStatus] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._metrics: dict[str, RunMetrics] = {}
        self._support: dict[str, dict[str, Support]] = {}
        self._generated: dict[str, dict[str, Unit]] = {}

    def status(self, slug: str) -> RunStatus:
        with self._lock:
            if slug in self._status:
                return self._status[slug]
            try:
                outline = self._repo.load_outline(slug)
            except NotImplementedError:
                return RunStatus()
            if outline is None:
                return RunStatus()
            application = self._repo.load_application(slug)
            error = None
            conflict = False
            try:
                saved = self._repo.load_generation_status(slug)
            except (OSError, ValueError) as exc:
                logger.warning("could not recover generation progress for slug=%s: %s", slug, type(exc).__name__)
                saved = None
                conflict = isinstance(exc, GenerationStatusConflict)
                error = "Could not recover generation progress. Check workspace storage."
            units = {unit.id: unit for unit in application.units}
            statuses = {}
            for ou in outline.units:
                stored = saved.get(ou.unit_id) if saved else None
                variants = units[ou.unit_id].variants
                complete = not conflict and len(variants) == 4 and all(v.text.strip() for v in variants) and (stored is None or stored.state != "pending")
                statuses[ou.unit_id] = UnitGenerationStatus(ou.unit_id, "succeeded" if complete else "failed", None if complete else "Generation was interrupted or incomplete. Retry this line.")
            status = RunStatus(units_total=len(statuses), units_done=sum(u.state == "succeeded" for u in statuses.values()), units=statuses, error=error)
            status.state = "error" if error else ("done" if status.units_done == status.units_total else "partial")
            self._status[slug] = status
            self._metrics[slug] = self._repo.load_metrics(slug) or RunMetrics(slug=slug, steps=[])
            self._support[slug] = self._repo.load_support(slug)
            self._generated[slug] = {key: units[key] for key, state in statuses.items() if state.state == "succeeded"}
            return status

    def _persist_progress(self, slug: str) -> None:
        self._repo.save_generation_status(slug, self._status[slug].units)

    def metrics(self, slug: str) -> RunMetrics | None:
        return self._metrics.get(slug)

    def _record_step(self, run_metrics: RunMetrics, name: str, started: float) -> None:
        """Append one step's metrics: its wall time plus the generation port's last call.

        Called after each outline()/variants() so partial progress is captured even when a
        later step fails (the RunMetrics object is already visible via metrics()).
        """
        wall_ms = int((time.monotonic() - started) * 1000)
        call = self._gen.last_call or CallMetrics.zero()
        run_metrics.add_step(StepMetrics(name=name, wall_ms=wall_ms, call=call))

    def start(self, slug: str) -> None:
        """Launch a background run for ``slug`` unless one is already running."""
        with self._lock:
            if self.status(slug).state == "running":
                return
            self._status[slug] = RunStatus(state="running")
            task = asyncio.create_task(self._run(slug))
            task.add_done_callback(self._log_task_exception)
            self._tasks[slug] = task

    def _log_task_exception(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("run task raised uncaught: %r", exc, exc_info=exc)

    async def join(self, slug: str) -> None:
        """Await the background task for ``slug`` (a no-op if none is in flight)."""
        task = self._tasks.get(slug)
        if task is not None:
            await task

    async def _check_claims(
        self, slug: str, unit: Unit, pool: Mapping[str, Evidence]
    ) -> dict[str, Support]:
        """The unit's support verdicts; every variant reads ``unchecked`` when the check fails."""
        try:
            return await self._verifier.verify(unit, pool)
        except Exception as exc:
            logger.warning(
                "claim check failed for slug=%s unit=%s: %r", slug, unit.id, exc
            )
            return {variant.id: Support(verdict="unchecked") for variant in unit.variants}

    def retry_unit(self, slug: str, unit_id: str) -> RunStatus:
        with self._lock:
            status = self.status(slug)
            if status.state == "running":
                return status
            target = status.units.get(unit_id)
            if target is None or target.state != "failed":
                raise ValueError("This unit is not available for retry.")
            outline = self._repo.load_outline(slug)
            if outline is None:
                raise ValueError("No outline available.")
            unit = next(u for u in outline.units if u.unit_id == unit_id)
            status.state = "running"
            status.error = None
            target.state = "generating"
            target.error = None
            try:
                self._persist_progress(slug)
            except OSError:
                self._fail_storage(slug)
                return status
            task = asyncio.create_task(self._retry(slug, unit))
            task.add_done_callback(self._log_task_exception)
            self._tasks[slug] = task
            return status

    async def _generate_unit(self, slug, ou, run_metrics, pool):
        target = self._status[slug].units[ou.unit_id]
        target.state = "generating"
        self._persist_progress(slug)
        started = time.monotonic()
        try:
            variants = await asyncio.wait_for(self._gen.variants(slug, ou), self._timeout_s)
            validate_unit_variants(variants)
        except Exception:
            logger.exception("unit generation failed for slug=%s unit=%s", slug, ou.unit_id)
            target.state = "failed"
            target.error = "Could not generate four usable variants. Retry this line."
            try:
                await self._gen.aclose()
            except Exception:
                logger.exception("generation client cleanup failed for slug=%s", slug)
            self._persist_progress(slug)
            return
        finally:
            self._record_step(run_metrics, ou.unit_id, started)
        unit = Unit(id=ou.unit_id, kind=ou.kind, label=label_for_unit_id(ou.unit_id), context=ou.description, variants=variants)
        self._repo.save_unit_variants(slug, unit)
        self._generated.setdefault(slug, {})[unit.id] = unit
        target.state = "succeeded"
        target.error = None
        self._persist_progress(slug)
        self._status[slug].units_done = sum(u.state == "succeeded" for u in self._status[slug].units.values())
        support = self._support.setdefault(slug, {})
        support.update(await self._check_claims(slug, unit, pool))
        try:
            self._repo.save_support(slug, support, list(self._generated[slug].values()), pool)
        except OSError as exc:
            logger.warning("could not save support.json for slug=%s: %r", slug, exc)

    def _complete(self, slug):
        status = self._status[slug]
        status.state = "done" if all(u.state == "succeeded" for u in status.units.values()) else "partial"
        self._repo.save_metrics(slug, self._metrics[slug])
        self._persist_progress(slug)

    def _fail_storage(self, slug):
        logger.exception("generation run failed for slug=%s", slug)
        status = self._status[slug]
        status.state = "error"
        status.error = "Could not save generation progress. Check workspace storage before retrying."
        for unit in status.units.values():
            if unit.state in ("pending", "generating"):
                unit.state = "failed"
                unit.error = status.error

    async def _run(self, slug: str) -> None:
        run_metrics = RunMetrics(slug=slug, steps=[])
        self._metrics[slug] = run_metrics
        self._support[slug] = {}
        self._generated[slug] = {}
        started = time.monotonic()
        try:
            outline = await self._gen.outline(slug)
        except Exception:
            logger.exception("outline generation failed for slug=%s", slug)
            self._status[slug].state = "error"
            self._status[slug].error = "Could not generate the outline. Try starting again."
            return
        self._record_step(run_metrics, "outline", started)
        try:
            self._repo.begin_generation(slug, outline)
            self._status[slug] = RunStatus(state="running", units_total=len(outline.units), units={u.unit_id: UnitGenerationStatus(u.unit_id) for u in outline.units})
            self._persist_progress(slug)
            pool = self._repo.load_inputs(slug).evidence_pool
            for ou in outline.units:
                await self._generate_unit(slug, ou, run_metrics, pool)
            self._complete(slug)
        except Exception:
            self._fail_storage(slug)

    async def _retry(self, slug, ou):
        try:
            pool = self._repo.load_inputs(slug).evidence_pool
            await self._generate_unit(slug, ou, self._metrics[slug], pool)
            self._complete(slug)
        except Exception:
            self._fail_storage(slug)

    async def aclose(self) -> None:
        """Cancel any pending runs cleanly (called on app shutdown)."""
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        for task in self._tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        await self._gen.aclose()
        await self._verifier.aclose()
