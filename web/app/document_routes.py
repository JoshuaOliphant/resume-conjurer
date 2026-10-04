# ABOUTME: Serves editable source documents and explicit import previews in a configured workspace.
# ABOUTME: Keeps uploads separate from saves and refuses stale or cross-origin source changes.

from __future__ import annotations

import secrets
from _thread import LockType

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.types import ASGIApp, Receive, Scope, Send

from app.document_import import MAX_DOCUMENT_BYTES, import_document
from app.document_normalize import NormalizedMaster, normalize_master_resume
from app.document_store import MAX_DOCUMENT_BYTES as MAX_SOURCE_BYTES
from app.document_store import ConflictError, DocumentStore
from app.rail import template_context
from app.runs import RunManager

MAX_UPLOAD_REQUEST_BYTES = MAX_DOCUMENT_BYTES + 64 * 1024


class DocumentUploadLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") != "POST" or scope.get("path") not in {"/documents/import", "/onboarding/sources"}:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_UPLOAD_REQUEST_BYTES:
                await PlainTextResponse("Upload request exceeds 10 MiB.", status_code=413)(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


def document_router(store: DocumentStore | None, templates: Jinja2Templates, runs: RunManager, slug: str, source_lock: LockType) -> APIRouter:
    router = APIRouter()
    preview_tokens: dict[str, tuple[str, bool]] = {}
    warning_revision: str | None = None

    def configured() -> DocumentStore:
        if store is None:
            raise HTTPException(503, "Source editing requires a configured workspace.")
        return store

    def writable(request: Request) -> DocumentStore:
        site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if site in {"same-origin", "same-site"}:
            pass
        elif site is None and origin and origin == expected:
            pass
        else:
            raise HTTPException(403, "Source changes must come from this application.")
        repository = configured()
        if runs.status(slug).state == "running":
            raise HTTPException(409, "Wait for generation to finish before changing its sources.")
        return repository

    def render(request: Request, name: str, *, status: int = 200, **extra):
        repository = configured()
        try:
            text, revision = repository.read_with_revision(name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        context = template_context(request, "entry", document_name=name, document_text=text, revision=revision)
        context.update(extra)
        return templates.TemplateResponse(request, "documents.html", context, status_code=status)

    def render_normalization(request: Request, source_text: str, revision: str,
                             normalization: NormalizedMaster, *, status: int = 200, error: str = "",
                             draft_text: str | None = None, order_review_required: bool = False,
                             review_token: str = ""):
        context = template_context(request, "entry", source_text=source_text, revision=revision,
                                   normalization=normalization, error=error,
                                   draft_text=normalization.text if draft_text is None else draft_text,
                                   order_review_required=order_review_required, review_token=review_token)
        return templates.TemplateResponse(request, "normalize.html", context, status_code=status)

    @router.get("/documents")
    def documents(request: Request, name: str = "master-resume.md", saved: bool = False):
        message = "Saved. Review existing applications against any changed source before using them." if saved else ""
        return render(request, name, message=message)

    @router.post("/documents/import")
    def import_preview_and_store_original(request: Request, document_name: str = Form(...), revision: str = Form(...), file: UploadFile = File(...)):
        nonlocal warning_revision
        repository = writable(request)
        try:
            repository.read(document_name)
            content = file.file.read(MAX_DOCUMENT_BYTES + 1)
            imported = import_document(file.filename or "", content)
            if len(imported.text.encode("utf-8")) > MAX_SOURCE_BYTES:
                raise ValueError("Extracted text exceeds the 2 MiB editor limit. Use a shorter source file.")
            key = repository.store_original(file.filename or "", content)
        except ValueError as exc:
            return render(request, document_name, status=400, error=str(exc))
        finally:
            file.file.close()
        normalization = normalize_master_resume(imported.text) if document_name == "master-resume.md" else None
        if document_name == "master-resume.md" and imported.warnings:
            with source_lock:
                warning_revision = revision
        context = template_context(request, "entry", document_name=document_name, document_text=repository.read(document_name), revision=revision, import_key=key, import_text=imported.text, import_warnings=imported.warnings, normalization=normalization)
        return templates.TemplateResponse(request, "documents.html", context)

    @router.post("/documents/normalize")
    def prepare_normalized_master_review(request: Request, document_name: str = Form(...), text: str = Form(...),
                                         revision: str = Form(...)):
        with source_lock:
            writable(request)
            if document_name != "master-resume.md":
                raise HTTPException(400, "Only the master resume can be normalized.")
            if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
                raise HTTPException(400, "Reviewed text exceeds the 2 MiB editor limit.")
            normalization = normalize_master_resume(text)
            review_token = secrets.token_urlsafe(24)
            order_review_required = warning_revision == revision
            preview_tokens[review_token] = (revision, order_review_required)
            if len(preview_tokens) > 64:
                del preview_tokens[next(iter(preview_tokens))]
        return render_normalization(request, text, revision, normalization,
                                    order_review_required=order_review_required, review_token=review_token)

    @router.post("/documents/normalize/accept")
    def accept_normalized_master(request: Request, document_name: str = Form(...), text: str = Form(...),
                                 revision: str = Form(...), review_token: str = Form(""),
                                 order_corrected: bool = Form(False)):
        nonlocal warning_revision
        with source_lock:
            repository = writable(request)
            if document_name != "master-resume.md":
                raise HTTPException(400, "Only the master resume can be normalized.")
            reviewed_text = text.replace("\r\n", "\n").replace("\r", "\n")
            normalization = normalize_master_resume(reviewed_text)
            preview = preview_tokens.get(review_token)
            if preview is None or preview[0] != revision:
                return render_normalization(request, "", revision, normalization, status=400,
                                            error="This draft has no valid review preview. Copy it, then prepare the master resume again.",
                                            draft_text=text)
            order_review_required = preview[1]
            if repository.revision(document_name) != revision:
                return render_normalization(
                    request, "", revision, normalization, status=409,
                    error="This master resume changed in another tab. Recover your unsaved normalized draft before reloading the saved document.",
                    draft_text=text, order_review_required=order_review_required, review_token=review_token,
                )
            if len(reviewed_text.encode("utf-8")) > MAX_SOURCE_BYTES:
                return render_normalization(request, "", revision, normalization, status=400,
                                            error="Normalized text exceeds the 2 MiB editor limit.", draft_text=text,
                                            order_review_required=order_review_required, review_token=review_token)
            if order_review_required and not order_corrected:
                return render_normalization(request, "", revision, normalization, status=422,
                                            error="Review and correct the reading order against the original file before accepting.",
                                            draft_text=text, order_review_required=True, review_token=review_token)
            if normalization.corrections or normalization.text != reviewed_text:
                return render_normalization(request, "", revision, normalization, status=422,
                                            error="Correct the listed structure and review the exact draft before accepting it.",
                                            draft_text=text, order_review_required=order_review_required, review_token=review_token)
            try:
                repository.save(document_name, reviewed_text, revision)
            except ConflictError:
                return render_normalization(
                    request, "", revision, normalization, status=409,
                    error="This master resume changed in another tab. Recover your unsaved normalized draft before reloading the saved document.",
                    draft_text=text, order_review_required=order_review_required, review_token=review_token,
                )
            except ValueError as exc:
                return render_normalization(request, "", revision, normalization, status=400,
                                            error=str(exc), draft_text=text,
                                            order_review_required=order_review_required, review_token=review_token)
            del preview_tokens[review_token]
            if warning_revision == revision:
                warning_revision = None
        return RedirectResponse("/documents?name=master-resume.md&saved=true", status_code=303)

    @router.post("/documents/save")
    def save(request: Request, document_name: str = Form(...), text: str = Form(...), revision: str = Form(...)):
        with source_lock:
            repository = writable(request)
            try:
                repository.save(document_name, text, revision)
            except ConflictError:
                return render(request, document_name, status=409, error="This document changed in another tab. Copy your edits before reloading to review the latest version.", import_key="recovery", import_text=text, revision=revision)
            except ValueError as exc:
                return render(request, document_name, status=400, error=str(exc), import_key="recovery", import_text=text, revision=revision)
        return RedirectResponse(f"/documents?name={document_name}&saved=true", status_code=303)

    return router
