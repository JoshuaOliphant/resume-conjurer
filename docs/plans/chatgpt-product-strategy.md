# ChatGPT distribution and product strategy

Status: working proposal, captured September 30, 2026 (Pacific).
Owner: Joshua Oliphant.
Implementation detail: [Phase one](chatgpt-phase-one.md).

## Product thesis

Keep the existing promise: generate evidence-grounded resume and cover-letter variants, let the
human choose the wording, then stitch and export. Extend that workflow into ChatGPT while keeping
the independent web product and Claude Code plugin useful.

ChatGPT is a candidate distribution surface. Whether directory discovery brings qualified users
or revenue is an experiment, not an established acquisition channel.

PRODUCT.md still governs the experience: calm editorial design, visible evidence, accessible
curation, and no generic chat interface. The model produces data; Conjurer renders the interface.

## Evidence and assumptions

Official documentation checked September 30, 2026:

| Finding | Product implication |
| --- | --- |
| Extensions support conversation panels, sidebar apps, settings, file viewers and deep links. Web extensions for Free and Go are still coming soon; composer mentions are desktop-only. | Start with one conversation panel; verify the actual target client's support. |
| Plugins can contain skills, MCP connections, or both. Claude commands and agents require conversion to reusable skills. | Assess existing plugin portability before building a second generation system. |
| Submission requires a verified publishing identity, automated checks and review. A skills-only published plugin cannot currently gain an MCP server later. | Do not publish a skills-only package under the intended hosted plugin identity without resolving that migration limit. |
| Plugin commerce currently excludes digital products/services, subscriptions and indirect freemium upsells. Existing paid accounts can access included features. | Do not assume an in-plugin Search Pass sale or paid funnel is allowed. |
| A registered MCP App UI resource and host bridge are supported. Nested iframes need explicit policy and review. | Do not assume existing HTMX pages can simply be embedded unchanged. |

The earlier brainstorm's model prices, latency/cost predictions, plan-usage eligibility and
revenue projections are not adopted as verified facts. Recheck them when implementing the
relevant phase. Native subagent features are optional; preserve deterministic orchestration until
evaluation demonstrates a reason to change it.

Sources:

- [Plugin extensions](https://developers.openai.com/plugins/build/extensions)
- [Submit a Claude Code plugin](https://developers.openai.com/plugins/guides/submit-claude-plugin)
- [Submission and publication](https://developers.openai.com/plugins/deploy/submission)
- [Plugin guidelines, including commerce](https://developers.openai.com/plugins/plugin-guidelines)
- [MCP App UI](https://developers.openai.com/plugins/build/chatgpt-ui)

## Sequence and decision gates

| Phase | Outcome | Gate before expanding |
| --- | --- | --- |
| 1. ChatGPT integration | Existing inputs → variants → human picks → review → export in a conversation panel, sharing core contracts with the web app. | Fixture prototype works; private pilot has authenticated isolation and reliable exports. |
| 2. OpenAI generation adapter | A second GenerationPort implementation, evaluated against the Claude implementation. | Equal fixtures; measured grounding, choice quality, regeneration, latency and cost. |
| 3. Identity | Convenient account linking/sign-in, with authorization enforced by Conjurer. | Verify client registration and commercial eligibility; identity is separate from inference allowance. |
| 4. Paid web experiment | A bounded job-search pass sold by the independent web product. | Willingness to pay, unit economics and permitted relationship to the plugin established. |
| 5. Apply Assist | Fill an application using approved documents and evidence-backed answers; user reviews before submission. | Reliable site behavior, explicit submission approval and bounded operating cost. |
| 6. Application lifecycle | Tracking and interview preparation, with optional email events. | Users return repeatedly; events are accurate and connections are authorized. |

The first three are connected but need not ship as one large release. Phase one can retain the
current generation provider. Before real resumes are hosted, authentication and user isolation
are prerequisites even if the nicer sign-in experience is scheduled later.

## Revenue hypotheses

These are proposed price tests, not committed packages or forecasts:

| Offering | Hypothesis | What to validate |
| --- | --- | --- |
| Free workflow | Profile/evidence setup and one complete application create trust. | Activation, operational cost and whether users want another application. |
| Web Search Pass | About $29 for 30 days and a bounded allowance, initially considering 20 applications. | Paid conversion, actual retry/export/support cost, expiry fairness and quota fit. |
| Apply Assist | About $10 for 10 assisted applications, or a higher pass near $49. | Browser reliability and cost; neither price nor allowance is validated. |
| Coaches | Client workspaces, comments and consistent evidence provenance might support $79–149/month. | Interviews with coaches and recurring usage before building collaboration. |

A pass reflects episodic job searching. Do not create unlimited usage promises before cost data
exists. Count generation retries, verification, exports, storage, support and payment costs;
token price alone is not unit economics.

Sell and test the web product through independent web acquisition. In ChatGPT, existing paid
accounts may use included entitlements, but do not show upgrade promotions, initiate purchases
or link to transactional checkout. Any allowed informational entitlement link must follow the
current guidelines. Ask OpenAI to clarify a proposed free-to-paid journey before relying on it.

## Persistent value

Over time, the grimoire, master resume and evidence can form a reusable professional profile:
voice, accomplishments, role preferences and application history. Preserve the existing concepts
and file contracts; do not silently move all evidence into grimoire.md.

Application tracking and interview preparation can extend the useful relationship. Treat success
followed by churn as normal. Explore coaches separately if recurring individual usage is weak.

## Measures

For the first private pilot, record only disclosed, necessary product metrics:
started applications, curation completion, exports, regeneration, time to export and direct
feedback on whether a user would submit the documents. Keep resume/JD text out of analytics.

Later compare acquisition source, repeat usage and web purchase conversion where permitted.
Maintain separate measures for evidence trace completeness and claim support: a citation is not
proof. The current live default has no claim verifier; report unchecked status honestly.

## Monitor

A daily ChatGPT task was enabled September 30, 2026, beginning October 1 in America/Los_Angeles.
It checks official sources for actionable changes to submission, discovery, extensions, digital
service monetization and commercial plan-usage eligibility. It reports material changes only and
does not edit this repository or publish the plugin. The task runs outside repository CI.

## Scope boundaries

Job discovery, a general job-search CRM, autonomous bulk submission, email/calendar integration,
coach collaboration and file-editor extensions are later candidates. The initial product remains
one complete, trustworthy tailoring workflow.

Next: prove the curation panel with synthetic fixtures and turn the phase-one slices into GitHub
issues using the repository's issue-tracker convention when implementation starts.
