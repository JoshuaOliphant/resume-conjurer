# Phase one: ChatGPT curation workflow

Status: proposed implementation plan, September 30, 2026 (Pacific).
Strategy: [ChatGPT distribution and product strategy](chatgpt-product-strategy.md).

## Outcome

A user supplies a master resume and job description, receives grounded variants, selects wording
in a conversation panel with visible evidence, reviews the assembled documents and downloads
exports. The web and ChatGPT surfaces agree on the same selections and artifacts.

The first engineering milestone is smaller: a fixture-backed panel that opens in ChatGPT, shows
one unit with four variants and evidence, persists an explicit user pick, and restores it when
reopened. Use synthetic data throughout this milestone.

## What exists now

Inspection of main on September 30, 2026:

| Seam | Current implementation | Consequence |
| --- | --- | --- |
| Generation | web/app/ports.py: GenerationPort; Claude SDK adapter configured in deps.py. | Retain it for the first hosted pilot; OpenAI generation is a separate experiment. |
| Claim support | VerificationPort; optional verifier; default live backend uses NoVerificationPort. | Show supported/unsupported/unchecked honestly; citations alone do not certify claims. |
| Persistence | WorkspaceRepository, filesystem adapter and canonical application files. | Scope repository instances to authenticated workspaces; keep wire formats unchanged. |
| Human picks | variants.md checkboxes, exposed by get_picks/set_pick. | Never add a second canonical pick database. |
| Composition | CompositionPort wraps stitch/lint/export/download scripts. | Reuse exact document composition; do not generate final export text in the chat model. |
| Routes | web/app/main.py has hardcoded SLUG and orchestration inside route handlers. | Extract shared use cases and replace the fixed application resolver. |
| Runs | RunManager holds tasks/status/metrics in memory, keyed by slug; variants run sequentially. | A new transport alone is insufficient for shared hosting or multiple worker processes. |
| Rendering | Jinja2, HTMX, hand-authored CSS and vanilla JS. | Preserve design, but validate the MCP App bridge and sandbox before selecting reuse strategy. |
| Inputs | Live web entry reuses an existing workspace master resume. | Hosted resume onboarding/import still needs implementation; the displayed flow is not a complete upload service. |

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
| review_application | application_id | Explicit picks, completeness, lint and support status; stitches only when complete. |
| export_application | application_id, formats, expected_revision | Artifacts matching the reviewed revision, or explicit skipped-format reasons. |

Profile import/setup is a prerequisite workflow, not an implicit filesystem path field in
create_application. Start with pasted Markdown; evaluate PDF/DOCX import using the existing
plugin procedure and required runtime dependencies as a later slice of this phase.

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

| Slice | Dependency | Acceptance / meaningful verification |
| --- | --- | --- |
| A. Protocol and portability spike | None | Confirm target client panel support, bridge, UI resource registration and download behavior. Compare skills-only conversion with hosted MCP. Record supported SDK versions and unresolved constraints. |
| B. Fixture curation panel | A | One unit renders four variants and evidence; explicit pick persists; reopen restores it; keyboard works; escaped hostile text is inert. No real resumes or generation required. |
| C. Shared use cases | B | Web and MCP call the same start/status/pick/review/export logic. Existing offline suites retain required coverage; file contracts remain interoperable with plugin scripts. |
| D. Identity and isolation | C | OAuth 2.1 and server-side owner resolution; two users with the same slug cannot read/change each other's inputs, picks, runs or exports. Path traversal and expired/revoked sessions fail safely. |
| E. Profile/application setup and runs | D | Pasted Markdown setup, unique owned applications, deduplicated start, isolated provider sessions/metrics, honest progress/failure/restart behavior. JD injection cannot invoke unauthorized mutation. |
| F. Complete workflow and exports | E | Pick every unit; web/panel agree; incomplete picks block final export; changed picks invalidate old artifacts. PDF/DOCX are real downloadable files when dependencies exist, otherwise show explicit fallback. |
| G. Private pilot and review package | F | Five positive and three negative scenarios exercised with synthetic reviewer data, accessible walkthrough, verified domain, privacy/data deletion behavior and accurate package/tool metadata. |

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

Continue if participants can curate and export without assistance, understand evidence/support
limits, and repeatedly say they would submit the result. Investigate abandonment and rewriting
before expanding features. Measure run cost/retries and time to export; record any privacy or
cross-user failure as a release blocker.

## First implementation task

Build slice A, then B: a synthetic one-unit curation panel with persistence and reopen behavior.
It establishes the new product surface while retaining the existing model and document pipeline.
After that succeeds, split the shared-use-case and isolation work into tracked issues using the
repository's gh-based issue convention.

## Sources

Checked September 30, 2026:

- [Extensions and client availability](https://developers.openai.com/plugins/build/extensions)
- [MCP App UI, resources and CSP](https://developers.openai.com/plugins/build/chatgpt-ui)
- [Claude plugin conversion](https://developers.openai.com/plugins/guides/submit-claude-plugin)
- [Review and publication requirements](https://developers.openai.com/plugins/deploy/submission)
- [Commerce and privacy constraints](https://developers.openai.com/plugins/plugin-guidelines)
