# ABOUTME: FastAPI app serving the Conjurer pipeline UI (entry → outline → curate → review → export).
# ABOUTME: Routes orchestrate; wiring is in deps.py, the rail + template context in rail.py.

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.data import lint_results
from app.deps import build_composition, build_generation, build_repository, is_live
from app.ports import CompositionPort, GenerationPort, WorkspaceRepository
from app.rail import template_context
from app.runs import RunManager

BASE = Path(__file__).parent

# Single fixed workspace today; the slug is the seam a future multi-user resolver scopes.
SLUG = "globex-staff-platform"


def create_app(
    repo: WorkspaceRepository,
    gen: GenerationPort,
    run_manager: RunManager,
    *,
    live: bool,
    comp: CompositionPort | None = None,
) -> FastAPI:
    """Build the FastAPI app over an injected repository, generation port, and run manager.

    ``comp`` is the deterministic composition port (stitch/lint/export). When present (live
    config) /review stitches+lints the real workspace docs and /export runs export_docs; when
    None (fake config) /review uses the in-memory lint and /export shows the static template.
    """
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Cancel any still-running generation tasks on shutdown so none are orphaned.
        await run_manager.aclose()

    app = FastAPI(title="Conjurer", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=str(BASE / "templates"))

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
        # Honest source line: the live backend reuses the workspace master resume; the
        # offline config uses the bundled sample. No fabricated "last updated"/counts.
        master_resume_note = (
            "Reusing master-resume.md from your workspace."
            if live
            else "Using the bundled sample resume."
        )
        return templates.TemplateResponse(
            request,
            "entry.html",
            template_context(
                request, "entry", app_data=app_data, master_resume_note=master_resume_note
            ),
        )

    @app.post("/start")
    async def start(request: Request):
        # Offline (fake) config has variants ready, so step straight to the outline.
        # The live config writes the pasted JD into the workspace, then summons variants
        # in the background and shows a progress page.
        if not live:
            return RedirectResponse("/outline", status_code=303)
        form = await request.form()
        jd = str(form.get("jd", "")).strip()
        if jd:
            repo.save_jd(SLUG, jd)
        run_manager.start(SLUG)
        return templates.TemplateResponse(
            request,
            "summoning.html",
            template_context(request, "outline", status=run_manager.status(SLUG), app_data=None),
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

    @app.get("/metrics")
    def metrics():
        # The current run's metrics as JSON (cost / caching / performance). Empty object when
        # no run has completed yet — true in the fake config and in a fresh live workspace.
        run_metrics = run_manager.metrics(SLUG)
        payload = run_metrics.to_dict() if run_metrics is not None else {}
        return JSONResponse(payload)

    @app.get("/outline", response_class=HTMLResponse)
    def outline(request: Request):
        if _not_generated_yet():
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request,
            "outline.html",
            template_context(request, "outline", app_data=repo.load_application(SLUG)),
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
            template_context(
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
        if comp is not None and complete:
            # Live, and every line is picked: stitch the picked variants into real
            # cover_letter.md / resume.md, then run the grimoire linter over those stitched
            # docs (the real check, not in-memory). stitch requires one pick per unit, so we
            # only run it when complete; otherwise we show the in-memory lint + the incomplete
            # banner rather than 500-ing on a half-curated workspace.
            comp.stitch(SLUG)
            lint = comp.lint(SLUG)
        else:
            lint = lint_results(cover_text)
        return templates.TemplateResponse(
            request,
            "review.html",
            template_context(
                request,
                "review",
                app_data=data,
                cover=cover,
                bullets=bullets,
                lint=lint,
                complete=complete,
                run_metrics=run_manager.metrics(SLUG),
            ),
        )

    @app.get("/export", response_class=HTMLResponse)
    def export(request: Request):
        if _not_generated_yet():
            return RedirectResponse("/", status_code=303)
        # Live: actually export the stitched docs and report the written/skipped map per
        # format. Fake has no workspace to export, so it shows the static export template.
        exported = comp.export(SLUG, ("pdf", "docx")) if comp is not None else None
        return templates.TemplateResponse(
            request,
            "export.html",
            template_context(request, "export", app_data=repo.load_application(SLUG), exported=exported),
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
_comp = build_composition()
_run_manager = RunManager(repo=_repo, gen=_gen)
app = create_app(repo=_repo, gen=_gen, run_manager=_run_manager, live=is_live(), comp=_comp)
