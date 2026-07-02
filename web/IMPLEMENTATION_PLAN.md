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

## Spike results — adapter contract pinned (verified live 2026-05-31)

A throwaway spike (`spike_generation.py`, since deleted) ran the real SDK against the fixture
workspace and **verified all three inferred assumptions**. The adapter contract below is now
empirical, not doc-inferred:

- **`output_format` is an options-level field, fixed per client** — `client.query(prompt,
  session_id)` takes NO per-call options (confirmed in `client.py`). So outline and variants need
  **two clients** (different/absent `output_format`), not one.
- **Outline client:** `output_format={"type":"json_schema","schema": OUTLINE_SCHEMA}` →
  `ResultMessage.structured_output` is a valid outline dict. The agent does **not** auto-run the
  pipeline and does **not** write `outline.json` — *we* persist it from `structured_output`.
- **Variants client (no `output_format`):** instruct it to use the `conjurer:variant-generator`
  subagent (plugin-qualified name) via the `Agent` tool; it returns the native `## Unit:` block
  (with `master-resume.md L16`-style citations and `*Axis:*` lines). Extract from the `## Unit:`
  marker (strip the agent's surrounding chatter); this is the exact format `stitch.py` parses, so
  it is reuse, not invention.
- **Caching confirmed:** `cache_read_input_tokens` = 114571 (outline) and 21905 (2nd variant call)
  → the persistent-client design holds. Fine-grained per-unit calls are cheap.
- **Fan-out:** start sequential per-unit on the variants client (cache hits across units, natural
  "summoned 3 of 6" progress). Parallel dispatch is a later optimization; same `variants.md` either
  way.

### Verified config (the adapter's `ClaudeAgentOptions`)

The two clients are asymmetric on permissions — do NOT put `bypassPermissions` in a shared
`base`, or it leaks onto the variant client and disables its prompt-injection guard.

```python
base = dict(
    cwd=str(workspace),
    plugins=[{"type": "local", "path": str(repo / "plugins" / "conjurer")}],
    setting_sources=[],            # isolate from THIS repo's .claude hooks/settings
    model="claude-sonnet-4-6",
    # NOTE: no permission_mode here — each client sets its own (see below).
)
# Outline: a `tools` allowlist removes mutating tools entirely, so bypass is safe.
outline_opts = ClaudeAgentOptions(
    tools=["Read","Glob","Grep"], allowed_tools=["Read","Glob","Grep"],
    permission_mode="bypassPermissions",
    output_format={"type":"json_schema","schema": OUTLINE_SCHEMA}, **base)
# Variant: cannot use a `tools` allowlist (breaks subagent dispatch), so it does NOT bypass
# and instead supplies a deny-by-default `can_use_tool` guard (guard_variant_tool).
variant_opts = ClaudeAgentOptions(
    allowed_tools=["Read","Glob","Grep","Agent"], can_use_tool=guard_variant_tool, **base)
```

### Post-build verification (agent-sdk-verifier-py) — resolved

- **Least privilege + prompt-injection defense.** `allowed_tools` only auto-approves; `tools`
  restricts the available toolset. The **outline** client sets `tools=["Read","Glob","Grep"]` and
  may bypass (no mutating tools exist for it). The **variant** client cannot use a `tools` allowlist
  (it disables plugin subagent dispatch — variants come back empty, verified live), so instead it
  **drops `bypassPermissions` and supplies a deny-by-default `can_use_tool` guard**
  (`guard_variant_tool`) that allows ONLY `{Read,Glob,Grep,Agent,Task}` and denies everything else
  — including unknown built-ins and any `mcp__*` tool. This closes the prompt-injection →
  RCE/exfiltration path from a hostile pasted JD while keeping subagent dispatch. The allowlist is
  enforced both via `allowed_tools` (auto-approval) and via the callback. Verified live: dispatch
  and the cache hit still work under the guard. (Raised by the push security review; fixed, not
  deferred.)
- **Resource lifecycle.** `aclose()` is part of the `GenerationPort` Protocol; `RunManager.aclose()`
  closes the generation port so the persistent variant client's subprocess is not orphaned on
  shutdown/cancellation. The fake's `aclose()` is a no-op.
- **skills= not used.** Loading the plugin via `plugins=[...]` is sufficient to dispatch
  `conjurer:variant-generator`; the earlier `skills=["conjurer"]` note is unnecessary.

### Auth / env gotcha (worktrees)

`.env` is per-worktree (gitignored). The key lives in each checkout's `web/.env` separately. When
absent, the SDK silently falls back to the local `claude` CLI's subscription auth — so a passing
run does **not** prove API-key auth. The live test must therefore skip on *both* signals: no
`ANTHROPIC_API_KEY` AND no authenticated CLI. Production auth is `ANTHROPIC_API_KEY` only.

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
Define `OUTLINE_SCHEMA` (mirrors `references/pipeline.md`). Build the SDK adapter: persistent
`ClaudeSDKClient`, plugin loaded, `cwd=workspace`, least-privilege tools. `outline()` →
structured_output; `variants(unit)` → the variant-generator's native `## Unit:` block, parsed by
`variants_from_block` (see the Spike Results section for the verified contract). *Tests:*
route/flow tests run entirely on `generation_fake` (no network); Protocol conformance shared by
both.

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

## Progress (live milestone)

Phases 0–5 complete and committed; the offline suite is at 100% line+branch; the
`@pytest.mark.live` test passes against the real API (valid outline, grounded variants,
`cache_read_input_tokens > 0`). Phase 4 (async runs + UI wiring) is done: `runs.py` orchestrates
the background run, the summoning page polls `GET /generate/status`, and picks persist to
`variants.md`. In the live config, `/review` stitches the picked variants into real
`cover_letter.md`/`resume.md` and runs the grimoire linter over them (via `ScriptCompositionPort`),
and `/export` runs `export_docs` and reports the written/skipped map per format.

### Phase 4 design decision (offline display path)

The app always uses a `WorkspaceRepository` + a `GenerationPort`, chosen by a composition root
keyed on `CONJURER_BACKEND` (default `fake`). To preserve the shipped editorial UI and the 20
route tests *unchanged* offline, the default config pairs a **fake repository** that serves the
existing `data.get_application()` (rich, resolved evidence) and an in-memory pick store with the
`FakeGenerationPort`. The `live` config pairs `FsWorkspaceRepository` + `SdkGenerationPort`. The
async generation flow (`runs.py`) is tested offline with `FakeGenerationPort` writing into a temp
`FsWorkspaceRepository`, so it reaches 100% without the API. This keeps the UI calm and the
evidence rich offline while the real path stays the single source of truth on disk.

## Decisions

- **Run model: single-user, fixed workspace — but built to extend.** One workspace dir (grimoire +
  master-resume + `applications/`), resolved in exactly one place and *injected* into the ports
  (never hardcoded inside adapters). `runs.py` keys run state by `slug` today, but through an
  indirection (a `RunStore`/`WorkspaceResolver` seam) so adding per-session/per-user scoping later
  is a new resolver, not a rewrite. No auth in this cut; do not bake single-user assumptions into
  the domain model, the repository signatures, or route handlers.
