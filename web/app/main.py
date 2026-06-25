# ABOUTME: FastAPI app serving the Conjurer pipeline UI (entry → outline → curate → review → export).
# ABOUTME: Server-rendered Jinja2 + HTMX. Routes orchestrate; wiring is in deps.py, the rail in rail.py.

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.deps import ensure_session, get_application, get_store, session_id
from app.domain import Application
from app.lint import lint_cover_letter
from app.rail import template_context
from app.selections import SelectionStore

BASE = Path(__file__).parent

app = FastAPI(title="Conjurer")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.middleware("http")(ensure_session)
templates = Jinja2Templates(directory=str(BASE / "templates"))


@app.get("/", response_class=HTMLResponse)
def entry(request: Request, app_data: Application = Depends(get_application)):
    return templates.TemplateResponse(request, "entry.html", template_context(request, "entry", app_data=app_data))


@app.post("/start")
def start():
    # Mock: a real run would read the master resume + JD here.
    return RedirectResponse("/outline", status_code=303)


@app.get("/outline", response_class=HTMLResponse)
def outline(request: Request, app_data: Application = Depends(get_application)):
    return templates.TemplateResponse(request, "outline.html", template_context(request, "outline", app_data=app_data))


@app.get("/curate", response_class=HTMLResponse)
def curate_start():
    return RedirectResponse("/curate/0", status_code=303)


@app.get("/curate/{idx}", response_class=HTMLResponse)
def curate(
    request: Request,
    idx: int,
    data: Application = Depends(get_application),
    sid: str = Depends(session_id),
    store: SelectionStore = Depends(get_store),
):
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
            selected=store.get(sid, unit.id),
            prev_idx=idx - 1 if idx > 0 else None,
        ),
    )


@app.post("/curate/{idx}")
def curate_pick(
    idx: int,
    variant_id: str = Form(...),
    data: Application = Depends(get_application),
    sid: str = Depends(session_id),
    store: SelectionStore = Depends(get_store),
):
    units = data.units
    if not 0 <= idx < len(units):
        raise HTTPException(status_code=404, detail="No such line to curate.")
    unit = units[idx]
    # Only store a variant that actually belongs to this unit. Rejecting an
    # unknown id here is what keeps the review screen from later attributing
    # content to the user that they never chose.
    if variant_id not in unit.variant_ids:
        raise HTTPException(status_code=422, detail="That variant isn't an option for this line.")
    store.set(sid, unit.id, variant_id)
    nxt = idx + 1
    if nxt >= len(units):
        return RedirectResponse("/review", status_code=303)
    return RedirectResponse(f"/curate/{nxt}", status_code=303)


@app.get("/review", response_class=HTMLResponse)
def review(
    request: Request,
    data: Application = Depends(get_application),
    sid: str = Depends(session_id),
    store: SelectionStore = Depends(get_store),
):
    picks = store.all(sid)
    chosen = [(unit, unit.variant(picks.get(unit.id))) for unit in data.units]
    cover = [(u, v) for (u, v) in chosen if u.kind == "cover_paragraph"]
    bullets = [(u, v) for (u, v) in chosen if u.kind == "resume_bullet"]
    # Complete means every unit has a stored selection that is actually one of
    # its variants — not merely that the store has enough entries.
    complete = all(picks.get(u.id) in u.variant_ids for u in data.units)
    cover_text = "\n\n".join(v.text for (_, v) in cover)
    return templates.TemplateResponse(
        request,
        "review.html",
        template_context(
            request,
            "review",
            app_data=data,
            cover=cover,
            bullets=bullets,
            lint=lint_cover_letter(cover_text),
            complete=complete,
        ),
    )


@app.get("/export", response_class=HTMLResponse)
def export(request: Request, app_data: Application = Depends(get_application)):
    return templates.TemplateResponse(request, "export.html", template_context(request, "export", app_data=app_data))


@app.post("/reset")
def reset(sid: str = Depends(session_id), store: SelectionStore = Depends(get_store)):
    store.clear(sid)
    return RedirectResponse("/", status_code=303)
