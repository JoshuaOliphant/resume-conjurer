# Backend Architecture

How the Conjurer web app is driven as a **hexagonal agents** application. Product strategy
lives in [../PRODUCT.md](../PRODUCT.md); the visual system in [../DESIGN.md](../DESIGN.md). This
doc covers only the backend: where the AI agent sits, what the ports are, and what it takes to
move from the current mock to a live engine.

## Thesis: the agent sits at the generation port, not the rendering layer

The standard hexagonal-agents pattern puts an AI agent at the **rendering** port — it receives a
user message and emits HTML, becoming the UI. That is exactly wrong for this product. PRODUCT.md's
first anti-reference is *"Generic AI-chat UI … nothing that reads as a ChatGPT wrapper,"* and the
UI is a deliberate, hand-authored editorial design: semantic HTML, ARIA roles, `:focus-visible`
rings, keyboard picking, a tuned typographic scale. Per-turn LLM-generated HTML would be slow,
non-deterministic, and corrosive to "calm under pressure / the document is the hero."

So we keep the architecture and the core principle of the pattern, and relocate the agent:

- **Architecture preserved** — ports and adapters, the agent quarantined behind a typed contract.
- **Principle preserved** — *semantic late binding*: the agent still interprets the job
  description and evidence at runtime to choose a strategic frame and summon grounded variants.
  That interpretation is the whole product.
- **Location changed** — the agent is a **driven adapter behind a generation port**, not the
  driving UI adapter. The deliberate Jinja2 + HTMX UI stays as the driving adapter, unchanged.

This is a faithful application of hexagonal agents to a product whose UI must not be a chat box,
not a rejection of it.

## The contracts already exist

The largest de-risking fact: this is not a hexagon to build from scratch. The seams are already
cut, because the mock UI was shaped to the real pipeline's output.

| Already in the repo | Is actually the… |
|---|---|
| `app/data.py` frozen dataclasses — `Evidence`, `Variant`, `Unit`, `Frame`, `Application`, `LintCheck` | **Domain model** the core and ports speak in |
| `outline.json` schema (`plugins/.../references/pipeline.md`) | **Outline port contract** |
| The `## Unit:` / `### Variant N` block format (`variant-generator.md`) | **Variant port contract** |
| `get_application()`, `lint_results()` in `data.py` | **Stub adapters** we replace |
| `stitch.py`, `composer.py`, `lint.py`, `export_docs.py` | **Driven adapters, ready-made** (pure functions over a workspace dir) |

"Wire the backend" therefore means: replace one mock adapter (`get_application`) with two real
ones — a workspace repository and a generation adapter — and let the deterministic scripts do the
rest. The domain model and the wire formats do not change.

## The hexagon for this app

```
                 Browser — the deliberate editorial UI (Jinja2 + HTMX)
                 NOT agent-generated; PRODUCT.md anti-reference #1
                          │  HTTP  (driving / primary adapter)
                          ▼
            ┌─────────────────────────────────────────────┐
            │     Application core (pipeline state machine) │
            │   entry → outline → curate → review → export  │
            └─────────────────────────────────────────────┘
                          │ depends on ports (interfaces) ↓
   ┌──────────────────────┼───────────────────────────────────────┐
   │ GenerationPort        │ CompositionPort         │ WorkspaceRepo │
   │  outline(inputs)      │  stitch(picks)          │  grimoire     │
   │  variants(unit, n)    │  lint(docs)             │  master_resume│
   │       │               │  export(docs, fmts)     │  jd / evidence│
   │       ▼  (driven)     │       ▼ (driven)        │  outline      │
   │  Claude Agent SDK     │  stitch/composer/lint/  │  variants+picks│
   │  loads the conjurer   │  export_docs scripts    │       ▼        │
   │  plugin + variant-    │  (already pure, today)  │  filesystem    │
   │  generator subagent   │                         │  adapter       │
   └───────────────────────────────────────────────────────────────┘
```

Only the **GenerationPort** is new engineering. The CompositionPort wraps scripts that already
exist and already operate on a workspace directory. The WorkspaceRepository is filesystem
plumbing over the `applications/<slug>/` layout the CLI pipeline already writes.

## Which steps are agentic vs deterministic

The conjurer pipeline cleanly splits, and the split is the port boundary:

**Agentic (GenerationPort — requires Claude, judgment, generation):**
- **Outline** — read grimoire + master resume + JD + evidence; choose *one* strategic frame
  (scale / friction / conviction / multiplier); design the unit skeleton → `outline.json`.
- **Variants** — for each unit, generate N=4 grounded variants citing evidence, via the
  `variant-generator` subagent, fanned out in parallel → `variants.md`.

**Deterministic (CompositionPort — pure scripts, no LLM):**
- **Stitch** (`stitch.py` + `composer.py`) — parse picks, slot bullets into the master-resume
  structure, assemble `cover_letter.md` + `resume.md`.
- **Lint** (`lint.py`) — regex/counting grimoire style checks.
- **Export** (`export_docs.py`) — pandoc to PDF/docx, graceful fallback to markdown.

**Human (mediated by the UI, not the agent):**
- **Curate** — the user exercises taste over variants. The agent does *not* pick. The UI's job is
  to sharpen recognition; the human decides.

## The concern with teeth: latency and state

The variant step is a 6-unit × 4-variant fan-out — roughly **30–60s** of generation. The current
backend cannot survive that as written:

- Routes are synchronous request/response; a 60s blocking POST is unacceptable.
- `SELECTIONS` is a module-level in-memory dict — single-user, lost on reload, not scoped to a run.

What the live backend needs:

1. **Async generation + progress UI.** Kick outline/variants off as a background task; the UI
   shows a working state and polls (HTMX `hx-trigger="every 2s"`) or streams (SSE) until ready.
   This is *on-brand*, not a compromise: the loading state is literally the product's thesis —
   *"summon abundance, then recognize the right variant."* The wait is the summoning. The
   fine-grained adapter (below) makes this progress *per-unit*: "summoned 3 of 6 lines."
2. **Picks persisted to `variants.md`.** Curation must write `- [x] Pick` back into `variants.md`
   (exactly one per unit), because that file *is* `stitch.py`'s input. Persisting picks there —
   not in an in-memory dict — is what unifies the web and CLI pipelines on a single contract: the
   same workspace, stitched by the same script, however the picks were made.
3. **A run = a workspace.** State lives in `applications/<slug>/` on disk (outline, variants,
   picks, stitched docs), not in process memory. The filesystem is the source of truth, which
   also makes the web and CLI flows interchangeable on the same data.

## SDK note (verified): reuse does not force duplication

A concern with fine-grained ports is re-implementing the prompts already tuned in `SKILL.md` and
`variant-generator.md`. The Python Agent SDK removes that risk: `ClaudeAgentOptions` accepts
`plugins=[…]`, `skills=["conjurer"]` (or `"all"`), and `agents={…}`. The backend can **load the
existing conjurer plugin** — same skill, same `variant-generator` subagent — and run it against a
workspace via `cwd`. The choice below is about *granularity of control*, not *whether we duplicate
logic*; either way the tuned prompts are reused, not copied.

## Decision: fine-grained per-step ports, on a persistent session

**Chosen: fine-grained.** The web app calls the SDK once per pipeline step, loading the conjurer
plugin so it reuses the skill's outline logic and dispatches the existing `variant-generator`
subagent per unit. This gives per-unit progress and tight control over sequencing and retries.

The reason this is the right call here — and not the heavier option it would normally be — is
**prompt caching**, which the conjurer plugin is built to exploit:

- **One persistent `ClaudeSDKClient`, connected once and reused** across every step of a run. The
  large static context (grimoire, master resume, skill instructions) is sent once and stays warm
  in the prompt cache for outline and every variant call after it. Recreating the client per
  request, or re-reading context per step, would throw the cache away — so client lifecycle is a
  load-bearing design rule, not an optimization.
- **The variant fan-out shares a cacheable prefix.** Each `variant-generator` dispatch receives
  the same grimoire + master resume + evidence + outline and differs only in the per-unit tail.
  That common prefix caches across the parallel unit calls; only the small tail is uncached.

So the usual fine-grained tax — re-paying to ship the big context every step — mostly does not
apply. We get per-unit streaming progress *and* keep generation cheap.

The cost we do accept: the fan-out, sequencing, and structured-output extraction orchestration
now lives in web-side Python and must be kept in step with the CLI pipeline's behavior. The
contracts (`outline.json` schema, the `## Unit:` block) are the guard against drift — both the web
adapter and the CLI must keep producing and consuming exactly those.

## What not to do

- **Do not run the skill's `init_hexagonal_app.py` scaffolder.** The app exists and is carefully
  built; a fresh scaffold would fight it (and would assume the agent-generates-HTML model we are
  explicitly not using). Adapt in place.
- **Do not move the UI behind the agent.** The rendering layer stays deterministic and
  hand-authored. The agent never emits HTML.
- **Do not introduce a second source of truth for picks.** `variants.md` is it.

## Minimal change set (when implementation is greenlit)

1. `WorkspaceRepository` (filesystem adapter): resolve a workspace + `applications/<slug>/`, read
   grimoire / master-resume / jd / evidence, read+write `outline.json` and `variants.md`
   (including toggling `- [x] Pick`).
2. `GenerationPort` + Agent SDK adapter (fine-grained): a long-lived adapter holding one
   `ClaudeSDKClient`, connected once and reused, with the conjurer plugin loaded. `outline()` is
   one step call; `variants()` dispatches the `variant-generator` subagent per unit (parallel,
   shared cached prefix) and extracts `## Unit:` blocks via structured output. Runs as a
   background task; per-unit completion drives the progress UI.
3. `CompositionPort`: thin wrappers over `stitch.py` / `lint.py` / `export_docs.py`
   (import the functions; they are already pure).
4. Rewrite `data.py`'s `get_application()` to hydrate the domain dataclasses from the workspace
   files instead of fixtures — the dataclasses themselves stay.
5. Replace `SELECTIONS` with pick-persistence to `variants.md`; add the async generation route
   pair (kick-off + poll/SSE) and a working-state partial for the rail's Outline/Curate steps.
6. Tests: a fake `GenerationPort` (deterministic fixtures — the current mock becomes the test
   double) so route/flow tests stay fast and offline; one integration test that runs the real
   adapter against a tiny fixture workspace.
