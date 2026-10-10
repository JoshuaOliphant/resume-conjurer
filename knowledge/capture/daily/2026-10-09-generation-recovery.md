---
title: Failed-unit generation recovery
date: 2026-10-09
project: resume-conjurer
component: generation
problem_type: debugging
severity: high
symptoms:
  - A failed unit stopped later units and discarded unsaved progress.
  - Retrying generation could replace reviewed drafts and picks.
  - Restarting the server lost failure and retry state.
solution_summary: Persist complete unit results, retry failures explicitly, and reconcile recovery metadata against authoritative drafts.
---

# Generation recovery journal

La Boeuf chose explicit retry for only the failed unit, continuation through remaining units, and preservation of successful drafts and picks. Parent #40 records the behavior; #41 delivers partial completion and retry, and #42 delivers restart recovery.

The original writer replaced the whole variant document and reset pick markers. Targeted atomic block replacement preserves other units. Full-run initialization is separate: a caught draft-reset failure restores the previous outline instead of pairing old drafts with a replacement outline. This is rollback on a caught write error, not a general multi-file crash transaction.

Recovery metadata holds unit state and an outline binding, never another pick store. Malformed metadata reports a recovery error while retaining readable drafts. Complete saved drafts within a correctly bound outline remain authoritative even if their metadata still says failed or generating. Retry refreshes eligibility before starting so externally completed drafts and removed outline targets are not overwritten.

A threaded regression reproduced an old recovery snapshot overwriting a completed retry. A run-manager lock now serializes recovery, start, and retry decisions. Retry also participates in the source-mutation lock that protects pick writes and source edits. SDK cleanup failures are logged without stopping later units; the client reference is cleared before disconnect.

Review found that corrupt optional metrics could prevent recovery and leave a half-initialized cache. Metrics failures now warn without blocking draft recovery, and the cache is published after initialization. Existing cost-accounting issues remain separate in #36.

The four CI type failures were real fixture-contract problems, not infrastructure failures. Pinned Ty includes tests, unlike the earlier local eval-only check. Sorted imports then exposed a test-order dependency; web conftest now calls the existing plugin-path helper. Future verification should run the exact pinned gate and isolated test modules.

Verification: 663 web tests and 232 plugin/tooling tests passed at 100% line and branch coverage; pinned Ruff and Ty passed. The live Sonnet adapter test passed in 57.53 seconds against committed synthetic fixtures. In the browser, a selected draft survived an actual server restart; seeded interrupted metadata became retryable, and keyboard retry returned to four choices in the same unit view. Actual assistive-technology speech was not tested.

Independent Standards, Spec, and approach-fit reviews found the meaningful edges. One claimed unhashable-state crash was refuted: tuple membership already rejects list/dictionary states. Negative cases now preserve that proof. External Jev review was not used because automatic approval rejected the source transfer. Private career/eval data stayed out of the commits.
