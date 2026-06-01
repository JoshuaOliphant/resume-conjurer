# ABOUTME: FastAPI app serving the Conjurer pipeline UI (entry → outline → curate → review → export).
# ABOUTME: A composition root wires a WorkspaceRepository + GenerationPort + RunManager into the routes.

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.generation_sdk import SdkGenerationPort
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.data import lint_results
from app.ports import GenerationPort, WorkspaceRepository
from app.runs import RunManager

BASE = Path(__file__).parent

# Single fixed workspace today; the slug is the seam a future multi-user resolver scopes.
SLUG = "globex-staff-platform"

# The five pipeline steps, in order, for the rail.
STEPS = [
    ("entry", "Start", "/"),
    ("outline", "Outline", "/outline"),
    ("curate", "Curate", "/curate"),
    ("review", "Review", "/review"),
    ("export", "Export", "/export"),
]


# --- Composition root ------------------------------------------------------
# One place resolves which backend (fake/offline vs live SDK) and which workspace,
# keyed on env. The default is `fake`, preserving the shipped editorial UI offline.


def _is_live() -> bool:
    return os.environ.get("CONJURER_BACKEND", "fake") == "live"


def _workspace_root() -> Path:
    env = os.environ.get("CONJURER_WORKSPACE")
    if env:
        return Path(env)
    return BASE.parent / "tests" / "fixtures" / "workspace"


def build_repository() -> WorkspaceRepository:
    if _is_live():
        return FsWorkspaceRepository(_workspace_root())
    return FakeWorkspaceRepository()


def build_generation() -> GenerationPort:
    if _is_live():
        return SdkGenerationPort(_workspace_root())
    return FakeGenerationPort()


def build_run_manager() -> RunManager:
    return RunManager(repo=build_repository(), gen=build_generation())


def create_app(
    repo: WorkspaceRepository,
    gen: GenerationPort,
    run_manager: RunManager,
    *,
    live: bool,
) -> FastAPI:
    """Build the FastAPI app over an injected repository, generation port, and run manager."""
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Cancel any still-running generation tasks on shutdown so none are orphaned.
        await run_manager.aclose()

    app = FastAPI(title="Conjurer", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=str(BASE / "templates"))

    def _ctx(request: Request, active: str, **extra) -> dict:
        active_i = next((i for i, (key, _, _) in enumerate(STEPS) if key == active), 0)
        return {
            "request": request,
            "steps": STEPS,
            "active_step": active,
            "active_i": active_i,
            **extra,
        }

    def _not_generated_yet() -> bool:
        # Live only: a fresh workspace has no outline.json yet, so load_application would
        # raise FileNotFoundError. The fake repo always has its fixture application, and its
        # load_outline raises NotImplementedError, so the `live and` short-circuit guards it.
        return live and repo.load_outline(SLUG) is None

    @app.get("/", response_class=HTMLResponse)
    def entry(request: Request):
        # Before generation has run (fresh live workspace) there is no application to show,
        # so render the Start form without app_data. base.html tolerates a missing app_data.
        app_data = None if _not_generated_yet() else repo.load_application(SLUG)
        return templates.TemplateResponse(
            request, "entry.html", _ctx(request, "entry", app_data=app_data)
        )

    @app.post("/start")
    async def start(request: Request):
        # Offline (fake) config has variants ready, so step straight to the outline.
        # The live config summons them in the background and shows a progress page.
        if not live:
            return RedirectResponse("/outline", status_code=303)
        run_manager.start(SLUG)
        return templates.TemplateResponse(
            request,
            "summoning.html",
            _ctx(request, "outline", status=run_manager.status(SLUG), app_data=None),
        )

    @app.get("/generate/status", response_class=HTMLResponse)
    def generate_status(request: Request):
        status = run_manager.status(SLUG)
        response = templates.TemplateResponse(
            request, "_summon_progress.html", {"request": request, "status": status}
        )
        if status.state == "done":
            response.headers["HX-Redirect"] = "/outline"
        return response

    @app.get("/outline", response_class=HTMLResponse)
    def outline(request: Request):
        if _not_generated_yet():
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request, "outline.html", _ctx(request, "outline", app_data=repo.load_application(SLUG))
        )

    @app.get("/curate", response_class=HTMLResponse)
    def curate_start():
        if _not_generated_yet():
            return RedirectResponse("/", status_code=303)
        return RedirectResponse("/curate/0", status_code=303)

    @app.get("/curate/{idx}", response_class=HTMLResponse)
    def curate(request: Request, idx: int):
        if _not_generated_yet():
            return RedirectResponse("/", status_code=303)
        data = repo.load_application(SLUG)
        units = data.units
        if idx < 0 or idx >= len(units):
            return RedirectResponse("/review", status_code=303)
        unit = units[idx]
        return templates.TemplateResponse(
            request,
            "curate.html",
            _ctx(
                request,
                "curate",
                app_data=data,
                unit=unit,
                idx=idx,
                total=len(units),
                selected=repo.get_picks(SLUG).get(unit.id),
                prev_idx=idx - 1 if idx > 0 else None,
            ),
        )

    @app.post("/curate/{idx}")
    def curate_pick(idx: int, variant_id: str = Form(...)):
        data = repo.load_application(SLUG)
        units = data.units
        if not 0 <= idx < len(units):
            raise HTTPException(status_code=404, detail="No such line to curate.")
        unit = units[idx]
        # Only store a variant that actually belongs to this unit. Rejecting an
        # unknown id here is what keeps the review screen from later attributing
        # content to the user that they never chose.
        if variant_id not in unit.variant_ids:
            raise HTTPException(status_code=422, detail="That variant isn't an option for this line.")
        repo.set_pick(SLUG, unit.id, variant_id)
        nxt = idx + 1
        if nxt >= len(units):
            return RedirectResponse("/review", status_code=303)
        return RedirectResponse(f"/curate/{nxt}", status_code=303)

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request):
        if _not_generated_yet():
            return RedirectResponse("/", status_code=303)
        data = repo.load_application(SLUG)
        picks = repo.get_picks(SLUG)
        chosen = []
        for unit in data.units:
            # A zero-variant unit can't be indexed; skip it rather than crash. The honest
            # surface for an empty unit is the summoning-error page (see runs.py), not a 500.
            if not unit.variants:
                continue
            vid = picks.get(unit.id)
            variant = next((v for v in unit.variants if v.id == vid), unit.variants[0])
            chosen.append((unit, variant))
        cover = [(u, v) for (u, v) in chosen if u.kind == "cover_paragraph"]
        bullets = [(u, v) for (u, v) in chosen if u.kind == "resume_bullet"]
        # Complete means every unit has a stored selection that is actually one of
        # its variants — not merely that the store has enough entries.
        complete = all(picks.get(u.id) in u.variant_ids for u in data.units)
        cover_text = "\n\n".join(v.text for (_, v) in cover)
        return templates.TemplateResponse(
            request,
            "review.html",
            _ctx(
                request,
                "review",
                app_data=data,
                cover=cover,
                bullets=bullets,
                lint=lint_results(cover_text),
                complete=complete,
            ),
        )

    @app.get("/export", response_class=HTMLResponse)
    def export(request: Request):
        if _not_generated_yet():
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request, "export.html", _ctx(request, "export", app_data=repo.load_application(SLUG))
        )

    @app.post("/reset")
    def reset():
        # Offline, picks live in the fake repo's in-memory store and can be cleared;
        # the live filesystem store keeps variants.md as the source of truth, so reset
        # there just returns to the start (re-running generation overwrites it).
        if isinstance(repo, FakeWorkspaceRepository):
            repo.clear(SLUG)
        return RedirectResponse("/", status_code=303)

    return app


_repo = build_repository()
_gen = build_generation()
_run_manager = RunManager(repo=_repo, gen=_gen)
app = create_app(repo=_repo, gen=_gen, run_manager=_run_manager, live=_is_live())
