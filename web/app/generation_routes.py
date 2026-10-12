# ABOUTME: Application-scoped retry actions and generation progress rendering.
# ABOUTME: Rejects unsafe mutations and keeps retry controls attached to failed units.
import re
from threading import Lock
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates

from app.ports import WorkspaceRepository
from app.runs import RunManager


def generation_router(repo: WorkspaceRepository, run_manager: RunManager, templates: Jinja2Templates, slug: str, source_lock: Lock) -> APIRouter:
    router = APIRouter()

    def render(request):
        return templates.TemplateResponse(request, "_summon_progress.html", {"request": request, "status": run_manager.status(slug)})

    @router.post("/generate/retry/{unit_id:path}")
    async def retry(request: Request, unit_id: str):
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if request.headers.get("sec-fetch-site") not in ("same-origin", "same-site") and origin != expected:
            raise HTTPException(403, "Retry must come from this application.")
        await run_in_threadpool(source_lock.acquire)
        try:
            try:
                run_manager.retry_unit(slug, unit_id)
            except ValueError as exc:
                raise HTTPException(404, "No failed unit available for retry.") from exc
        finally:
            source_lock.release()
        return render(request)

    @router.get("/generate/unit-status")
    def progress(request: Request):
        response = render(request)
        current = urlsplit(request.headers.get("HX-Current-URL", ""))
        if run_manager.status(slug).state in ("done", "partial") and current.netloc == request.url.netloc and (current.path == "/outline" or re.fullmatch(r"/curate/\d+", current.path)):
            response.headers["HX-Redirect"] = current.path
        return response

    return router
