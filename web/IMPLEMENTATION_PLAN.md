# Implementation Plan — SDK-driven generation backend

Wiring the conjurer-web FastAPI app to a live engine, per [BACKEND.md](BACKEND.md): the agent is a
**driven adapter behind a generation port**, the editorial HTMX UI stays the driving adapter.
Branch: `feature/conjurer-backend-generation-port`.

All SDK facts below were read from the official reference on 2026-05-31:
`https://code.claude.com/docs/en/agent-sdk/overview` and `.../python`, cross-checked against the
SDK's `types.py`. Pin **`claude-agent-sdk==0.2.87`** (latest; requires Python ≥3.10 — the app is
≥3.11).

> Credit note from the docs: from **2026-06-15**, Agent SDK / `claude -p` usage on subscription
> plans draws from a separate monthly Agent SDK credit. Auth is `ANTHROPIC_API_KEY` (claude.ai
> login is not permitted for SDK-backed products). Surface this in the README.

## The SDK surface we will use (verified)

| Need | SDK mechanism |
| --- | --- |
| Persistent session so the static context stays warm in prompt cache | `async with ClaudeSDKClient(options) as client:` then repeated `await client.query(...)` / `async for m in client.receive_response()`. **Connect once, reuse** — the load-bearing rule from BACKEND.md. |
| Reuse the existing conjurer skill + `variant-generator` subagent (no prompt duplication) | `ClaudeAgentOptions(plugins=[{"type":"local","path":"<repo>/plugins/conjurer"}], skills=["conjurer"])` |
| Ground the agent against the workspace files | `cwd="<workspace>"` so `Read`/`Glob` resolve `grimoire.md`, `master-resume.md`, `applications/<slug>/…` |
| Outline as a validated contract | `output_format={"type":"json_schema","schema": OUTLINE_SCHEMA}` → read `ResultMessage.structured_output` (OUTLINE_SCHEMA mirrors `references/pipeline.md` exactly) |
| Per-unit variants | one query per unit (see fork below); structured output or the `## Unit:` block format from `variant-generator.md` |
| Parallel fan-out option | `agents=` / loaded plugin subagent invoked via the `Agent` tool (`"Agent"` in `allowed_tools`); subagent messages carry `parent_tool_use_id` for per-unit progress |
| Least privilege | `allowed_tools=["Read","Glob","Grep"]` (+ `"Agent"` only if dispatching subagents); `permission_mode` + a `can_use_tool` handler that confines reads to the workspace |
| Verify caching actually happens | assert `ResultMessage.usage` shows `cache_read_input_tokens > 0` on the 2nd+ call |
| Cost guardrails | `max_budget_usd`, `max_turns` per run |

## Module layout (adapt in place — do NOT scaffold a new app)

```
web/app/
  domain.py          # the dataclasses from data.py, promoted to the shared domain model
  ports.py           # Protocols: GenerationPort, CompositionPort, WorkspaceRepository
  adapters/
    workspace_fs.py  # WorkspaceRepository over applications/<slug>/ (read+write outline/variants/picks)
    generation_sdk.py# GenerationPort via ClaudeSDKClient (the only new "agent" code)
    composition.py   # CompositionPort: thin wrappers importing stitch/lint/export_docs
    generation_fake.py # deterministic GenerationPort for tests (today's data.py fixtures become this)
  runs.py            # async run/job state: kicks generation off, tracks per-unit progress
  main.py            # FastAPI: existing routes + async kickoff + poll/SSE partial
  data.py            # deleted once domain.py + generation_fake.py absorb it
```

`stitch.py` / `composer.py` / `lint.py` / `export_docs.py` stay in the plugin and are imported by
`composition.py` (they are already pure functions over a workspace dir).

## Two internal forks (resolved, doc-grounded)

**Outline — let the skill write the file, or use `output_format`?**
→ **`output_format` with `OUTLINE_SCHEMA`.** The SDK validates and returns `structured_output`; the
WorkspaceRepository persists `outline.json`. Keeps the exact contract, removes parse/repair code.

**Variants fan-out — parallel subagents in one query, or orchestrator-driven per-unit queries?**
→ **Start orchestrator-driven, sequential per-unit on the persistent client.** Each unit is one
`client.query(...)` carrying the same big prefix (grimoire + master resume + evidence + outline),
so calls 2..N hit prompt cache; only the per-unit tail is uncached. Gives clean per-unit
`structured_output` capture and natural "summoned 3 of 6" progress. ~30–50s for 6 units, matching
the async UX. *Optimization, only if the wait feels dead:* graduate to parallel `variant-generator`
subagent dispatch (single query, `Agent` tool) or a small pool of concurrent clients. Nothing else
changes — both write the same `variants.md`.

## Phased TDD task breakdown

Each phase: failing test first, minimal code to green, refactor. PostToolUse validation runs `vet`.

**Phase 0 — Deps & skeleton.** `uv add claude-agent-sdk==0.2.87`; `.env.example` (+ `.env` in
`.gitignore`); README run/auth/credit note. Define `ports.py` Protocols and `domain.py` (move the
dataclasses out of `data.py`, unchanged). *Test:* import + Protocol conformance of the fake.

**Phase 1 — WorkspaceRepository (`workspace_fs.py`).** Read grimoire/master-resume/jd/evidence;
read+write `outline.json`; parse `variants.md` into the domain `Unit`/`Variant`/`Evidence` model;
toggle exactly one `- [x] Pick` per unit. *Tests:* round-trip against a tiny fixture workspace
under `tests/fixtures/`; pick-toggle invariant (exactly one pick/unit); hydrate `Application`.

**Phase 2 — CompositionPort (`composition.py`).** Wrap `stitch`/`lint`/`export_docs`. *Tests:*
stitch a fixture `variants.md` with picks → expected `cover_letter.md`/`resume.md`; lint findings
map to `LintCheck`. (Mostly exercises existing, tested scripts.)

**Phase 3 — GenerationPort, offline-testable (`generation_sdk.py` + `generation_fake.py`).**
Define `OUTLINE_SCHEMA` (mirrors `references/pipeline.md`) and `VARIANT_SCHEMA`. Build the SDK
adapter: persistent `ClaudeSDKClient`, plugin+skill loaded, `cwd=workspace`, least-privilege tools.
`outline()` → structured_output; `variants(unit)` → structured variants. *Tests:* route/flow tests
run entirely on `generation_fake` (no network); Protocol conformance shared by both.

**Phase 4 — Async runs + UI wiring (`runs.py`, `main.py`).** Replace `SELECTIONS` with
pick-persistence to `variants.md` via the repository. Add the kickoff route (background task) + a
poll (`hx-trigger="every 2s"`) or SSE progress partial for the rail's Outline/Curate steps. Rewrite
`get_application()` to hydrate from the workspace. *Tests:* kickoff returns a working state; poll
transitions working→ready; picks persist and survive reload; full flow Start→Export on the fake.

**Phase 5 — Live integration (network, opt-in).** One integration test marked `@pytest.mark.live`
(skipped without `ANTHROPIC_API_KEY`): run the real adapter against the tiny fixture workspace;
assert outline validates against `OUTLINE_SCHEMA`, variants cite only in-pool evidence, **and the
2nd per-unit call shows `usage.cache_read_input_tokens > 0`** (proves the persistent-client cache
design). Manual smoke: `uv run uvicorn app.main:app --reload --port 8400`, walk the flow against a
real workspace.

## Verification & guardrails

- Run the **`agent-sdk-verifier-py`** agent after Phase 3/4 to validate SDK usage against the docs.
- `vet` after each logical unit (PostToolUse).
- Claim discipline is enforced structurally: variants may cite only evidence IDs the repository
  loaded from the workspace — the UI can render no trace that isn't in the pool (today's invariant,
  preserved).
- Least privilege: `allowed_tools` limited to read/search (+`Agent` only if subagent fan-out);
  `can_use_tool` confines file reads to the workspace `cwd`.

## Decisions

- **Run model: single-user, fixed workspace — but built to extend.** One workspace dir (grimoire +
  master-resume + `applications/`), resolved in exactly one place and *injected* into the ports
  (never hardcoded inside adapters). `runs.py` keys run state by `slug` today, but through an
  indirection (a `RunStore`/`WorkspaceResolver` seam) so adding per-session/per-user scoping later
  is a new resolver, not a rewrite. No auth in this cut; do not bake single-user assumptions into
  the domain model, the repository signatures, or route handlers.
