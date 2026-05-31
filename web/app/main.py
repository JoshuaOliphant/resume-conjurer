# ABOUTME: FastAPI app serving the Conjurer pipeline UI (entry → outline → curate → review → export).
# ABOUTME: Server-rendered Jinja2 + HTMX. Selections held in a single-user in-memory store (mock).

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.data import get_application, lint_results

BASE = Path(__file__).parent

app = FastAPI(title="Conjurer")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

# Single-user mock store: unit_id -> chosen variant_id. A real build would scope
# this to a session or persist it; here it just lets the flow remember picks.
SELECTIONS: dict[str, str] = {}

# The five pipeline steps, in order, for the rail.
STEPS = [
    ("entry", "Start", "/"),
    ("outline", "Outline", "/outline"),
    ("curate", "Curate", "/curate"),
    ("review", "Review", "/review"),
    ("export", "Export", "/export"),
]


def _ctx(request: Request, active: str, **extra) -> dict:
    return {"request": request, "steps": STEPS, "active_step": active, **extra}


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
def curate(request: Request, idx: int):
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
            selected=SELECTIONS.get(unit.id),
            prev_idx=idx - 1 if idx > 0 else None,
        ),
    )


@app.post("/curate/{idx}")
def curate_pick(idx: int, variant_id: str = Form(...)):
    data = get_application()
    units = data.units
    if 0 <= idx < len(units):
        SELECTIONS[units[idx].id] = variant_id
    nxt = idx + 1
    if nxt >= len(units):
        return RedirectResponse("/review", status_code=303)
    return RedirectResponse(f"/curate/{nxt}", status_code=303)


@app.get("/review", response_class=HTMLResponse)
def review(request: Request):
    data = get_application()
    chosen = []
    for unit in data.units:
        vid = SELECTIONS.get(unit.id)
        variant = next((v for v in unit.variants if v.id == vid), unit.variants[0])
        chosen.append((unit, variant))
    cover = [(u, v) for (u, v) in chosen if u.kind == "cover_paragraph"]
    bullets = [(u, v) for (u, v) in chosen if u.kind == "resume_bullet"]
    return templates.TemplateResponse(
        request,
        "review.html",
        _ctx(
            request,
            "review",
            app_data=data,
            cover=cover,
            bullets=bullets,
            lint=lint_results(),
            complete=len(SELECTIONS) >= len(data.units),
        ),
    )


@app.get("/export", response_class=HTMLResponse)
def export(request: Request):
    return templates.TemplateResponse(request, "export.html", _ctx(request, "export", app_data=get_application()))


@app.post("/reset")
def reset():
    SELECTIONS.clear()
    return RedirectResponse("/", status_code=303)
