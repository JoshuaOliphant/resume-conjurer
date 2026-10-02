# ABOUTME: FastAPI app serving the Conjurer pipeline UI (entry → outline → curate → review → export).
# ABOUTME: Routes orchestrate; wiring is in deps.py, the rail + template context in rail.py.

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.adapters.finals_fs import FinalDocuments
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.data import lint_results
from app.deps import (
    build_composition,
    build_generation,
    build_repository,
    build_verification,
    is_live,
    workspace_root,
)
from app.document_routes import DocumentUploadLimit, document_router
from app.document_store import ConflictError, DocumentStore
from app.domain import SUPPORT_CHECK_LABEL, LintCheck, support_check
from app.onboarding_routes import onboarding_router
from app.onboarding_sdk import OnboardingSdk
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
    documents: DocumentStore | None = None,
    finals: FinalDocuments | None = None,
    onboarding: OnboardingSdk | None = None,
) -> FastAPI:
    """Build the FastAPI app over an injected repository, generation port, and run manager.

    ``comp`` handles deterministic lint and export in live configuration. ``finals`` owns
    explicit composition and editable Markdown; the fake configuration renders sample picks.
    """
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Cancel any still-running generation tasks on shutdown so none are orphaned.
        await run_manager.aclose()

    app = FastAPI(title="Conjurer", lifespan=lifespan)
    app.add_middleware(DocumentUploadLimit)
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=str(BASE / "templates"))
    source_lock = Lock()
    app.include_router(document_router(documents, templates, run_manager, SLUG, source_lock))
    app.include_router(onboarding_router(documents, templates, onboarding or OnboardingSdk(), run_manager, SLUG, source_lock))

    def require_mutation(request: Request) -> None:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != expected):
            raise HTTPException(403, "Document changes must come from this application.")
        if run_manager.status(SLUG).state == "running":
            raise HTTPException(409, "Wait for generation to finish before changing final documents.")

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
                request, "entry", app_data=app_data, master_resume_note=master_resume_note, documents_available=documents is not None
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
        await run_in_threadpool(source_lock.acquire)
        try:
            if run_manager.status(SLUG).state != "running":
                if jd:
                    await run_in_threadpool(repo.save_jd, SLUG, jd)
                run_manager.start(SLUG)
        finally:
            source_lock.release()
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
    def curate_pick(request: Request, idx: int, variant_id: str = Form(...)):
        with source_lock:
            require_mutation(request)
            data = repo.load_application(SLUG)
            units = data.units
            if not 0 <= idx < len(units):
                raise HTTPException(status_code=404, detail="No such line to curate.")
            unit = units[idx]
            if variant_id not in unit.variant_ids:
                raise HTTPException(status_code=422, detail="That variant isn't an option for this line.")
            repo.set_pick(SLUG, unit.id, variant_id)
        nxt = idx + 1
        if nxt >= len(units):
            return RedirectResponse("/review", status_code=303)
        return RedirectResponse(f"/curate/{nxt}", status_code=303)

    def render_review(request: Request, *, error: str = "", status: int = 200):
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
        final = finals.state() if finals is not None else None
        if comp is not None and final is not None and final.complete:
            lint = comp.lint(SLUG)
        else:
            lint = lint_results(cover_text)
        if final is not None and final.complete and (final.edited or final.stale):
            support = LintCheck(SUPPORT_CHECK_LABEL, "Final text or its sources changed. Claim support is unchecked for this document.", False)
        else:
            support = support_check(chosen)
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
                support=support,
                complete=complete,
                final=final,
                error=error,
                run_metrics=run_manager.metrics(SLUG),
            ),
            status_code=status,
        )

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request):
        with source_lock:
            return render_review(request)

    @app.post("/review/compose", response_class=HTMLResponse)
    def compose(request: Request, cover_revision: str = Form(""), resume_revision: str = Form("")):
        if finals is None or comp is None:
            raise HTTPException(503, "Final documents require a configured workspace.")
        with source_lock:
            require_mutation(request)
            data = repo.load_application(SLUG)
            picks = repo.get_picks(SLUG)
            if not all(picks.get(unit.id) in unit.variant_ids for unit in data.units):
                return render_review(request, error="Choose every line before composing.", status=409)
            try:
                finals.compose(cover_revision, resume_revision)
            except ConflictError as exc:
                return render_review(request, error=str(exc), status=409)
            except (OSError, ValueError, RuntimeError) as exc:
                return render_review(request, error=f"Could not compose final documents: {exc}", status=503)
        return RedirectResponse("/review", status_code=303)

    def render_final_editor(request: Request, name: str, *, error: str = "", recovery_text: str = "",
                            submitted_revision: str | None = None, saved: bool = False, status: int = 200):
        if finals is None:
            raise HTTPException(503, "Final documents require a configured workspace.")
        try:
            text, revision = finals.store.read_with_revision(name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not revision:
            raise HTTPException(409, "Compose final documents before editing them.")
        return templates.TemplateResponse(
            request, "final_editor.html",
            template_context(request, "review", document_name=name, document_text=text,
                             revision=revision if submitted_revision is None else submitted_revision,
                             error=error, recovery_text=recovery_text, saved=saved),
            status_code=status,
        )

    @app.get("/finals", response_class=HTMLResponse)
    def final_editor(request: Request, name: str = "resume.md", saved: bool = False):
        return render_final_editor(request, name, saved=saved)

    @app.post("/finals/save", response_class=HTMLResponse)
    def save_final(request: Request, document_name: str = Form(...), text: str = Form(...), revision: str = Form("")):
        if finals is None:
            raise HTTPException(503, "Final documents require a configured workspace.")
        with source_lock:
            require_mutation(request)
            try:
                if not finals.store.revision(document_name):
                    raise ConflictError("Compose final documents before editing them.")
                finals.save(document_name, text, revision)
            except ConflictError:
                return render_final_editor(request, document_name,
                                           error="This final document changed in another tab. Copy your edits before reloading the saved version to compare them.",
                                           recovery_text=text, submitted_revision=revision, status=409)
            except ValueError as exc:
                return render_final_editor(request, document_name, error=str(exc), recovery_text=text,
                                           submitted_revision=revision, status=400)
        return RedirectResponse(f"/finals?name={document_name}&saved=true", status_code=303)

    @app.get("/export", response_class=HTMLResponse)
    def export(request: Request):
        if _not_generated_yet():
            return RedirectResponse("/", status_code=303)
        exported = None
        downloads = {}
        if comp is not None:
            with source_lock:
                if run_manager.status(SLUG).state == "running":
                    raise HTTPException(409, "Wait for generation to finish before exporting final documents.")
                if finals is not None and finals.state().complete:
                    exported = comp.export(SLUG, ("pdf", "docx"))
                    finals.record_exports(exported)
                else:
                    exported = {}
                for extension in ("pdf", "docx", "md"):
                    downloads[extension] = []
                    for document, label in (("cover_letter", "Cover letter"), ("resume", "Resume")):
                        filename = f"{document}.{extension}"
                        if extension != "md" and exported.get(filename) != "written":
                            continue
                        if comp.download(SLUG, filename) is not None:
                            downloads[extension].append((filename, label))
        return templates.TemplateResponse(
            request,
            "export.html",
            template_context(request, "export", app_data=repo.load_application(SLUG), exported=exported, downloads=downloads),
        )

    @app.get("/export/download/{filename}")
    def download(filename: str):
        with source_lock:
            if run_manager.status(SLUG).state == "running":
                raise HTTPException(409, "Wait for generation to finish before downloading final documents.")
            artifact = comp.download(SLUG, filename) if comp is not None else None
            if artifact is None or finals is None or not finals.can_download(filename):
                raise HTTPException(status_code=404, detail="No such exported file.")
            content = artifact.read_bytes()
        media_type = {
            ".md": "text/markdown",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }[artifact.suffix]
        return Response(content, media_type=media_type, headers={"content-disposition": f'attachment; filename="{filename}"'})

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
_run_manager = RunManager(repo=_repo, gen=_gen, verifier=build_verification())
app = create_app(repo=_repo, gen=_gen, run_manager=_run_manager, live=is_live(), comp=_comp,
                 documents=DocumentStore(workspace_root()) if is_live() else None,
                 finals=FinalDocuments(workspace_root(), SLUG) if is_live() else None)
