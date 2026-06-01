# Conjurer web UI

A calm, editorial web app that walks a job seeker from a job description to a stitched,
submittable resume and cover letter, one grounded decision at a time.

The app is a **hexagonal agents application**: the editorial HTMX UI is the rendering layer, and
the AI agent sits behind a `GenerationPort` as a driven adapter (it never emits HTML). It runs in
two configurations, chosen by the `CONJURER_BACKEND` environment variable:

- **`fake` (default)** — served from fixtures in `app/data.py`, shaped exactly like the real
  pipeline's output. No API key, no network: ideal for design work and the test suite.
- **`live`** — the real engine. A `SdkGenerationPort` (Claude Agent SDK) loads the conjurer plugin
  in `../plugins/conjurer/`, chooses a strategic frame (the outline), and dispatches the
  `conjurer:variant-generator` subagent per unit to summon grounded variants. The deterministic
  conjurer scripts (`stitch`/`lint`/`export`) compose and check the documents.

Design rationale and the verified SDK contract live in `BACKEND.md` and `IMPLEMENTATION_PLAN.md`.

## Stack

- **FastAPI + Jinja2** — server-rendered pages; a composition root wires the repository, the
  generation port, and the run manager.
- **HTMX** — smooth navigation, plus polling the async "summoning" progress while a live run works.
  Vendored locally in `app/static/vendor/`, no CDN.
- **Hand-authored CSS** — design tokens in `app/static/css/app.css`. No utility framework, no build.
- **A little vanilla JS** — keyboard picking on the curation screen (`app/static/js/app.js`).
- **Claude Agent SDK** (`claude-agent-sdk`) — the live generation backend.

## Run

```
cd web
uv sync

# Design build (fixtures, no key):
uv run uvicorn app.main:app --reload --port 8400

# Live build (real generation):
cp .env.example .env          # then set ANTHROPIC_API_KEY in .env
export CONJURER_BACKEND=live
export CONJURER_WORKSPACE=/path/to/workspace   # grimoire.md, master-resume.md, applications/
uv run uvicorn app.main:app --reload --port 8400
```

Open http://127.0.0.1:8400 and walk the flow: Start → (summon) → Outline → Curate → Review → Export.

Auth: the live backend uses `ANTHROPIC_API_KEY`. If it is unset, the SDK falls back to your
authenticated `claude` CLI (fine for local dev, not the production auth path). From 2026-06-15,
Agent SDK usage on subscription plans draws from a separate monthly Agent SDK credit.

## Test

```
uv run pytest            # offline suite; enforces 100% line+branch coverage (see ../.claude/rules)
uv run pytest -m live    # the live integration test (needs auth; makes real API calls)
```

Coverage lives across `tests/` (routes, domain, ports, workspace_fs, composition, generation, runs,
live flow). The default run deselects the `live` marker.

## The flow

| Route | Screen | What it does |
|-------|--------|--------------|
| `/` | Start | Choose a master resume, paste the job description. |
| `POST /start` | (summon) | `fake`: straight to Outline. `live`: kicks off a background run and shows the summoning page, which polls `GET /generate/status` until generation is done. |
| `/outline` | Outline | The chosen strategic frame and the lines to tailor. |
| `/curate/{i}` | Curate | One line at a time: grounded variants, each with its evidence trace. Pick one (click or `1`–`4`), continue (`Enter`). |
| `/review` | Review | The stitched documents in reading typography, with the style-check (lint) results. In `live`, this stitches the picked variants into real `cover_letter.md`/`resume.md` and runs the grimoire linter over them; in `fake` it uses the in-memory lint. |
| `/export` | Export | PDF / Word / Markdown. In `live`, this runs `export_docs` and reports the written/skipped map per format; in `fake` it shows the static export options. |

## Design

The visual system (oxblood-on-white, editorial, Restrained color strategy) is documented in
`../DESIGN.md`. Strategy and audience live in `../PRODUCT.md`. The backend architecture (the agent
at the generation port, the ports/adapters, the async run model) is in `BACKEND.md`.
