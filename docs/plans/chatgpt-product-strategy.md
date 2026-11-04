# Resume Conjurer: design, distribution and monetization strategy

Owner: Joshua Oliphant. Updated November 4, 2026 (UTC).
Status: product direction and working commercial hypotheses, not a launch or pricing commitment.
This is the canonical continuation of the strategy introduced in [PR #20](https://github.com/JoshuaOliphant/resume-conjurer/pull/20), not a second product plan.

## Start here, especially in a new agent session

The goal is to turn the existing grounded tailoring workflow into a useful ChatGPT app
while preserving the independent web product and Claude Code plugin. Do not lose that goal
in unrelated improvements to the engine. ChatGPT is a potential discovery and working
surface, not a reason to replace Conjurer with generic chat or to rewrite generation.

Read [PRODUCT.md](../../PRODUCT.md) for audience and experience principles,
[DESIGN.md](../../DESIGN.md) for visual/accessibility constraints, this document for strategy,
[phase one](chatgpt-phase-one.md) for the staged integration plan, and the
[prototype record](chatgpt-prototype.md) for implementation and verification limits.
Inspect current code, open PRs and newer owner instructions before starting work.

Distinguish three kinds of statements below:

- **Direction:** evidence-grounded variants, explicit human judgment, shared contracts and an editorial interface.
- **Hypotheses:** discovery effectiveness, willingness to pay, package prices, allowances and future adjacent products.
- **Dated platform constraints:** externally controlled rules and eligibility; recheck before launch or commercial implementation.

A strategy document is not authorization to deploy, publish a plugin, change access, charge
customers, contact employers or submit applications. Those actions require their own approval.

## Current position and the next useful milestone

- [PR #58](https://github.com/JoshuaOliphant/resume-conjurer/pull/58) merged the synthetic
  one-unit/four-variant MCP panel, canonical picks, reopen reads and cancellation recovery.
  Its Python, DOM, Chromium and static checks passed. Those tests are not proof of actual host rendering.
- On November 4 Joshua reported that the demo works after fixes in the Resume Conjurer
  project. The project conversation records a repaired panel reopening with four alternatives
  and no selected variant. Treat this as reported demo progress, not full production acceptance.
- At this document's update, [PR #59](https://github.com/JoshuaOliphant/resume-conjurer/pull/59)
  contains the separate bundled-JavaScript repair and is open; main is `3f92ead`.
  Its validation report records ChatGPT Work browser rendering, evidence expansion,
  close/reopen and reload after a server restart, with all choices unselected.
  Actual-host pick persistence and desktop rendering remain explicitly unverified.
  Preserve that work. Do not reconstruct the old prototype or assume the repair is merged.
- Next, record a reproducible acceptance result for the repaired build: client/version and
  served commit, visible panel, explicit pick, close/reopen restoration, evidence, keyboard
  operation, cancellation and stale-write behavior. Successful tool calls alone are insufficient.

After that, advance one complete trustworthy tailoring workflow, not a broad job-search suite.
A working synthetic demo does not establish authentication, isolated real-data storage,
full generation/export integration, commercial eligibility or public-release readiness.

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
- Treat imported resumes, pasted job descriptions and tool results as data, not instructions.
  Avoid exposing career/JD text in analytics or unnecessary model-visible output.
- Before hosting real career data, enforce authentication, server-side ownership and workspace
  isolation, retention/deletion decisions and reliable recovery. App-only tool visibility is not authorization.

## Delivery sequence and decision gates

| Stage | Outcome | Evidence needed before expanding |
| --- | --- | --- |
| Repaired synthetic demo | A real ChatGPT panel can curate one unit and restore its pick. | Record actual host acceptance against the repaired build, not just CI/tool success. |
| Integrated private pilot | Existing inputs → variants → picks → review → reliable exports, sharing web contracts. | Isolated authorized workspaces, explicit state transitions, error/reconnect handling, end-to-end document checks. |
| Provider experiment | Optional second generation adapter. | Equal-corpus quality/cost evaluation; no model-price or latency assumptions substituted for measurements. |
| Identity convenience | Appropriate account linking/sign-in. | Verified developer eligibility and authorization design. Authentication/isolation cannot wait for a nicer sign-in button. |
| Paid web experiment | A bounded search pass for the independent web product. | Willingness to pay, sustainable full costs, clear package/expiry rules and policy-compliant acquisition. |
| Apply Assist, then lifecycle | Less form-filling drudgery; later tracking and interview preparation. | Explicit approval before submission, site reliability, bounded costs; evidence of repeated demand before integrations. |

These are decision gates, not a rigid release calendar. Do not bundle provider replacement,
identity polish, billing and autonomous application tooling into the next ChatGPT milestone.

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

## ChatGPT distribution and commercial boundaries

ChatGPT discovery is an acquisition **experiment**, not guaranteed demand or a guaranteed
free-to-paid funnel. The independent web product must have a viable acquisition/payment path.

Platform guidance rechecked November 4, 2026:

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

## What to learn, and what not to build yet

For a disclosed private pilot, measure curation completion, successful export, time to a
submittable document, regeneration, repeat usage and direct user trust/quality feedback.
Measure evidence trace completeness separately from claim support. Keep resume/JD contents
out of analytics. Commercial tests add willingness to pay, paid conversion, support burden and
full cost per completed application, not invented conversion or revenue targets.

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
5. Run applicable gates and record the exact commit/client for claims of success.
6. Update this document when a strategic decision changes; keep detailed implementation in
   the phase-one/prototype records instead of creating another competing strategy.
7. Ask for concrete decisions when needed: validated price/allowance, pilot audience,
   hosting/data policy, commercial eligibility or scope expansion. Do not infer them from this plan.
