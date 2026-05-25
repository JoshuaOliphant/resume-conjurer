---
title: Grimoire (template)
status: v0.1
---

# Grimoire

The encoded taste. Read by the generator at every step. Fill in the personal sections
(Identity, your strong-bullet examples, your cover-letter openers); the universal rules
below work for most people as-is. Update as patterns crystallize from real applications.

## Identity (How I Position)

<!-- FILL THIS IN. Describe, in 3-5 sentences:
  - What you do and the rare combination you bring.
  - The kind of role you are aiming at and the ownership level you assume.
  - The throughline of your career (what consistently energizes you).
Example (fictional):
  "I am a senior data engineer (8 years) who builds reliable streaming pipelines and the
  tooling teams use to trust their data. The rare combination is deep pipeline internals
  plus a product sense for what analysts actually need. Every role I take, I come in to own
  a system end to end." -->

Every application assumes I am coming in to own something. Cover letter language reflects
ownership, not assistance: "I led", "I architected", "I built" — not "I contributed to",
"I helped with", "I supported."

## Voice

- **First person, always.** "I built", "I designed", "I led". Never "we" or passive voice.
- **Specificity over abstraction.** Name the technology, the system, the number. "the billing
  service" not "the API"; "Python 2 to 3" not "modernized the stack"; "12k requests/sec" not
  "high traffic."
- **No em dashes. Ever.** Restructure into two sentences, use a semicolon, or use a comma.
- **No "not just X, it's Y"** correlative constructions. Pick the stronger half. State it directly.
- **No filler**: cut "just", "actually", "a bit", "really", "basically", "pretty much", "kind of",
  "sort of", "fine".
- **No AI-generic openers**: "In today's fast-moving landscape", "Let's dive into", "I'm
  passionate about", "I would be thrilled to". Lead with a fit assertion grounded in something
  specific.
- **No self-deprecation**: "I built a small tool", "nothing fancy". State what was built.
- **No disclaimers**: "I could be wrong, but", "this is just my opinion". State the claim.

## Claim Discipline (Truth Constraint)

Every claim in every generated variant must be grounded in source material. The model
re-frames; it does not invent.

- Numbers are exact. Use a number only if a source document says so. Never "many" or "lots".
- Adoption/impact claims require evidence in the master resume or evidence pool.
- If a desired claim cannot be sourced, the generator must flag it rather than invent.

Each variant emits a citation pointer: a path + line reference or quoted span from the
evidence pool. The lint pass and curation verify the citation.

## Resume Bullet Patterns

```
<Action verb> <specific system/scope> <quantified outcome or distinguishing detail>,
<technical specifics> <impact on team / org / production>.
```

Examples (fictional — replace with your own strongest bullets):

- "Architected the billing-service migration from a monolith to event-driven microservices over
  an 18-month roadmap, cutting invoice-generation latency from 40s to under 2s across 3 regions."
- "Built the data-quality framework adopted by 6 analytics teams, catching schema drift before it
  reached dashboards and reducing data incidents by 70%."
- "Led the on-call tooling rewrite that lifted incident-triage accuracy from 60% to 92% and cut
  mean time to acknowledge by half."

Verb bank: Architected, Led, Engineered, Built, Drove, Spearheaded, Delivered, Designed, Migrated,
Containerized, Authored, Developed, Diagnosed, Fixed, Established, Championed, Shipped, Extended.

Avoid weak verbs: Worked on, Helped with, Contributed to, Was involved in, Participated in,
Supported, Assisted with.

## Cover Letter Patterns

### Structure: 3-4 Paragraphs

**Paragraph 1 — Fit assertion.** Opens with a claim tying this specific team/role to what you
already do. Anchors in something specific about the company. No "I am writing to express my interest."

Example (fictional): "Stripe's data platform team is solving the exact reliability problems I work
on every day."

**Paragraph 2 — Evidence stack.** 3-5 concrete projects, each with a quantified or adoption detail.
Ownership language. Lead with the most recent and most relevant.

**Paragraph 3 — Strategic angle.** Why this role specifically. The angle varies:
- External prestige company → scale/fundamentals/excellence
- Internal transfer → friction frame (name what you cannot do where you are)
- AI-first startup → conviction frame (name the thesis bet)
- Platform/infra company → multiplier frame (name the leverage)

**Paragraph 4 (optional) — Skills bridge + ask.** Short. "I bring X, Y, Z. I would welcome a
conversation about where the team has gaps I could fill."

### Length

Under 350 words total. The linter flags cover letters over that.

### What Never Appears

- "I am writing to express my interest in..."
- "I would be honored to..."
- "Please find my resume attached..."
- "I believe my skills are a perfect match..."
- Generic gratitude paragraphs at the close.

### Variant Dimensions for Cover Letters

1. Opening fit assertion — which specific thing about the company anchors paragraph 1
2. Evidence selection — which 3-5 projects get featured, and in what order
3. Strategic angle — scale / friction / conviction / multiplier
4. Tone register — confident-direct vs confident-warm

## Anti-Patterns Specific to Resumes and Cover Letters

- "Synergy", "leverage" (as verb), "rockstar", "ninja", "guru"
- "Passionate about" (everyone says this)
- "Results-oriented", "detail-oriented", "self-starter" (show, don't tell)
- "Looking for an opportunity to..." (positions you as needy)
- "Hard worker", "excellent communication skills" (table stakes)
- Vague impact: "improved efficiency", "drove results", "delivered value"

## Linter Checklist

1. Em dash check: zero "—" instances
2. Correlative check: zero "not just X, it's Y" patterns
3. Filler word sweep
4. AI-generic opener check
5. "We" check: first person singular throughout
6. Self-deprecation audit
7. Disclaimer audit
8. Vague-impact check: every bullet has a specific noun and a specific outcome
9. Citation check: every claim has an evidence source
10. Length check: cover letter under 350 words
