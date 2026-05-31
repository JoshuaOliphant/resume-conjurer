# Conjurer web UI

A production-shaped front-end for the Conjurer pipeline: a calm, editorial web app that walks a
job seeker from a job description to a stitched, submittable resume and cover letter, one grounded
decision at a time.

This is a **design build with mock data**. The real engine is Claude running inside Claude Code
(see the plugin in `../plugins/conjurer/`), so there is no live generation here. Everything is
served from fixtures in `app/data.py`, shaped exactly like the real pipeline's output so the visual
and interaction design transfer directly if the app is ever wired to a backend.

## Stack

- **FastAPI + Jinja2** — server-rendered pages.
- **HTMX** (`hx-boost`) — smooth navigation without a client framework. Vendored locally in
  `app/static/vendor/`, no CDN.
- **Hand-authored CSS** — design tokens in `app/static/css/app.css`. No utility framework, no
  build step.
- **A little vanilla JS** — keyboard picking on the curation screen (`app/static/js/app.js`).
  The screen works fully without it.

## Run

```
cd web
uv sync
uv run uvicorn app.main:app --reload --port 8400
```

Open http://127.0.0.1:8400 and walk the flow: Start → Outline → Curate → Review → Export.

## Test

```
uv run pytest
```

Route and flow coverage lives in `tests/test_routes.py`.

## The flow

| Route | Screen | What it does |
|-------|--------|--------------|
| `/` | Start | Choose a master resume, paste the job description. |
| `/outline` | Outline | Shows the chosen strategic frame and the lines to tailor. |
| `/curate/{i}` | Curate | One line at a time: 4 grounded variants, each with its evidence trace. Pick one (click or `1`–`4`), continue (`Enter`). |
| `/review` | Review | The stitched documents in reading typography, with the style-check (lint) results. |
| `/export` | Export | PDF / Word / Markdown. |

## Design

The visual system (oxblood-on-white, editorial, Restrained color strategy) is documented in
`../DESIGN.md`. Strategy and audience live in `../PRODUCT.md`.
