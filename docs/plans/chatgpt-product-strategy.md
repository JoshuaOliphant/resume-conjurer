# Resume Conjurer: design, distribution and monetization strategy

Owner: Joshua Oliphant. Updated November 4, 2026 (Pacific).
Status: product direction and working commercial hypotheses, not a launch or pricing commitment.
This is the canonical continuation of the strategy introduced in [PR #20](https://github.com/JoshuaOliphant/resume-conjurer/pull/20), not a second product plan.

## Start here, especially in a new agent session

The direction is a full-document web workspace with a useful, narrow ChatGPT companion,
sharing the grounded tailoring workflow and canonical data with the Claude Code plugin.
The web product owns the complete workbench and independent customer relationship; ChatGPT
helps users work with evidence-grounded alternatives and make explicit picks where they
already converse. Validate that division through use, rather than expanding both surfaces
or rewriting generation before learning what people value.

Read [PRODUCT.md](../../PRODUCT.md) for audience and experience principles,
[DESIGN.md](../../DESIGN.md) for visual/accessibility constraints, this document for strategy,
[phase one](chatgpt-phase-one.md) for the staged integration plan, and the
[prototype record](chatgpt-prototype.md) for implementation and verification limits.
Inspect current code, open PRs and newer owner instructions before starting work.

Distinguish three kinds of statements below:

- **Direction:** a web workbench and useful ChatGPT companion, evidence-grounded variants, explicit human judgment, shared contracts and an editorial interface.
- **Hypotheses:** discovery effectiveness, willingness to pay, package prices, allowances and future adjacent products.
- **Dated platform constraints:** externally controlled rules and eligibility; recheck before launch or commercial implementation.

A strategy document is not authorization to deploy, publish a plugin, change access, charge
customers, contact employers or submit applications. Those actions require their own approval.

## Current position and the next useful milestone

- [PR #58](https://github.com/JoshuaOliphant/resume-conjurer/pull/58) merged the synthetic
  one-unit/four-variant MCP panel, canonical picks, reopen reads and cancellation recovery.
  Its Python, DOM, Chromium and static checks passed. Those tests are not proof of actual host rendering.
- On November 3, 2026 (Pacific), Joshua reported that the demo works after fixes in the Resume Conjurer
  project. The project conversation records a repaired panel reopening with four alternatives
  and no selected variant. Treat this as reported demo progress, not full production acceptance.
- At this document's update, [PR #59](https://github.com/JoshuaOliphant/resume-conjurer/pull/59)
  contains the separate bundled-JavaScript repair and is merged; main is `277895e`.
  Its validation report records ChatGPT Work browser rendering, evidence expansion,
  close/reopen and reload after a server restart, with all choices unselected.
  Actual-host pick persistence and desktop rendering remain explicitly unverified.
  Preserve that work and the recorded host-validation limits. Do not reconstruct the old prototype.
- Next, record a reproducible acceptance result for the repaired build: client/version and
  served commit, visible panel, explicit pick, close/reopen restoration, evidence, keyboard
  operation, cancellation and stale-write behavior. Successful tool calls alone are insufficient.

In parallel, test the existing local web workflow with an authorized supervised study before
building the hosted pilot stack. Keep the next ChatGPT engineering work bounded by the
synthetic acceptance check and evidence that the companion adds value.
A working synthetic demo does not establish authentication, isolated real-data storage,
full generation/export integration, commercial eligibility or public-release readiness.

## Intended use and paid value

1. **First application:** bring a master resume and a real job description, review the evidence,
   compare grounded alternatives, choose wording, review the complete documents and export.
   Include setup and rewriting in the time measured; selection speed alone can hide extra work.
2. **Later applications:** reuse approved evidence and voice rules, carry forward saved choices
   and revisions, and tailor to another role without rebuilding the professional profile.
3. **ChatGPT companion:** complete a useful bounded task, such as comparing a unit's alternatives
   with evidence and saving the user's choice. The web workbench supports full-document editing,
   application organization and reliable exports. Preserve the same canonical state across both.

The paid-workspace hypothesis is that reusable evidence, saved application work and revisions,
and reliable documents save enough effort to pay for during an active search. Customers are
buying a dependable workflow, not a promise of more model tokens. Which capabilities belong in
each package, the allowance and expiry behavior, and the production architecture remain open.
Keep the ChatGPT experience useful on its own and existing entitlements accessible; do not make
it an upgrade funnel or degrade a shared feature to drive people to the website.

## Product thesis and design contract

Master resume plus job description → grounded alternatives → human chooses → review → export.
The user is a job seeker under time pressure who wants documents they would actually submit,
without doubting where the claims came from. The differentiator is trustworthy curation,
not a larger volume of AI-written text or automated applications.

The conversation helps the user understand and direct the work. Conjurer owns the structured
comparison, evidence and document interface. The model generates data, not HTML.

Preserve the existing experience:

1. **Evidence is visible.** A citation is not a verification verdict. Keep supported,
   unsupported and unchecked distinct; never turn "claim check not run" into reassurance.
2. **The document leads.** Calm editorial typography, whitespace and restrained oxblood-on-white
   styling; chrome stays subordinate to resume and letter text. Use existing design tokens.
3. **Abundance, then taste.** Make alternatives easy to compare and choices deliberate.
   Do not silently choose on the user's behalf in the human-curation workflow. Existing explicit
   fast-mode workflows remain separate; they are not permission for hidden auto-selection.
4. **Continuity earns trust.** A pick persists across surfaces and reopen. Explain stale output,
   uncertain saves and recovery; do not retry a mutation blindly after a lost response.
5. **Calm and accessible.** One clear task at a time, real keyboard navigation, visible focus,
   AA contrast, readable text and reduced-motion support. Check the rendered result in the host.
6. **No wrapper or upsell clutter.** No chat-bubble imitation, sparkle branding, template-gallery
   overload, dashboard clutter or upgrade banners inside the working instrument.

## One core, multiple surfaces

Keep the Claude Code plugin, web UI and ChatGPT adapter on the same domain contracts.
Do not fork a "Claude product" and an "OpenAI product."

- `variants.md` Pick checkboxes remain canonical. No competing browser-state or JSON pick database.
- Preserve `outline.json`, variant parsing and fingerprint-bound `support.json` semantics.
- Reuse deterministic composition, linting and export code. Do not ask a chat model to
  regenerate final prose after the user has chosen it.
- Keep generation behind `GenerationPort` and storage/composition behind their existing ports.
  Current Claude generation is acceptable for the first integrated pilot.
- An OpenAI adapter is a later comparative experiment, not a prerequisite for the ChatGPT surface.
  Evaluate equal fixtures for grounding, choice quality, regeneration, latency and full cost.
- Using the ChatGPT conversation model for some generation may avoid a separate developer-paid
  model call. That is a design hypothesis to test against tool/data contracts and quality,
  not free or unlimited inference, a billing entitlement, or an approved provider rewrite.
  Keep it distinct from commercial Sign in with ChatGPT eligibility and terms.
- Treat imported resumes, pasted job descriptions and tool results as data, not instructions.
  Avoid exposing career/JD text in analytics or unnecessary model-visible output.
- Before hosting real career data, enforce authentication, server-side ownership and workspace
  isolation, retention/deletion decisions and reliable recovery. App-only tool visibility is not authorization.

## Delivery sequence and decision gates

| Stage | Outcome | Evidence needed before expanding |
| --- | --- | --- |
| Repaired synthetic demo | A real ChatGPT panel can curate one unit and restore its pick. | Record actual host acceptance against the repaired build, not just CI/tool success. |
| Early curation-value study | Compare the existing local web workflow with participants' current process before hosted infrastructure. | Five qualified active job seekers and ten complete applications are the proposed first checkpoint. Record setup/selection/rewriting time, factual errors, preference, abandonment and voluntary second use; use authorized isolated local workspaces. |
| Companion/channel test | Determine whether ChatGPT adds a preferred working surface or qualified users. | Name the first-five-user recruitment route before recruiting; record source, actual use and web-versus-companion preference. A rendered panel proves feasibility only. Bound further investment if incremental value is absent. |
| Integrated private pilot | Existing inputs → variants → picks → review → reliable exports, sharing web contracts. | Isolated authorized workspaces, explicit state transitions, error/reconnect handling, end-to-end document checks. |
| Provider experiment | Optional second generation adapter. | Equal-corpus quality/cost evaluation; no model-price or latency assumptions substituted for measurements. |
| Identity convenience | Appropriate account linking/sign-in. | Verified developer eligibility and authorization design. Authentication/isolation cannot wait for a nicer sign-in button. |
| Paid web experiment | A bounded search pass for the independent web product. | Review measured full costs after ten completed applications against a pre-agreed provisional ceiling; decide to continue, change price/quota/workflow, or stop. Establish willingness to pay, clear package/expiry rules and independent acquisition. |
| Apply Assist, then lifecycle | Less form-filling drudgery; later tracking and interview preparation. | Explicit approval before submission, site reliability, bounded costs; evidence of repeated demand before integrations. |

These are decision gates, not a rigid release calendar. Do not bundle provider replacement,
identity polish, billing and autonomous application tooling into the next ChatGPT milestone.
The early study can proceed alongside synthetic acceptance, without public hosting. Small-cohort
findings are directional; they do not establish conversion rates or causal employment outcomes.
At this stage, compare the synthetic companion with equivalent web content under supervision
and disclose missing functions. Interface preference is not repeat real-data usage; retest
actual usage in the authorized integrated pilot if the decision is to build it.

## Monetization: sell time saved and trust, test the package

Job searches are episodic. A time-bounded pass is a better initial hypothesis than assuming
an individual wants an indefinite monthly subscription. Success followed by churn can be a
healthy outcome; do not manufacture retention by withholding the user's work.

The following USD amounts were brainstormed and remain **unvalidated experiments**, not
approved prices, promised quotas, forecasts or currently available features:

| Candidate | Hypothesis | Validation required |
| --- | --- | --- |
| Free workflow | Evidence/profile setup and one complete application let the user experience trust. | Completion, cost and desire to do another application; keep the trial genuinely useful. |
| Web Search Pass | Approximately $29 for 30 days, initially considering 20 applications. | Willingness to pay, quota fit, retries/support/storage/payment costs and fair expiry behavior. |
| Apply Assist | Perhaps $10 for 10 assisted applications, or a pass around $49. | Browser reliability, human review, operating cost and permission boundaries. Not a current bundle promise. |
| Coaches | Perhaps $79–149/month for recurring client workspaces, comments and provenance. | Coach interviews and recurring demand before building collaboration, permissions or branded exports. |

Possible paid value includes resume/letter exports, retained evidence, job-fit analysis and
later tracking/interview preparation. These are packaging candidates, not a mandate to build
every feature before testing demand. Do not advertise unlimited usage without cost data.

Measure full application economics: outline/variant generation, retries, verification,
composition/export, storage, browser work, support and payment costs. Model token pricing
alone is not margin. Do not base the business on access to a user's ChatGPT inference allowance.
At the example $29/20 allowance, gross revenue is $1.45 per included application at full usage,
before fees and expenses. That arithmetic is not a cost ceiling or validated unit economics.
Agree a provisional budget and contribution-margin goal before the study, then use the
measurement gate below before adopting any package.

## ChatGPT distribution and commercial boundaries

ChatGPT discovery is an acquisition **experiment**, not guaranteed demand or a guaranteed
free-to-paid funnel. The independent web product must have a viable acquisition/payment path.

Platform guidance rechecked November 4, 2026 (Pacific):

- Web plugin extensions remain coming soon for Free/Go, and composer mentions are desktop-only.
  Verify the actual target client's support rather than assuming the same entry points everywhere.
- Nested frames are blocked by default. Existing editors may qualify on the MCP server's
  registrable domain with narrow frame CSP, domain-control/purpose justification and review;
  approval is not automatic. Do not embed the existing HTMX pages unchanged without testing
  navigation, bridge behavior and these constraints. Prefer a dedicated component template.
- Claude Markdown commands and reusable agent procedures need conversion into skills, including
  relevant persona instructions. Remove unsupported Claude-specific assumptions and public-directory
  lifecycle hooks; Claude approval does not transfer to the OpenAI directory.
- Current plugin guidelines prohibit digital-product/service sales, subscription sales and
  direct or indirect upsells inside ChatGPT. Do not initiate checkout, link to transactional
  checkout/upgrade flows, or place upgrade promotions in the panel.
- Existing paid users may access included features. Limited factual entitlement information
  and compliant nontransactional explanatory links are different from a purchase prompt.
- Do not deliberately degrade the ChatGPT version of the same feature or charge a
  ChatGPT-specific surcharge. Validate the proposed journey against current guidelines.
- Sign-in identity and plan-funded inference are separate questions. Commercial Sign in with
  ChatGPT onboarding remains restricted to selected partners; do not assume this project is eligible.
- Any plan-funded inference design must satisfy applicable SIWC terms on user control,
  runtime/token storage, non-pooling and permitted charges. Commercial help pages do not
  replace partner-specific terms; resolve that before choosing a billing or hosting architecture.
- Publishing identity verification, review and client support are release gates. Do not publish
  a skills-only package under the intended hosted identity without checking the currently
  unsupported later addition of MCP. A working development plugin is not Marketplace approval.

Recheck the relevant official pages immediately before implementation/submission, and seek
clarification for an uncertain paid journey. No launch, checkout or eligibility is authorized by
this document. Earlier brainstorms describing an automatic ChatGPT-to-paid-pass funnel or
inference subsidies are superseded by these constraints.

Official sources:
- [Plugin commerce and monetization](https://developers.openai.com/plugins/plugin-guidelines#commerce-and-monetization)
- [Commercial Sign in with ChatGPT client eligibility](https://developers.openai.com/siwc/request-client-id)
- [Sign in with ChatGPT terms](https://openai.com/policies/sign-in-with-chatgpt-terms/)
- [Submission and publication](https://developers.openai.com/plugins/deploy/submission)
- [Plugin extensions and supported surfaces](https://developers.openai.com/plugins/build/extensions)
- [MCP App UI](https://developers.openai.com/plugins/build/chatgpt-ui)
- [Claude plugin conversion](https://developers.openai.com/plugins/guides/submit-claude-plugin)

## Evaluation plan and decision record

Evaluation is part of the product work, not a substitute for user research or a green test suite.
The following extends the existing [variant eval runner](../../web/evals/run_variant_eval.py)
and [recorded lessons](../../knowledge/capture/daily/2026-10-06-variant-generation-eval.md).
It is a plan, not a claim that these end-to-end evals have been implemented or run.

### Baselines and representative cases

- Freeze the current generation/workflow baseline and compare candidates on the same inputs.
  Record commit, requested and served model, prompt/harness version, case-set version, settings,
  verifier/judge versions and pricing date. Repeat stochastic cases and retain failures, not
  only the successful outputs. Keep tuning cases separate from held-out evaluation cases.
- Extend the existing synthetic cases with varied roles and experience levels, thin evidence,
  number bait, contradictions, adjacent skills, glossary terms, unsupported claims, cover-letter
  opinion versus facts, hostile job text, long documents and export edge cases. Add real cases
  only with consent for the specific data, processors and purpose; never commit private resumes.
- For the early study, compare with each participant's usual process and record the assistance
  provided. Counterbalance task/order where practical and separate first-use setup from repeat use.
  Test whether four variants create useful choice or decision fatigue; do not assume abundance wins.

### Measure separately, then decide together

| Layer | Checks and measures | Decision it informs |
| --- | --- | --- |
| Factual grounding | Deterministic parsing, citation resolution, number/glossary checks; calibrated verifier plus human evidence review for unsupported details, contradictions and material omissions. Report unchecked separately. | Block known fabricated claims; fix a regression before expanding use. A resolved citation alone is not proof. |
| Writing and choice quality | Blind human pairwise preference, job relevance, specificity, distinct useful alternatives, voice/style, factual corrections and rewriting required. Review both unit sets and the assembled document. | Keep grounding gains only when the output remains useful. A shorter, blander answer can game a factuality score. |
| Workflow and document reliability | Successful generation, explicit picks, reopen/revision consistency, retry and stale-write recovery, accessible interaction, deterministic composition, real download and PDF/DOCX parse/render checks. Record format fallback and failure rates. | Gate the next surface/pilot release on trustworthy end-to-end behavior, not successful tool calls alone. |
| User value and outcomes | Completion and abandonment by stage; total and repeat-use time; support needed; preference versus usual process; willingness to submit; voluntary second application; willingness to pay separately. | Decide whether the workspace and companion merit more investment. Callback/interview data, when voluntarily recorded, is delayed and confounded, not proof of causal lift. |
| Full cost and latency | Setup/onboarding, generation, retries/failed attempts, verification, composition/export, hosting/storage, browser work where used, support time and payment fees. Separate serving costs from evaluation/judge/research costs. | Price, quota and workflow decisions using cost per attempted and completed application, latency distributions and observed usage, not token price alone. |

Calibrate automated judges against human-labeled good/bad cases and real preferences, randomize
pair order, and report disagreement. The existing judge was only a secondary signal; preserve
that lesson. Report sample sizes, paired changes and uncertainty alongside aggregates. Do not
hide parse failures, missing costs or unscorable outputs inside a favorable average.

### Cost measurement prerequisite: issue #36

[Issue #36](https://github.com/JoshuaOliphant/resume-conjurer/issues/36) remains open as of
November 4, 2026 (Pacific): production `RunMetrics` sums SDK session-cumulative costs across
calls, overstating cost for a reused variant client. Do not use its displayed totals to set prices
or claim margins. The eval runner already uses per-session deltas and resets on client recreation.
Before economic decisions, validate equivalent accounting across retries/restarts and reconcile
with provider usage or invoices where available. Missing cost fields are unknown, not free calls.
Keep measured costs separate from token-priced estimates, recording the tariff and limitations.
This documentation update does not fix or close the issue.

### Gates, cadence and privacy

Before running a study, record the question, baseline, cohort/case set, data authorization,
spend cap, provisional quality/cost/latency thresholds and the decision each result will change.
Joshua approves numeric thresholds and budgets; none are finalized here. Treat fabricated
claims, unauthorized cross-user access and silent pick/document corruption as blockers, not
trade-offs for lower cost. Passing a finite eval cannot guarantee their absence in production.

Keep deterministic regression cases in the existing offline gates when implemented. Run bounded
live evals after material model/prompt/provider changes with authorized data and spend; they do
not belong in secret-free offline CI by default. Review early-study evidence after the first ten
completed applications, including costs and failures from all attempts. Choose continue, revise
the workflow/price/quota, or stop; record the evidence and next question in the relevant issue.
The study result, not its mere completion, governs expansion.

Use case IDs and aggregate events in analytics; exclude resume/JD text and contact details.
Restrict any necessary raw eval traces to authorized reviewers, minimize processor inputs,
set retention/deletion rules, and keep real-case artifacts out of the public repository.
Existing eval inputs/results are private and gitignored, not a reusable public benchmark.

## Policy monitoring

The September 30 plan recorded a daily ChatGPT policy-change task beginning October 1 in
America/Los_Angeles, separate from repository CI and limited to reporting material changes.
Its current enabled state could not be verified for this update; do not assume it is active
or retired. Confirm the schedule with the owner when needed. Alerts do not replace a fresh
official-source check before a commercial or publication decision.

## What not to build yet

The grimoire, master resume and evidence can grow into a reusable professional profile, but
keep voice rules separate from factual evidence rather than dumping everything into grimoire.md.
Application history and interview preparation are sensible adjacent possibilities, not the next
mandatory build. Coaches may offer recurring demand; validate it separately.

Defer broad job discovery, a general CRM, email/calendar automation, coach collaboration,
autonomous bulk submission and new file-editor surfaces until the core workflow and demand
justify them. Apply Assist must stop for user review and submission approval; it is not a
license to mass-apply or contact employers.

## Handoff checklist for future agents

1. Read the linked product/design docs and inspect current main plus open repair PRs.
2. State which small product outcome the task advances; avoid unrelated engine polish.
3. Preserve human picks, evidence honesty, canonical contracts and the owner's newer work.
4. Separate observed behavior, user reports, platform constraints and commercial hypotheses.
5. Run applicable gates and record exact commit/client and evaluation versions for claims of success.
6. Update this document when a strategic decision changes; keep detailed implementation in
   the phase-one/prototype records instead of creating another competing strategy.
7. Ask for concrete decisions when needed: validated price/allowance, pilot audience,
   hosting/data policy, commercial eligibility or scope expansion. Do not infer them from this plan.
