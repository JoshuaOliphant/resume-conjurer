# resume-conjurer

Agent guidance for this repo. `CLAUDE.md` points here; this is the real file.

## Two deliverables, one set of on-disk contracts

- **`plugins/conjurer/`** — the Claude Code plugin. `scripts/` is pure stdlib, run with bare
  `python3`, no dependencies. Generation is not code: Claude follows `skills/conjurer/SKILL.md`
  and dispatches the `agents/variant-generator.md` subagent. No API key.
- **`web/`** — a FastAPI app running the same pipeline for a browser. Separate uv project,
  separate lockfile, imports the plugin's scripts rather than reimplementing them.

Both sides read and write the same files in `applications/<slug>/`, and the wire formats are the
contract that keeps them interchangeable:

- `outline.json` — schema in `plugins/conjurer/skills/conjurer/references/pipeline.md`, mirrored
  as `OUTLINE_SCHEMA` in `web/app/schemas.py`.
- `variants.md` — the `## Unit:` / `### Variant N` block format from `agents/variant-generator.md`.
  `stitch.py` parses it, so it is also **the single source of truth for the user's picks**
  (`- [x] Pick`, exactly one per unit). Never introduce a second pick store.

Change either format and you must change it in both places, or the CLI and web flows silently
diverge on the same workspace.

## Commands

Plugin scripts (repo root):

```
uv run pytest
```

Web app (`cd web` first):

```
uv sync
uv run pytest                                   # the gate: 154 tests, 100% line+branch, deselects `live`
uv run pytest tests/test_domain.py -q --no-cov  # single file — see below
uv run pytest -m live                           # real API calls; needs auth
uv run uvicorn app.main:app --reload --port 8400
```

`--no-cov` is not optional on a partial run. Coverage is in `addopts` with `fail_under = 100`, so
`uv run pytest tests/test_domain.py` exits non-zero reporting `FAIL Required test coverage of
100.0% not reached` even when every test in the file passes. The full-suite rule is in
`.claude/rules/testing.md`.

Lint and types are ad hoc — no config is committed and neither is a dependency:
`uvx ruff check .`, `uvx ty check`.

There is no CI. A green suite is only as good as the last person who ran it.

## Backend configuration

The composition root is `web/app/deps.py`, keyed on two env vars. Routes take ports and never name
a concrete adapter, so switching backends is a one-line change there.

| `CONJURER_BACKEND` | Repository | Generation | Composition |
|---|---|---|---|
| `fake` (default) | `FakeWorkspaceRepository` (fixtures in `app/data.py`, in-memory picks) | `FakeGenerationPort` | `None` — `/review` uses the in-memory lint, `/export` is static |
| `live` | `FsWorkspaceRepository` | `SdkGenerationPort` | `ScriptCompositionPort` — real stitch/lint/export |

`live` additionally requires `CONJURER_WORKSPACE` pointing at a directory with `grimoire.md`,
`master-resume.md`, and `applications/`. `workspace_root()` raises rather than guessing: a silent
fallback used to write generated output into the tracked test fixtures.

The whole offline suite runs on the `fake` pair, which is why it reaches 100% with no network.

## Architecture: the agent sits at the generation port

The standard hexagonal-agents pattern puts an agent at the *rendering* port, emitting HTML. This
app deliberately does not, and that inversion is the single most important thing to preserve.
`PRODUCT.md`'s first anti-reference is "nothing that reads as a ChatGPT wrapper"; the Jinja2 + HTMX
UI is hand-authored down to the focus rings and keyboard picking. **The agent never emits HTML.**

Ports live in `web/app/ports.py` as Protocols — `GenerationPort` (agentic: outline, variants),
`CompositionPort` (deterministic: stitch, lint, export — thin wrappers importing the plugin's
scripts through a `sys.path` insert), `WorkspaceRepository` (filesystem plumbing). Curation is
neither: the human picks, mediated by the UI.

Rationale in `web/BACKEND.md`; the empirically verified SDK contract in
`web/IMPLEMENTATION_PLAN.md`.

### Constraints in `generation_sdk.py` that look like mistakes and are not

- **Two `ClaudeSDKClient`s, not one.** `output_format` is an options-level field fixed per client
  and `client.query()` takes no per-call options, so the outline client (JSON schema output) and
  the variant client (native `## Unit:` blocks) cannot be the same object.
- **The clients are asymmetric on permissions.** The outline client sets a `tools` allowlist, which
  removes mutating tools entirely, so `permission_mode="bypassPermissions"` is safe there. The
  variant client **cannot** use a `tools` allowlist — it breaks plugin subagent dispatch and
  variants come back empty — so it drops bypass and supplies the deny-by-default `can_use_tool`
  guard instead. Do not hoist `bypassPermissions` into the shared `base` dict; it would leak onto
  the variant client and disable its prompt-injection defense against a hostile pasted JD.
- **The variant client is created once, `connect()`ed, and reused across every unit** (built
  lazily on first use, held on `self._variant_client`). The large static context (grimoire, master
  resume, skill instructions) stays warm in the prompt cache, so per-unit calls are cheap because
  they share the cached prefix. Recreating it per unit throws that away; this is a design rule, not
  an optimization. The outline client is a one-shot `async with`, because it is called once per run.
- **`setting_sources=[]`** isolates the SDK from this repo's own `.claude/` hooks and settings.

### Async run model

Variant generation is 30-60s, so `web/app/runs.py` kicks it off as a background task keyed by slug
and the summoning page polls `GET /generate/status` until it flips to done. `RunManager.aclose()`
runs on FastAPI shutdown so the persistent client's subprocess is not orphaned.

### Known limit

`SLUG = "globex-staff-platform"` is hardcoded at `web/app/main.py:25`. The web app serves exactly
one application, for one user, with no auth and globally shared picks. The slug is the documented
seam for a future per-user resolver — `runs.py` and the repository signatures are already keyed by
it, so do not bake further single-user assumptions into the domain model or route handlers.

## Repo docs

`PRODUCT.md` (audience, anti-references, design principles) and `DESIGN.md` (the oxblood-on-white
token system, implemented in `web/app/static/css/app.css`) constrain UI work; read them before
touching templates or CSS. `specs/` and `.sdlc/` are artifacts of the autonomous-sdlc loop, not
hand-maintained docs.

## Agent skills

### Issue tracker

GitHub issues via `gh`; specs are parent issues labelled `spec`, slices are labelled
`ready-for-agent` or `ready-for-human`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single context: `CONTEXT.md` and `docs/adr/` at the root. See `docs/agents/domain.md`.

### Tests and gates

Plain pytest in two suites (`tests/` for the plugin scripts, `web/tests/` for the web app), 100%
line and branch coverage. See `docs/agents/testing.md`.
