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
from dataclasses import dataclass

from app.domain import Unit, label_for_unit_id
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

    def status(self, slug: str) -> RunStatus:
        return self._status.get(slug, RunStatus())

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
        try:
            outline = await self._gen.outline(slug)
            self._repo.save_outline(slug, outline)
            outline_units = outline.units
            self._status[slug] = RunStatus(
                state="running", units_done=0, units_total=len(outline_units)
            )
            units: list[Unit] = []
            for ou in outline_units:
                variants = await self._gen.variants(slug, ou)
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
            self._status[slug].state = "done"
        except Exception as exc:  # the agent can fail; we say so honestly rather than pretend.
            self._status[slug] = RunStatus(state="error", error=str(exc))

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
