# ABOUTME: Guides local source review, explicitly consented Claude drafting, and grimoire acceptance.
# ABOUTME: Preserves unaccepted drafts and refuses stale source or document revisions.
from __future__ import annotations

import asyncio
import hashlib
from _thread import LockType

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.document_import import MAX_DOCUMENT_BYTES, import_document
from app.document_normalize import normalize_master_resume
from app.document_store import ConflictError, DocumentStore
from app.onboarding import (
    KINDS,
    MAX_REVIEW_BYTES,
    acceptance_questions,
    bounded_snippets,
    build_prompt,
    claim_ledger,
    reviewed_snippets,
    source_lines,
    source_questions,
    validate_proposal,
)
from app.onboarding_sdk import OnboardingSdk
from app.onboarding_store import OnboardingStore
from app.rail import template_context
from app.runs import RunManager

MAX_PROMPT_BYTES = 64 * 1024


def onboarding_router(documents: DocumentStore | None, templates: Jinja2Templates, sdk: OnboardingSdk,
                      runs: RunManager, slug: str, source_lock: LockType) -> APIRouter:
    router = APIRouter()
    drafts = OnboardingStore(documents.root) if documents is not None else None
    active = False

    def configured() -> tuple[DocumentStore, OnboardingStore]:
        if documents is None or drafts is None:
            raise HTTPException(503, "Grimoire onboarding requires a configured workspace.")
        return documents, drafts

    def writable(request: Request) -> tuple[DocumentStore, OnboardingStore]:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != expected):
            raise HTTPException(403, "Grimoire changes must come from this application.")
        stores = configured()
        if active or runs.status(slug).state == "running":
            raise HTTPException(409, "Wait for the current draft or generation to finish.")
        return stores

    def render(request: Request, *, state: dict | None = None, revision: str | None = None,
               error: str = "", status: int = 200, saved: bool = False):
        source_store, draft_store = configured()
        if state is None:
            state, revision = draft_store.read()
        master, master_revision = source_store.read_with_revision("master-resume.md")
        try:
            prompt = build_prompt(state)
            available = source_lines(master, master_revision, state["optional_sources"])
            questions = acceptance_questions(state, state["draft"], master_revision, True) if state["claims"] else source_questions(reviewed_snippets(state))
        except ValueError as exc:
            prompt, available, questions = "", [], [str(exc)]
            if status == 200:
                status = 400
        context = template_context(request, "entry", state=state, revision=revision, error=error, saved=saved,
                                   available=available,
                                   selected_ids={source["id"] for source in state["selected"]},
                                   questions=questions,
                                   ledger=claim_ledger(state, state["draft"], master_revision),
                                   prompt=prompt, prompt_hash=hashlib.sha256(prompt.encode()).hexdigest())
        return templates.TemplateResponse(request, "onboarding.html", context, status_code=status)

    @router.get("/onboarding")
    def onboarding(request: Request, saved: bool = False):
        source_store, _ = configured()
        master = source_store.read("master-resume.md")
        if not master or not normalize_master_resume(master).ready:
            return RedirectResponse("/documents?name=master-resume.md", status_code=303)
        return render(request, saved=saved)

    @router.post("/onboarding/sources")
    def add_source(request: Request, revision: str = Form(""), kind: str = Form(...),
                   pasted: str = Form(""), file: UploadFile | None = File(None)):
        with source_lock:
            source_store, draft_store = writable(request)
            state, current = draft_store.read()
            if current != revision:
                return render(request, state=state, revision=revision, status=409, error="Onboarding changed in another tab. Reload before adding a source.")
            try:
                if kind not in KINDS:
                    raise ValueError("Tag the source as career fact or voice sample.")
                if bool(file and file.filename) == bool(pasted.strip()):
                    raise ValueError("Upload one file or paste one source.")
                has_file = bool(file and file.filename)
                filename = file.filename if has_file else "pasted.txt"
                content = file.file.read(MAX_DOCUMENT_BYTES + 1) if has_file else pasted.encode("utf-8")
                imported = import_document(filename or "", content)
                if len(imported.text.encode()) > MAX_REVIEW_BYTES or len(state["optional_sources"]) >= 16:
                    raise ValueError("Keep optional sources below 64 KiB and at most 16 files. Paste a shorter excerpt.")
                original_hash = hashlib.sha256(content).hexdigest()
                source = {"text": imported.text, "kind": kind, "filename": filename,
                          "revision": hashlib.sha256(imported.text.encode()).hexdigest(),
                          "original_hash": original_hash, "warnings": list(imported.warnings)}
                optional = [item for item in state["optional_sources"] if item["original_hash"] != original_hash] + [source]
                master, master_revision = source_store.read_with_revision("master-resume.md")
                source_lines(master, master_revision, optional)
                source_store.store_original(filename or "", content)
                state["optional_sources"] = optional
                draft_store.save(state, revision)
            except ValueError as exc:
                return render(request, state=state, revision=revision, status=400, error=str(exc))
            finally:
                if file is not None:
                    file.file.close()
        return RedirectResponse("/onboarding", status_code=303)

    @router.post("/onboarding/sources/remove")
    def remove_source(request: Request, revision: str = Form(...), original_hash: str = Form(...)):
        with source_lock:
            _, draft_store = writable(request)
            state, _ = draft_store.read()
            state["optional_sources"] = [source for source in state["optional_sources"] if source["original_hash"] != original_hash]
            state["selected"] = [source for source in state["selected"] if source["original_hash"] != original_hash]
            try:
                draft_store.save(state, revision)
            except ConflictError:
                return render(request, status=409, error="Onboarding changed. Reload before removing a source.")
        return RedirectResponse("/onboarding", status_code=303)

    @router.post("/onboarding/review")
    def review_sources(request: Request, revision: str = Form(""), roles: str = Form(...),
                       examples: str = Form(...), voice: str = Form(...), source_ids: list[str] = Form([])):
        with source_lock:
            source_store, draft_store = writable(request)
            state, _ = draft_store.read()
            state["answers"] = {"roles": roles, "examples": examples, "voice": voice}
            master, master_revision = source_store.read_with_revision("master-resume.md")
            try:
                bounded_snippets(reviewed_snippets(state))
                available = {source["id"]: source for source in source_lines(master, master_revision, state["optional_sources"])}
                if not normalize_master_resume(master).ready:
                    raise ValueError("Import and prepare your master resume before onboarding.")
                if not all(answer.strip() for answer in state["answers"].values()):
                    raise ValueError("Answer all three question groups before drafting.")
                if any(source_id not in available for source_id in source_ids):
                    raise ValueError("A selected excerpt no longer exists. Re-review the sources.")
                state["selected"] = [available[source_id] for source_id in dict.fromkeys(source_ids)]
                state["master_revision"] = master_revision
                state["grimoire_revision"] = source_store.revision("grimoire.md")
                draft_store.save(state, revision)
            except ConflictError:
                return render(request, state=state, revision=revision, status=409, error="Onboarding changed in another tab. Your submitted answers remain below; reload before saving.")
            except ValueError as exc:
                return render(request, state=state, revision=revision, status=400, error=str(exc))
        return RedirectResponse("/onboarding", status_code=303)

    @router.post("/onboarding/draft")
    def draft_grimoire(request: Request, revision: str = Form(...), prompt_hash: str = Form(...)):
        nonlocal active
        with source_lock:
            source_store, draft_store = writable(request)
            state, current = draft_store.read()
            try:
                prompt = build_prompt(state)
            except ValueError as exc:
                return render(request, state=state, revision=revision, status=400, error=str(exc))
            if current != revision or hashlib.sha256(prompt.encode()).hexdigest() != prompt_hash or state["master_revision"] != source_store.revision("master-resume.md"):
                return render(request, state=state, revision=revision, status=409, error="Reviewed sources changed. Re-review the exact outbound text before drafting.")
            if not all(state["answers"].values()) or len(prompt.encode()) > MAX_PROMPT_BYTES:
                return render(request, state=state, revision=revision, status=400, error="Complete the answers and select at most 64 KiB of outbound text.")
            active = True
        try:
            payload, metrics = asyncio.run(asyncio.wait_for(sdk.draft(prompt), timeout=90))
            proposal, claims = validate_proposal(payload, reviewed_snippets(state))
            state.update(proposal=proposal, claims=claims, metrics=metrics)
            if not state["draft"]:
                state["draft"] = proposal
            with source_lock:
                next_revision = draft_store.save(state, revision)
                if state["master_revision"] != source_store.revision("master-resume.md"):
                    return render(request, state=state, revision=next_revision, status=409,
                                  error="The master resume changed while Claude drafted. Your proposal is retained; re-review sources before acceptance.")
        except ConflictError:
            return render(request, state=state, revision=revision, status=409, error="Onboarding changed while Claude drafted. Recover the proposal below before reloading.")
        except Exception as exc:
            return render(request, status=400, error=f"Draft failed ({type(exc).__name__}): {exc}. Your saved answers and draft remain available.")
        finally:
            with source_lock:
                active = False
        return RedirectResponse("/onboarding", status_code=303)

    @router.post("/onboarding/edit")
    def edit_draft(request: Request, revision: str = Form(...), draft: str = Form(""), use_proposal: bool = Form(False), discard: bool = Form(False)):
        with source_lock:
            _, draft_store = writable(request)
            state, _ = draft_store.read()
            state["draft"] = "" if discard else state["proposal"] if use_proposal else draft
            if not state["draft"]:
                state.update(proposal="", claims=[], metrics={})
            try:
                draft_store.save(state, revision)
            except ConflictError:
                return render(request, state=state, revision=revision, status=409, error="Onboarding changed in another tab. Your edited draft remains below for recovery.")
            except ValueError as exc:
                return render(request, state=state, revision=revision, status=400, error=str(exc))
        return RedirectResponse("/onboarding", status_code=303)

    @router.post("/onboarding/accept")
    def accept_grimoire(request: Request, revision: str = Form(...), grimoire_revision: str = Form(""),
                        draft: str = Form(...), attest_edits: bool = Form(False)):
        with source_lock:
            source_store, draft_store = writable(request)
            state, current = draft_store.read()
            state["draft"] = draft
            if current != revision or grimoire_revision != state["grimoire_revision"]:
                return render(request, state=state, revision=revision, status=409, error="Onboarding changed. Recover your submitted draft before reloading.")
            questions = acceptance_questions(state, draft, source_store.revision("master-resume.md"), attest_edits)
            if questions:
                return render(request, state=state, revision=revision, status=422, error="Resolve the review questions before accepting. " + " ".join(questions))
            try:
                source_store.save("grimoire.md", draft, grimoire_revision)
            except ConflictError:
                return render(request, state=state, revision=revision, status=409, error="The grimoire changed in another tab. Recover your submitted draft before reloading.")
            except ValueError as exc:
                return render(request, state=state, revision=revision, status=400, error=str(exc))
        return RedirectResponse("/onboarding?saved=true", status_code=303)

    return router
