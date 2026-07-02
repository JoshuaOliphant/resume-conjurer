# Plan: conjurer-backend-reconciliation

Task breakdown mapped to `specs/conjurer-backend-reconciliation-spec.md`. Tracked via
TaskCreate/TaskUpdate (task IDs below refer to that tracker, not beads — the work was
already broken down before this loop started and doesn't benefit from a second
decomposition).

| Task | AC | Status at PLAN | Note |
|---|---|---|---|
| #3 Restructure into routes/deps/rail layout | AC-1 | in progress | `rail.py`, `deps.py` written; `main.py` restructured; needs verification |
| #4 Fix workspace fixture pollution | AC-2 | code written | `deps.workspace_root()` raises `RuntimeError`; `test_live_flow.py` updated; needs a full test run |
| #5 Enforce evidence-grounding invariant | AC-3 | code written | `Application.__post_init__` + `generation_sdk.py` `grounded=False` fix; needs a test proving the raise path |
| #6 Validate slug | AC-4 | code written | `domain.validate_slug` + `workspace_fs._app_dir` call; needs a test proving the raise path |
| #7 Log the runs.py except block | AC-5 | not started | add `logging.getLogger(__name__)` + `logger.exception(...)` |
| #8 Polish (Literal, RunMetrics.add_step, FRAMES fallback, done-callback, README, comment) | AC-6 | partial | Literal + FRAMES fallback + comment fix done; `add_step()`, done-callback, README wording remain |
| #9 New tests (concurrency, fs edge cases, cancellation) | AC-7 | not started | |
| #10 Full suite + lint + coverage gate, fix regressions | AC-8 | not started | the real verification step for #3–#9 |
| #11 Commit + push to existing PR #3 branch | AC-9 | not started | |

## Why no fresh Architect decomposition

The architecture decision (port PR #3's backend onto PR #4's file layout, keep PR #3's
ports as the functional backend) and the finding-by-finding fix list were already
established via direct file comparison and an explicit user choice earlier in this
session, before the SDLC loop was armed. Re-running the Architect pattern from the raw
request text would either reproduce this analysis at extra cost or, worse, drift from
the specific decision the user already signed off on. This is logged as the PLAN
decision below rather than treated as silent scope-cutting.

## Build order for the remaining BUILD iterations

1. Finish #7 (logging) and #8 (remaining polish) — small, independent, low-risk.
2. Write #9's new tests against the code as it now stands.
3. Run #10 (full suite, `ruff`, coverage gate) — fix whatever the restructuring broke.
   This is the real gate; #3–#9 are only "done" once this passes.
4. #11: commit in logical chunks, push to `origin/feature/conjurer-backend-generation-port`.

Then VERIFY walks the 9 AC one by one, REVIEW runs `code-review` + `security-review`
against the diff, and SHIP pushes (already on the right branch — no new PR to open).
