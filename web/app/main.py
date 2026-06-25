# ABOUTME: FastAPI app serving the Conjurer pipeline UI (entry → outline → curate → review → export).
# ABOUTME: Server-rendered Jinja2 + HTMX. Picks live in a session-scoped SelectionStore behind a port.

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.lint import lint_cover_letter
from app.providers.fixtures import FixtureProvider
from app.selections import InMemorySelectionStore, SelectionStore

BASE = Path(__file__).parent

app = FastAPI(title="Conjurer")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

# Adapters behind the ports. Swapping FixtureProvider for a live Agent SDK
# adapter, or InMemorySelectionStore for a workspace-backed one, is the
# documented "replace one adapter" change — no route touches their internals.
provider = FixtureProvider()
get_application = provider.get_application
store: SelectionStore = InMemorySelectionStore()

SESSION_COOKIE = "cj_session"

# The five pipeline steps, in order, for the rail.
STEPS = [
    ("entry", "Start", "/"),
    ("outline", "Outline", "/outline"),
    ("curate", "Curate", "/curate"),
    ("review", "Review", "/review"),
    ("export", "Export", "/export"),
]


@app.middleware("http")
async def ensure_session(request: Request, call_next):
    """Give every browser a stable session id so picks are scoped to one run.

    Done in middleware (not a route dependency) so the cookie is set on the
    outgoing response no matter what type a route returns — including the
    RedirectResponses the curate flow leans on.
    """
    sid = request.cookies.get(SESSION_COOKIE)
    is_new = sid is None
    if is_new:
        sid = uuid4().hex
    request.state.session_id = sid
    response = await call_next(request)
    if is_new:
        response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return response


def session_id(request: Request) -> str:
    return request.state.session_id


def get_store() -> SelectionStore:
    return store


def _ctx(request: Request, active: str, **extra) -> dict:
    active_i = next((i for i, (key, _, _) in enumerate(STEPS) if key == active), 0)
    return {"request": request, "steps": STEPS, "active_step": active, "active_i": active_i, **extra}


@app.get("/", response_class=HTMLResponse)
def entry(request: Request):
    return templates.TemplateResponse(request, "entry.html", _ctx(request, "entry", app_data=get_application()))


@app.post("/start")
def start():
    # Mock: a real run would read the master resume + JD here.
    return RedirectResponse("/outline", status_code=303)


@app.get("/outline", response_class=HTMLResponse)
def outline(request: Request):
    return templates.TemplateResponse(request, "outline.html", _ctx(request, "outline", app_data=get_application()))


@app.get("/curate", response_class=HTMLResponse)
def curate_start():
    return RedirectResponse("/curate/0", status_code=303)


@app.get("/curate/{idx}", response_class=HTMLResponse)
def curate(
    request: Request,
    idx: int,
    sid: str = Depends(session_id),
    store: SelectionStore = Depends(get_store),
):
    data = get_application()
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
            selected=store.get(sid, unit.id),
            prev_idx=idx - 1 if idx > 0 else None,
        ),
    )


@app.post("/curate/{idx}")
def curate_pick(
    idx: int,
    variant_id: str = Form(...),
    sid: str = Depends(session_id),
    store: SelectionStore = Depends(get_store),
):
    data = get_application()
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
    sid: str = Depends(session_id),
    store: SelectionStore = Depends(get_store),
):
    data = get_application()
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
        _ctx(
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
def export(request: Request):
    return templates.TemplateResponse(request, "export.html", _ctx(request, "export", app_data=get_application()))


@app.post("/reset")
def reset(sid: str = Depends(session_id), store: SelectionStore = Depends(get_store)):
    store.clear(sid)
    return RedirectResponse("/", status_code=303)
