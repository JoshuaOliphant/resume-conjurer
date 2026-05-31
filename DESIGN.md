# Design

The visual system for the Conjurer web UI (`web/`). Calm, editorial, oxblood-on-white. Strategy and
audience live in [PRODUCT.md](PRODUCT.md). Tokens are implemented in
`web/app/static/css/app.css`.

## Theme

Light, paper-respecting. Scene: a job seeker at their desk on a weekday afternoon, working through
applications one at a time, wanting a quiet, focused space to read carefully and decide. A reading
tool, not a dashboard.

## Color

**Strategy: Restrained.** Oxblood carries identity; the surface stays pure white so the color does
the work. Accent (ink-teal) signals grounding/evidence and is used for links and traces only. All
values OKLCH.

| Role | Value | Use |
|------|-------|-----|
| `--bg` | `oklch(1 0 0)` | Page background (pure white) |
| `--surface` | `oklch(0.978 0.004 40)` | Rail, panels, notes |
| `--ink` | `oklch(0.215 0.014 35)` | Body text (~13:1 on white) |
| `--muted` | `oklch(0.475 0.012 38)` | Secondary text |
| `--primary` | `oklch(0.38 0.14 18)` | Oxblood: primary buttons, current step, selected variant |
| `--primary-soft` | `oklch(0.96 0.018 18)` | Selected-variant wash |
| `--accent` | `oklch(0.44 0.105 215)` | Ink-teal: links, evidence-trace disclosures |
| `--warn` / `--warn-soft` | `oklch(0.62 0.13 70)` / `oklch(0.96 0.04 80)` | The honest "limited evidence" note |

White text on the oxblood and ink-teal fills (mid-luminance, saturated). Dark ink only on pale or
neutral fills.

## Typography

Two families on a contrast axis, justified by "the document is the hero":

- **UI** — humanist system sans (`system-ui` stack). Headings, labels, buttons, nav.
- **Document** — quiet serif (`"Iowan Old Style", Palatino, Georgia, serif`). Reserved for the
  actual deliverable text: variant blocks and the stitched resume/cover letter, so they read like a
  document, not an app screen.

Fixed rem scale, ratio ~1.2 (`--text-xs` 0.78rem → `--text-3xl` 2.25rem). Prose capped ~60–75ch.
`text-wrap: balance` on titles.

## Layout

App shell: a slim sticky **pipeline rail** (Start → Outline → Curate → Review → Export) with
done/current/upcoming states and a connector line, plus a centered content column
(`--content-max: 44rem`). Rhythm comes from whitespace, not borders or cards. On ≤860px the rail
collapses to a horizontal step strip across the top.

## Components

- **Pipeline step**: numbered dot → check when done, ring + soft halo when current.
- **Variant block** (the curation crux): a vertical reading block (never a card grid), number key
  `1`–`4`, document-serif text, and an inline expandable evidence trace in the footer. Selected =
  oxblood key + soft wash + edge border + check, via `:has(input:checked)` with a JS fallback.
- **Evidence trace**: a `<details>` disclosure listing quoted master-resume lines with a monospace
  source path; ink-teal.
- **Ground note**: warm amber callout for the honest "limited evidence" state.
- **Document**: raised serif panel for the stitched output (`--shadow-2`).
- **Buttons**: `primary` (oxblood), `ghost`, `quiet`. Every interactive element has hover, focus
  (`:focus-visible` ink-teal ring), and active states.

## Motion

State-conveying only, 130–200ms, `ease-out-quint`. Progress bar and selection transitions. Full
`prefers-reduced-motion` override collapses all transitions.

## Bans honored

No side-stripe accents, no gradient text, no glassmorphism, no hero-metric template, no identical
card grids, no per-section uppercase eyebrows. No em dashes in prose (the product's own rule).
