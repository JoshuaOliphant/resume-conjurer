# ABOUTME: Async RunManager — orchestrates a live generation run and tracks per-unit progress.
# ABOUTME: Kicks outline + variants off as a background task; the UI polls status() while it works.

"""Background orchestration for the live generation flow.

A run, keyed by ``slug``, does the work the agent can't do synchronously inside a request:
choose the outline, then summon variants for each unit, persisting both to the workspace via
the repository. The route handler calls :meth:`start` (which returns immediately, having set
state to ``running``) and the HTMX poll calls :meth:`status` until it reads ``done`` or
``error``.

State is held in memory, keyed by slug, behind the same indirection the rest of the backend
uses, so a future per-session/per-user resolver is a new key source rather than a rewrite.
Generation's non-determinism stays quarantined behind :class:`~app.ports.GenerationPort`;
this module only sequences calls and counts progress.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.domain import Unit, label_for_unit_id
from app.metrics import CallMetrics, RunMetrics, StepMetrics
from app.ports import GenerationPort, WorkspaceRepository

RunState = str  # one of: "idle" | "running" | "done" | "error"


@dataclass
class RunStatus:
    """A snapshot of one slug's run, safe to render in the progress partial."""

    state: RunState = "idle"
    units_done: int = 0
    units_total: int = 0
    error: str | None = None


class RunManager:
    """Sequences outline + variant generation for a slug, tracking progress."""

    def __init__(self, repo: WorkspaceRepository, gen: GenerationPort) -> None:
        self._repo = repo
        self._gen = gen
        self._status: dict[str, RunStatus] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._metrics: dict[str, RunMetrics] = {}

    def status(self, slug: str) -> RunStatus:
        return self._status.get(slug, RunStatus())

    def metrics(self, slug: str) -> RunMetrics | None:
        return self._metrics.get(slug)

    def _record_step(self, run_metrics: RunMetrics, name: str, started: float) -> None:
        """Append one step's metrics: its wall time plus the generation port's last call.

        Called after each outline()/variants() so partial progress is captured even when a
        later step fails (the RunMetrics object is already visible via metrics()).
        """
        wall_ms = int((time.monotonic() - started) * 1000)
        call = self._gen.last_call or CallMetrics.zero()
        run_metrics.steps.append(StepMetrics(name=name, wall_ms=wall_ms, call=call))

    def start(self, slug: str) -> None:
        """Launch a background run for ``slug`` unless one is already running."""
        if self.status(slug).state == "running":
            return
        # Mark running synchronously so the route can render the progress page and the
        # very next status poll already reflects an in-flight run.
        self._status[slug] = RunStatus(state="running")
        self._tasks[slug] = asyncio.create_task(self._run(slug))

    async def join(self, slug: str) -> None:
        """Await the background task for ``slug`` (a no-op if none is in flight)."""
        task = self._tasks.get(slug)
        if task is not None:
            await task

    async def _run(self, slug: str) -> None:
        run_metrics = RunMetrics(slug=slug, steps=[])
        # Publish the (initially empty) metrics up front so any steps recorded before an error
        # are visible best-effort; the except path touches no metrics and so cannot mask the
        # generation error with a metrics/persist failure.
        self._metrics[slug] = run_metrics
        try:
            started = time.monotonic()
            outline = await self._gen.outline(slug)
            self._record_step(run_metrics, "outline", started)
            self._repo.save_outline(slug, outline)
            outline_units = outline.units
            self._status[slug] = RunStatus(
                state="running", units_done=0, units_total=len(outline_units)
            )
            units: list[Unit] = []
            for ou in outline_units:
                started = time.monotonic()
                variants = await self._gen.variants(slug, ou)
                self._record_step(run_metrics, ou.unit_id, started)
                # A unit with zero variants is a real generation failure: fail honestly
                # here so the except below records state="error", rather than letting an
                # empty unit reach (and 500) the curate/review screens later.
                if not variants:
                    raise RuntimeError(f"No variants generated for {ou.unit_id}")
                units.append(
                    Unit(
                        id=ou.unit_id,
                        kind=ou.kind,
                        label=label_for_unit_id(ou.unit_id),
                        context=ou.description,
                        variants=variants,
                    )
                )
                self._status[slug].units_done = len(units)
            self._repo.save_variants(slug, units)
            self._repo.save_metrics(slug, run_metrics)
            self._status[slug].state = "done"
        except Exception as exc:  # the agent can fail; we say so honestly rather than pretend.
            # Keep whatever progress counts the run reached so the error snapshot shows how
            # far the summoning got (e.g. "failed after 3 of 6 lines"), not a reset to zero.
            prev = self._status.get(slug, RunStatus())
            self._status[slug] = RunStatus(
                state="error",
                units_done=prev.units_done,
                units_total=prev.units_total,
                error=str(exc),
            )

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
        # Release the generation port's own resources (e.g. the persistent SDK client).
        await self._gen.aclose()
