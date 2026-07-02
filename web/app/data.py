# ABOUTME: Fixtures for the Conjurer web UI, modeling one tailored application.
# ABOUTME: Builds domain objects (the same types the live backend produces) for one Globex example.
"""Fixture data for the Conjurer web UI.

The real pipeline grounds every variant in lines drawn from a master resume. These fixtures
build the same ``app.domain`` objects the live workspace/generation adapters produce, so the
UI's trust mechanic is real: a variant carries its evidence trace, and the template can only
show traces that were put there. This module is the offline source the fake ``GenerationPort``
and the existing route tests draw from.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.domain import Application, Evidence, Frame, FRAMES, LintCheck, Unit, Variant


# --- Evidence pool ---------------------------------------------------------
# Lines lifted from the (fixture) master resume, keyed by id.

EVIDENCE: dict[str, Evidence] = {
    "billing-migration": Evidence(
        id="billing-migration",
        text="Led the migration of the billing platform from a monolith to event-driven "
        "services; invoice generation dropped from ~40s to under 2s.",
        source="master-resume → Experience → Senior Engineer, Northwind",
    ),
    "regional-rollout": Evidence(
        id="regional-rollout",
        text="Rolled the new billing backbone out across three regions (US, EU, APAC) "
        "with zero customer-visible downtime.",
        source="master-resume → Experience → Senior Engineer, Northwind",
    ),
    "oncall-reliability": Evidence(
        id="oncall-reliability",
        text="Owned the billing on-call rotation; cut paging volume 60% by adding "
        "idempotency keys and a dead-letter replay tool.",
        source="master-resume → Experience → Senior Engineer, Northwind",
    ),
    "internal-platform": Evidence(
        id="internal-platform",
        text="Built an internal service template and CI pipeline adopted by 9 teams, "
        "cutting new-service setup from two days to under an hour.",
        source="master-resume → Experience → Staff Engineer, Northwind",
    ),
    "mentorship": Evidence(
        id="mentorship",
        text="Mentored four engineers; two were promoted to senior within a year. "
        "Ran the weekly design-review forum.",
        source="master-resume → Leadership",
    ),
    "cost-savings": Evidence(
        id="cost-savings",
        text="Reduced billing infrastructure spend 35% by right-sizing consumers and "
        "moving batch reconciliation to spot capacity.",
        source="master-resume → Experience → Staff Engineer, Northwind",
    ),
    "values-craft": Evidence(
        id="values-craft",
        text="Summary: I like systems that are calm to operate and obvious to the next "
        "engineer who reads them.",
        source="master-resume → Summary",
    ),
}


def _v(id: str, text: str, *evidence_ids: str) -> Variant:
    """Build a Variant with its evidence resolved from the fixture pool.

    Resolving here (rather than in the type) is the fake adapter's job; the live repository
    resolves against the workspace pool instead. An unknown id fails loudly at build time.
    """
    missing = [e for e in evidence_ids if e not in EVIDENCE]
    if missing:
        raise ValueError(f"Variant {id!r} cites unknown evidence: {missing}")
    return Variant(id=id, text=text, evidence_items=tuple(EVIDENCE[e] for e in evidence_ids))


def _units() -> list[Unit]:
    return [
        Unit(
            id="cover-open",
            kind="cover_paragraph",
            label="Opening paragraph",
            context="Sets the frame. Globex's posting leads with regional scale, so the "
            "opening should land the billing migration as a scale story.",
            variants=[
                _v(
                    "cover-open-1",
                    "I spent the last three years turning a billing monolith into "
                    "something that scales: event-driven services that took invoice "
                    "generation from forty seconds to under two, across three regions. "
                    "Globex is solving that problem one size up, and I'd like to help.",
                    "billing-migration", "regional-rollout",
                ),
                _v(
                    "cover-open-2",
                    "Your Staff Platform Engineer posting describes the billing scale "
                    "problem I've been living in. I led the migration that moved "
                    "invoicing onto an event-driven backbone and rolled it across three "
                    "regions without customer-visible downtime.",
                    "billing-migration", "regional-rollout",
                ),
                _v(
                    "cover-open-3",
                    "I build platforms that stay calm under load. At Northwind I led the "
                    "billing migration to event-driven services and the three-region "
                    "rollout that followed; the work Globex describes reads like the next "
                    "chapter of it.",
                    "billing-migration", "regional-rollout", "values-craft",
                ),
                _v(
                    "cover-open-4",
                    "Forty seconds to two. That was the invoice-generation latency before "
                    "and after the billing migration I led at Northwind, and it's why your "
                    "Staff Platform Engineer role caught my attention.",
                    "billing-migration",
                ),
            ],
        ),
        Unit(
            id="bullet-migration",
            kind="resume_bullet",
            label="Headline bullet",
            context="The single strongest line. Globex weighs platform migrations heavily, "
            "so quantify the latency win and the regional reach.",
            variants=[
                _v(
                    "bullet-migration-1",
                    "Architected the billing-platform migration to event-driven services, "
                    "cutting invoice latency from 40s to under 2s across three regions.",
                    "billing-migration", "regional-rollout",
                ),
                _v(
                    "bullet-migration-2",
                    "Led the platform migration that moved billing onto an event-driven "
                    "backbone, taking invoice generation from 40 seconds to two and "
                    "clearing the path for regional rollout.",
                    "billing-migration", "regional-rollout",
                ),
                _v(
                    "bullet-migration-3",
                    "Migrated billing from a monolith to event-driven services, dropping "
                    "invoice generation 20x (40s → <2s) and shipping to US, EU, and APAC "
                    "with zero downtime.",
                    "billing-migration", "regional-rollout",
                ),
                _v(
                    "bullet-migration-4",
                    "Owned the end-to-end billing migration to event-driven services: 20x "
                    "faster invoicing and a three-region rollout with no customer impact.",
                    "billing-migration", "regional-rollout",
                ),
            ],
        ),
        Unit(
            id="bullet-reliability",
            kind="resume_bullet",
            label="Reliability bullet",
            context="Globex calls out on-call ownership. Lead with the paging-volume "
            "reduction and the concrete mechanisms.",
            variants=[
                _v(
                    "bullet-reliability-1",
                    "Cut billing on-call paging volume 60% by introducing idempotency keys "
                    "and a self-serve dead-letter replay tool.",
                    "oncall-reliability",
                ),
                _v(
                    "bullet-reliability-2",
                    "Owned the billing on-call rotation and reduced pages 60% through "
                    "idempotency keys and a dead-letter replay tool the team could run "
                    "themselves.",
                    "oncall-reliability",
                ),
                _v(
                    "bullet-reliability-3",
                    "Made billing calm to operate: idempotency keys and a replay tool for "
                    "dead-lettered events cut on-call paging by 60%.",
                    "oncall-reliability", "values-craft",
                ),
                _v(
                    "bullet-reliability-4",
                    "Reduced on-call load 60% on the billing platform by closing the "
                    "retry-safety gaps that caused most pages.",
                    "oncall-reliability",
                ),
            ],
        ),
        Unit(
            id="bullet-platform",
            kind="resume_bullet",
            label="Platform-tooling bullet",
            context="The role is platform-facing. This is the clearest 'force multiplier' "
            "evidence, so frame it around teams unblocked.",
            variants=[
                _v(
                    "bullet-platform-1",
                    "Built an internal service template and CI pipeline adopted by 9 teams, "
                    "cutting new-service setup from two days to under an hour.",
                    "internal-platform",
                ),
                _v(
                    "bullet-platform-2",
                    "Shipped a service template and CI pipeline that 9 teams adopted, "
                    "turning a two-day setup into a sub-hour one.",
                    "internal-platform",
                ),
                _v(
                    "bullet-platform-3",
                    "Gave 9 teams a paved road: a service template and CI pipeline that "
                    "took new-service setup from two days to under an hour.",
                    "internal-platform",
                ),
                _v(
                    "bullet-platform-4",
                    "Reduced new-service setup from two days to under an hour for 9 teams "
                    "by standardizing a service template and CI pipeline.",
                    "internal-platform",
                ),
            ],
        ),
        Unit(
            id="bullet-kubernetes",
            kind="resume_bullet",
            label="Kubernetes bullet",
            context="The JD lists 'deep Kubernetes operations at scale' as a requirement. "
            "The master resume only mentions it in passing.",
            grounding_note="Your master resume mentions Kubernetes only "
            "in the context of the service template, not as deep operational ownership. "
            "These variants stay within what your evidence actually supports; they don't "
            "claim scale you haven't documented. Add a stronger line to your master resume "
            "if you have one.",
            variants=[
                _v(
                    "bullet-kubernetes-1",
                    "Standardized service deployment on Kubernetes as part of the shared "
                    "CI pipeline adopted by 9 teams.",
                    "internal-platform",
                ),
                _v(
                    "bullet-kubernetes-2",
                    "Packaged the internal service template for Kubernetes, giving 9 teams "
                    "a consistent deploy path.",
                    "internal-platform",
                ),
                _v(
                    "bullet-kubernetes-3",
                    "Delivered Kubernetes-based deployment as part of the paved-road "
                    "tooling 9 teams now use.",
                    "internal-platform",
                ),
            ],
        ),
        Unit(
            id="cover-close",
            kind="cover_paragraph",
            label="Closing paragraph",
            context="Tie the work to Globex and to how you operate. Keep it short; the "
            "letter is already near the 350-word ceiling.",
            variants=[
                _v(
                    "cover-close-1",
                    "I like systems that are calm to operate and obvious to the next "
                    "engineer who reads them. That's the kind of platform I'd want to "
                    "build with your team.",
                    "values-craft",
                ),
                _v(
                    "cover-close-2",
                    "The thread through all of this is the same: platforms that stay "
                    "quiet under load and clear to whoever inherits them. I'd welcome the "
                    "chance to bring that to Globex.",
                    "values-craft",
                ),
                _v(
                    "cover-close-3",
                    "What I care about is leaving systems calmer than I found them. If "
                    "that's the kind of platform engineering Globex is investing in, I'd "
                    "love to talk.",
                    "values-craft",
                ),
                _v(
                    "cover-close-4",
                    "I'd bring the same instinct to Globex that runs through this resume: "
                    "build platforms that are calm to operate and obvious to read.",
                    "values-craft",
                ),
            ],
        ),
    ]


# The fixtures are static, so build the object graph once and share it. Nothing
# mutates the returned Application; per-request selections live in main.SELECTIONS.
@lru_cache(maxsize=1)
def get_application() -> Application:
    return Application(
        slug="globex-staff-platform",
        company="Globex",
        role="Staff Platform Engineer",
        jd_excerpt="We need an engineer who has taken a core platform through a major "
        "architectural migration at scale, owns reliability end to end, and multiplies the "
        "teams around them. Deep Kubernetes operations at scale a strong plus.",
        frame=Frame(
            name=FRAMES["scale"],
            rationale="Globex's posting leads with regional scale and a platform migration. "
            "Your strongest, most quantified evidence is exactly that story (40s → <2s, "
            "three regions), so the whole application is framed around scale, with "
            "reliability and the force-multiplier work as support, not the lead.",
        ),
        units=_units(),
        evidence=dict(EVIDENCE),
    )


# --- Lint (run on the stitched documents) ----------------------------------


def lint_results(cover_text: str) -> list[LintCheck]:
    """Run the grimoire checklist against the actual stitched cover letter.

    Computed from the real text so the displayed result can't drift from what's
    on screen, matching the product's "won't pretend" stance.
    """
    lower = cover_text.lower()
    has_em_dash = "—" in cover_text or "--" in cover_text
    fillers = [
        p for p in ("very", "really", "in order to")
        if re.search(rf"\b{re.escape(p)}\b", lower)
    ]
    generic_opener = lower.lstrip().startswith(
        ("i am excited", "i am writing", "i am thrilled", "as a")
    )
    words = len(cover_text.split())
    return [
        LintCheck(
            "No em dashes in prose",
            "Checked the cover letter." if not has_em_dash else "Found an em dash.",
            not has_em_dash,
        ),
        LintCheck(
            "No filler words",
            "No 'very', 'really', 'in order to'."
            if not fillers
            else f"Found: {', '.join(fillers)}.",
            not fillers,
        ),
        LintCheck(
            "No AI-generic openers",
            "Opening doesn't start with 'I am excited to'."
            if not generic_opener
            else "Opens with a generic phrase.",
            not generic_opener,
        ),
        LintCheck(
            "Cover letter under 350 words",
            f"Currently {words} words.",
            words < 350,
        ),
    ]
