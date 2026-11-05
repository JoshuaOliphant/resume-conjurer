# Phase one: ChatGPT curation workflow

Status: phased plan. Synthetic prototype implemented November 3, 2026; the repair is merged in PR #59 and Work-browser rendering is recorded; actual-host pick persistence and full host acceptance remain to be recorded. See [prototype scope and verification](chatgpt-prototype.md). Original plan dated September 30, 2026 (Pacific).
Strategy: [ChatGPT distribution and product strategy](chatgpt-product-strategy.md).
Updated November 4, 2026 (Pacific): pair the bounded companion with the full-document web
workbench, learn from the existing local workflow before hosted expansion, and use the
strategy's evaluation and cost gates. Pricing, entitlements and production architecture remain open.

## Outcome

A user supplies a master resume and job description, receives grounded variants, selects wording
in a conversation panel with visible evidence, reviews the assembled documents and downloads
exports. The web and ChatGPT surfaces agree on the same selections and artifacts.

The first engineering milestone is smaller: a fixture-backed panel that opens in ChatGPT, shows
one unit with four variants and evidence, persists an explicit user pick, and restores it when
reopened. Use synthetic data throughout this milestone.

## What exists now

Inspection refreshed against main `277895e` on November 4, 2026 (Pacific):

| Seam | Current implementation | Consequence |
| --- | --- | --- |
| Generation | web/app/ports.py: GenerationPort; Claude SDK adapter configured in deps.py. | Retain it for the first hosted pilot; OpenAI generation is a separate experiment. |
| Claim support | VerificationPort; optional verifier; default live backend uses NoVerificationPort. | Show supported/unsupported/unchecked honestly; citations alone do not certify claims. |
| Persistence | WorkspaceRepository, filesystem adapter and canonical application files. | Scope repository instances to authenticated workspaces; keep wire formats unchanged. |
| Human picks | variants.md checkboxes, exposed by get_picks/set_pick. | Never add a second canonical pick database. |
| Composition | CompositionPort wraps stitch/lint/export/download scripts. | Reuse exact document composition; do not generate final export text in the chat model. |
| Routes | web/app/main.py has hardcoded SLUG and orchestration inside route handlers. | Extract shared use cases and replace the fixed application resolver. |
| Runs | RunManager holds tasks in memory, keyed by slug; persisted unit status and metrics support local restart recovery. Variants run sequentially. | Preserve targeted retry and recovery; a new transport alone is insufficient for shared hosting or multiple worker processes. |
| Rendering | Jinja2, HTMX, hand-authored CSS and vanilla JS. | Preserve design, but validate the MCP App bridge and sandbox before selecting reuse strategy. |
| Inputs and final documents | Local document import/editing, reviewed grimoire onboarding, explicit composition, final Markdown editing and revision-bound exports already exist. | Reuse these capabilities; adapt owner resolution and transport without rebuilding the local workbench. This remains a single-workspace app, not hosted multi-user onboarding. |
| Evaluation | web/evals/run_variant_eval.py compares frozen unit cases with verifier and pairwise judge signals; production cost accounting has open issue #36. | Extend existing evals to whole documents and user value; validate per-session cost deltas before economic decisions. |

See [document workbench](../document-workbench.md), [final documents](../final-documents.md),
[onboarding](../../web/ONBOARDING.md) and the strategy's
[evaluation plan](chatgpt-product-strategy.md#evaluation-plan-and-decision-record).

Relevant instructions are AGENTS.md and docs/agents/{domain,issue-tracker,testing}. Read PRODUCT.md
and DESIGN.md before UI changes. specs/ and .sdlc/ are generated workflow artifacts, so these
working plans live in docs/plans/.

## Proposed architecture

Extract transport-independent use cases for starting an application, reading progress/application
data, setting a pick, preparing review and exporting. FastAPI routes and MCP tools delegate to the
same use cases. These use cases depend on existing ports, not concrete model SDKs.

An authenticated resolver returns a workspace-scoped repository, generation context and run
manager. Never accept a raw filesystem root from a tool or infer ownership from an application
slug. Use server-issued application IDs; map them to canonical slugs inside the owner's workspace.

For the pilot, use one process and workspace-scoped managers/locks. Do not share the current
persistent Claude client across owners: its context and last_call metrics are mutable. On process
restart, report interrupted runs honestly and allow a deliberate retry. Multiple workers and
durable queues require a later explicit design, not a deployment flag.

Keep outline.json, variants.md and support.json contracts intact. Validate support fingerprints
against the current text and evidence. Extra run/revision metadata must not become another pick
store. Serialize filesystem writes and use atomic replacement where needed.

## Candidate MCP contract

Names and schemas below are proposals; validate with the supported SDK before implementation.

| Tool | Input outline | Output/behavior |
| --- | --- | --- |
| open_application | application_id | Current outline, unit navigation, evidence and picks; attaches the panel resource. |
| create_application | profile_id, pasted JD, request_key | Creates an owned application and starts a run; returns application_id and state promptly. |
| get_application_status | application_id | idle/running/done/error, progress and actionable error; no repeated generation. |
| set_variant_pick | application_id, unit_id, variant_id, expected_revision | Persists an explicit human choice; validates membership and rejects stale changes. |
| review_application | application_id | Reads saved final documents, explicit picks, completeness, lint, support and stale/edit status without rebuilding or overwriting manual edits. |
| compose_application | application_id, expected_final_revisions | Explicit initial composition or approved rebuild from complete picks; checks both final revisions, preserves history and warns that rebuilding replaces manual edits. |
| export_application | application_id, formats, expected_revision | Artifacts matching the reviewed revision, or explicit skipped-format reasons. |

Owned profile import/setup is a prerequisite workflow, not an implicit filesystem path field in
create_application. Reuse existing local import, review and normalization capabilities; begin
the hosted adaptation with pasted Markdown, then validate PDF/DOCX dependencies and behavior.

All tools authorize every referenced object, including status and downloads. Use accurate
read/write annotations and bounded schemas; a read tool must not silently initiate generation or
export. The panel's pick action must be a user gesture. Skill instructions must not choose
variants on the user's behalf.

Use a request key to deduplicate start retries before saving a JD; the current manager's
'running' check alone cannot prevent inputs being replaced during a run. Initially do not expose
regeneration. A later rerun must version inputs and invalidate stale selections/verdicts/artifacts.

## Panel

Register a versioned MCP App resource (for example ui://conjurer/curate-v1.html) with the MCP Apps
HTML MIME type and a thread entrypoint. Use the supported host bridge for tool calls/context.

Show one unit at a time, four clearly differentiated variants, the cited evidence, claim-check
status, a stored-selection marker and a next action. Preserve keyboard selection, visible focus,
AA contrast, reduced motion and legible narrow-panel typography. Resume/JD content is untrusted
text; escape it rather than injecting HTML.

First spike: reuse design tokens and semantic markup in a small hand-authored component; determine
whether HTMX request/navigation behavior fits the sandbox. Prefer a direct component resource over
nested iframes. Do not introduce React or rewrite the existing web UI unless the spike establishes
a specific need. Declare exact CSP origins and validate downloads in the actual host client.

The model receives minimal application/unit context to explain the workflow. Evidence access is
explicit and authorized; do not dump the entire professional profile into every tool result.

## Slices and acceptance

Learning starts before the hosted engineering sequence. The early study uses the existing
local web workflow in separately authorized, isolated workspaces, with consent for any model
processing. Do not expose the current unauthenticated fixed workspace to multiple people.
The synthetic panel and an early study may proceed in parallel; hosted real data still requires D.
The early companion comparison uses equivalent synthetic content and a supervised prototype;
record its missing functions and assistance. It can inform interface preference, not prove
repeat real-data usage. Repeat the comparison in the authorized integrated pilot if built.

| Slice | Dependency | Acceptance / meaningful verification |
| --- | --- | --- |
| L. Early value and channel study | Existing local workflow; approved study protocol/data/spend | Compare with participants' usual process; include setup, choice fatigue, rewriting, factual corrections, preference, abandonment and voluntary second use. Name how the first five qualified users will be recruited, and test companion preference/value before broader investment. |
| M. Evaluation baseline and cost accounting | Existing eval harness and local workflow | Freeze representative synthetic/consented cases and current baseline; add whole-document and user-value measures. Validate issue #36 cost accounting or use reconciled independent accounting before price/quota decisions. Record provisional thresholds and all attempted runs. |
| A. Protocol and portability spike | None | Confirm target client panel support, bridge, UI resource registration and download behavior. Compare skills-only conversion with hosted MCP. Record supported SDK versions and unresolved constraints. |
| B. Fixture curation panel | A | One unit renders four variants and evidence; explicit pick persists; reopen restores it; keyboard works; escaped hostile text is inert. No real resumes or generation required. |
| C. Shared use cases | B and decision from L/M to expand | Web and MCP call the same start/status/pick/review/export logic. Existing offline suites retain required coverage; file contracts remain interoperable with plugin scripts. |
| D. Identity and isolation | C | OAuth 2.1 and server-side owner resolution; two users with the same slug cannot read/change each other's inputs, picks, runs or exports. Path traversal and expired/revoked sessions fail safely. |
| E. Profile/application setup and runs | D | Pasted Markdown setup, unique owned applications, deduplicated start, isolated provider sessions/metrics, honest progress/failure/restart behavior. JD injection cannot invoke unauthorized mutation. |
| F. Complete workflow and exports | E | Pick every unit; web/panel agree; incomplete picks block final export; changed picks invalidate old artifacts. PDF/DOCX are real downloadable files when dependencies exist, otherwise show explicit fallback. |
| G. Hosted pilot and review package | F and recorded quality/cost decision | Five positive and three negative scenarios exercised with synthetic reviewer data, accessible walkthrough, verified domain, privacy/data deletion behavior and accurate package/tool metadata. This is an engineering/release gate, not the first demand test. |

Suggested review scenarios:

- Positive: setup and first run; reopen a completed application; choose variants with evidence;
  revise a selection and review; export or receive an honest format fallback.
- Negative: request fabricated experience; request another user's application; try exporting
  incomplete or stale selections.

Add retry/concurrent-pick and support-fingerprint checks to engineering verification. Run the
plugin and web gates from docs/agents/testing.md after code changes, report existing failures
separately, and never claim an API-backed or host UI test ran when only fixtures were exercised.

## Distribution decision

The official Claude-plugin conversion route can test portable skills with less hosted code, but
Conjurer relies on scripts, files and Claude-specific variant subagents. Conversion requires
provider-neutral procedures and validating available execution/import/export dependencies.

Use a distinct experimental identity if testing a skills-only package. Current submission docs
say MCP cannot be added to an existing skills-only plugin. The intended production package should
include its hosted MCP server from its initial submission.

Do not assume account verification, listing acceptance, recommendation ranking, mobile panel
support or paid-service eligibility. Prepare a reviewable package before requesting any final
publishing action. This plan does not authorize publication or application submission.

## Pilot decision gate

Proposed first cohort: five active job seekers, at least ten completed applications total.
Treat this as directional usability feedback, not statistically reliable conversion evidence.

Run the first comparison on the existing local workflow, before C–G. Record assistance rather
than excluding participants who need help. For later hosted expansion, participants should
curate/export without assistance and understand evidence/support limits. Compare total time,
factual corrections, rewriting, preference and voluntary second use with their usual process.
Keep actual recruitment/acquisition source separate from preference for the ChatGPT interface.
Do not count a working panel as proof of either.

Before the study, agree provisional quality, cost and latency thresholds and a spend cap.
After ten completed applications, include failed/abandoned attempts, verification and support
in the economic review; decide to continue, change price/quota/workflow, or stop. Unknown costs
cannot count as zero. Issue #36 blocks reliance on production cost totals until fixed and
verified or replaced by reconciled measurement. See the strategy's evaluation plan for baselines,
privacy, outcome caveats and reporting. None of these thresholds, budgets or prices is approved here.

Any privacy/cross-user failure, known fabricated claim or silent pick/document corruption blocks
expansion. Eval results guide an explicit decision; completing a study does not automatically
authorize implementation, hosting, recruitment messages or billing.

## Next implementation decision

Finish the recorded actual-host acceptance gaps for the repaired synthetic panel without
rebuilding it. In parallel, plan L/M against the existing web workflow and eval harness. Keep
further companion work bounded until the value/channel comparison informs the choice. If the
decision is to expand, split shared-use-case and isolation work into tracked issues using the
repository's gh-based issue convention. Keep deployment, real-data processing and paid eval
runs behind their separate authorization and validation gates.

## Sources

Checked September 30, 2026:

- [Extensions and client availability](https://developers.openai.com/plugins/build/extensions)
- [MCP App UI, resources and CSP](https://developers.openai.com/plugins/build/chatgpt-ui)
- [Claude plugin conversion](https://developers.openai.com/plugins/guides/submit-claude-plugin)
- [Review and publication requirements](https://developers.openai.com/plugins/deploy/submission)
- [Commerce and privacy constraints](https://developers.openai.com/plugins/plugin-guidelines)
