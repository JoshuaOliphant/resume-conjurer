# Spec: conjurer-backend-reconciliation

Reconcile PR #3's live Claude Agent SDK backend with the separately-merged PR #4
(routes/composition-root/rail layout on `main`), and fix the findings from the
pr-review-toolkit review of PR #3. Target: push a green, reviewed diff to the existing
`origin/feature/conjurer-backend-generation-port` branch (PR #3 stays open, no new PR).

Requirements are fully specified already (five named review findings, an architecture
decision made with the user, a fixed suggestion list) — no ambiguity to resolve
autonomously here, so this spec restates them as acceptance criteria rather than
re-deriving requirements from scratch.

## Architecture decision (already made, restated for the record)

PR #3's ports/adapters/runs/metrics are the functional live backend; PR #4's
`providers/fixtures.py` is a static mock wrapped in nicer file organization. Keep PR #3's
backend as-is; adopt PR #4's *organizational* pattern (routes-only `main.py` + a
`deps.py` composition root + a `rail.py` template-context module) on top of it. PR #4's
session-cookie/`SelectionStore` machinery is not ported — PR #3 has no per-session
concept (one hardcoded `SLUG`, documented as "the seam a future multi-user resolver
scopes"), so there is nothing analogous to harden.

## Acceptance Criteria

1. **AC-1 (layout)**: Given the reconciled branch, when `web/app/` is inspected, then
   `main.py` contains only route handlers + the FastAPI app factory (no composition-root
   functions), `deps.py` contains `is_live`/`workspace_root`/`build_repository`/
   `build_generation`/`build_composition`, and `rail.py` contains `STEPS` +
   `template_context`. `default_repository()` (workspace_fs.py) and `build_run_manager()`
   (main.py) — both dead, duplicated composition roots — are removed.

2. **AC-2 (no fixture pollution)**: Given `CONJURER_BACKEND=live` and no
   `CONJURER_WORKSPACE` set, when `build_repository()`, `build_generation()`, or
   `build_composition()` is called, then it raises `RuntimeError` naming
   `CONJURER_WORKSPACE` rather than silently defaulting to `web/tests/fixtures/workspace/`.

3. **AC-3 (evidence grounding enforced)**: Given an `Application` whose `units` contain a
   `Variant` with an `Evidence` item marked `grounded=True`, when that Evidence does not
   match (by id and value) an entry in the `Application.evidence` pool, then constructing
   the `Application` raises `ValueError`. Given the live generation path's transient,
   not-yet-resolved variants (`generation_sdk.variants_from_block`), then their Evidence
   items are marked `grounded=False` (not a false `True`) until `WorkspaceRepository`
   resolves them against the real pool.

4. **AC-4 (slug validated)**: Given a slug that is not a safe `applications/<slug>/` path
   segment (e.g. contains `..`, `/`, or a leading `-`), when any `FsWorkspaceRepository`
   method is called with it, then it raises `ValueError` before touching the filesystem.

5. **AC-5 (durable failure trace)**: Given a generation run whose outline or variants
   call raises, when `RunManager._run`'s except block runs, then the exception is logged
   (via `logging`, with traceback) in addition to being recorded on `RunStatus.error` —
   not only held in memory for whoever happens to be polling.

6. **AC-6 (polish)**: `RunMetrics` gains an `add_step()` method and `runs.py`
   uses it instead of `.steps.append(...)`; `workspace_fs.py`'s frame lookup uses
   `outline.frame_name` (safe fallback) instead of `FRAMES[outline.strategic_frame]`
   (KeyError-prone); the fire-and-forget task in `RunManager.start()` gets a
   `add_done_callback` logging safety net; the README's CLI-auth-check wording and dated
   billing-policy sentence are tightened; the garbled comment in `generation_sdk.py` is
   fixed.

7. **AC-7 (test coverage)**: New tests cover: `RunManager` state isolation across two
   concurrently-running slugs; `FsWorkspaceRepository` behavior on malformed JSON
   (`load_outline`/`load_metrics`) and on an invalid slug; cancelling `RunManager` mid
   variants-loop (not only mid-outline, which was the only cancellation path already
   tested).

8. **AC-8 (green gate)**: `cd web && uv run pytest` passes at 100% line+branch coverage
   (the project's enforced gate); `ruff check` is clean.

9. **AC-9 (delivered to the right place)**: The result is pushed to
   `origin/feature/conjurer-backend-generation-port` (updating PR #3), not a new branch
   or PR.

## Out of scope (logged, not ambiguity)

- Standing up an observability harness (the "no logging" finding is fully addressed by
  AC-5's stdlib logging, per the decision logged at INIT).
- Porting PR #4's session-cookie/`SelectionStore` machinery (no per-session concept
  exists in PR #3's single-slug design; inventing one is unrequested feature work).
