# ABOUTME: Exercises exact source snapshots, conservative claim labels, and grimoire acceptance checks.
# ABOUTME: Uses synthetic career facts and voice samples without any model or filesystem calls.
import copy

import pytest

from app.onboarding import (
    SECTIONS,
    acceptance_questions,
    build_prompt,
    claim_ledger,
    delivery_status,
    empty_state,
    review_draft,
    reviewed_snippets,
    source_lines,
    source_questions,
    validate_proposal,
)

ANSWERS = {"roles": "Seek Staff Engineer ownership.", "examples": "implemented the billing migration.",
           "voice": "Use direct language.\nKeep claims grounded.\nLead with outcomes.\nWrite short letters.\nAvoid hype."}


def _payload():
    phrases = [(ANSWERS["roles"], "answer.roles L1"), *[(text, f"answer.voice L{index}") for index, text in enumerate(ANSWERS["voice"].splitlines(), 1)]]
    return {"sections": [{"title": title, "items": [{"text": phrase, "kind": "preference", "source_id": source_id,
                         "quote": phrase, "status": "unknown"}]} for title, (phrase, source_id) in zip(SECTIONS, phrases, strict=True)]}


@pytest.fixture
def state():
    value = empty_state()
    value["answers"] = ANSWERS.copy()
    value["master_revision"] = "master-hash"
    value["selected"] = source_lines("# Casey\n\n- Saved 42%", "master-hash", [])
    draft, claims = validate_proposal(_payload(), reviewed_snippets(value))
    value.update(draft=draft, proposal=draft, claims=claims)
    return value


def test_exact_source_lines_and_outbound_prompt_exclude_unselected_originals(state):
    optional = [{"text": "Voice only\n\ngrew revenue 80%", "revision": "extracted-hash", "original_hash": "original-hash",
                 "kind": "voice sample", "filename": "voice.txt", "warnings": ["Review order"]}]
    sources = source_lines("# Casey\n\nSaved 42%", "master-hash", optional)
    assert [(source["id"], source["text"]) for source in sources] == [
        ("master-resume.md L1", "# Casey"), ("master-resume.md L3", "Saved 42%"),
        ("original-hash L1", "Voice only"), ("original-hash L3", "grew revenue 80%")]
    state["selected"] = [sources[1]]
    prompt = build_prompt(state)
    assert "Saved 42%" in prompt and "master-hash" in prompt
    assert all(line in prompt for answer in ANSWERS.values() for line in answer.splitlines())
    assert "grew revenue 80%" not in prompt and "original-hash" not in prompt


@pytest.mark.parametrize("text, expected", [("planned rollout", "planned"), ("SHIPPED release", "shipped"),
                                              ("commit abc", "unknown"), ("planned then shipped", "unknown"),
                                              ("billing migration has not shipped", "unknown"), ("will ship observed result", "unknown")])
def test_status_is_explicit_and_never_inferred_from_a_commit(text, expected):
    assert delivery_status(text) == expected


def test_conflicting_metrics_status_dates_and_duplicates_remain_questions():
    def facts(*values):
        return [{"id": str(index), "text": text, "kind": "career fact"} for index, text in enumerate(values)]
    assert "Conflicting metrics" in source_questions(facts("Revenue grew 40%", "Revenue grew 80%"))[0]
    assert "Conflicting metrics" in source_questions(facts("planned billing migration", "shipped billing migration"))[0]
    assert "Duplicate" in source_questions(facts("Built service", "Built service"))[0]
    assert "backwards" in source_questions(facts("Engineer 2024-2021"))[0]
    assert source_questions(facts("Engineer 2021-Present", "Different project 2020-2024")) == []
    assert source_questions(facts("42", "80")) == []
    assert source_questions([{ "id": "voice", "text": "grew revenue 80%", "kind": "voice sample"}]) == []


@pytest.mark.parametrize("change,error", [
    (lambda value: None, "malformed"), (lambda value: {"sections": "bad"}, "malformed"),
    (lambda value: {**value, "draft": "I grew revenue 80%", "claims": []}, "malformed"),
    (lambda value: {"sections": []}, "omitted"),
    (lambda value: {"sections": [None] * 6}, "omitted"),
    (lambda value: {"sections": list(reversed(value["sections"]))}, "reordered"),
    (lambda value: {"sections": [{**section, "items": []} for section in value["sections"]]}, "empty"),
    (lambda value: {"sections": [{**section, "items": "bad"} for section in value["sections"]]}, "empty"),
])
def test_malformed_or_unledgered_model_text_cannot_become_a_draft(change, error):
    with pytest.raises(ValueError, match=error):
        validate_proposal(change(_payload()), [])


@pytest.mark.parametrize("item", [None, {}, {"text": ""}, {"text": "one\ntwo"}, {"kind": "bogus"}, {"status": "bogus"}, {"quote": 42}])
def test_malformed_claims_are_rejected(item, state):
    payload = _payload()
    payload["sections"][0]["items"] = [item if item is None else {**payload["sections"][0]["items"][0], **item}]
    if item == {}:
        payload["sections"][0]["items"] = [{}]
    with pytest.raises(ValueError, match="malformed claim"):
        validate_proposal(payload, reviewed_snippets(state))


@pytest.mark.parametrize("source,item,flag", [
    ({"text": "grew revenue 80%", "kind": "voice sample"}, {"text": "grew revenue 80%", "kind": "fact", "quote": "grew revenue 80%"}, "voice sample"),
    ({"text": "Saved 42%", "kind": "career fact"}, {"text": "Saved 80%", "quote": "Saved 42%"}, "Numbers"),
    ({"text": "planned migration", "kind": "career fact"}, {"text": "shipped migration", "kind": "fact", "quote": "planned migration", "status": "shipped"}, "Delivery status"),
    ({"text": "the team implemented migration", "kind": "career fact"}, {"text": "I implemented migration", "quote": "the team implemented migration"}, "attribution"),
    ({"text": "2021-2024", "kind": "career fact"}, {"text": "2021 to 2024", "quote": "2021-2024"}, "Role dates"),
    ({"text": "I have not shipped the release.", "kind": "career fact"}, {"text": "shipped the release.", "kind": "preference", "quote": "shipped the release."}, "Delivery status"),
    ({"text": "Built reliable services", "kind": "career fact"}, {"text": "Owned all services", "kind": "fact", "quote": "Built reliable services"}, "not an exact"),
    ({"text": "Exact words", "kind": "career fact"}, {"quote": "not present"}, "Invalid"),
    ({"text": "Exact words", "kind": "career fact"}, {"quote": ""}, "Invalid"),
])
def test_unsupported_claims_are_needs_review_and_never_verified(source, item, flag, state):
    payload = _payload()
    base = payload["sections"][0]["items"][0]
    base.update(source_id="source", **item)
    snippet = {**source, "id": "source", "revision": "source-revision"}
    _, claims = validate_proposal(payload, [snippet, *reviewed_snippets(state)])
    assert claims[0]["label"] == "needs review"
    assert any(flag in question for question in claims[0]["flags"])
    assert claims[0]["revision"] == "source-revision"


def test_missing_pointer_and_duplicate_sentence_are_not_supported(state):
    payload = _payload()
    payload["sections"][0]["items"][0]["source_id"] = "missing"
    payload["sections"][1]["items"] = copy.deepcopy(payload["sections"][0]["items"])
    _, claims = validate_proposal(payload, reviewed_snippets(state))
    assert claims[0]["label"] == "needs review" and claims[0]["revision"] == ""
    assert any("Duplicate" in question for question in claims[1]["flags"])


def test_exact_factual_sentence_is_source_linked_and_stale_snapshots_are_unchecked(state):
    payload = _payload()
    payload["sections"][0]["items"][0].update(text="Saved 42%", quote="Saved 42%", kind="fact", source_id="master-resume.md L3")
    state["selected"][1]["text"] = "Saved 42%"
    draft, claims = validate_proposal(payload, reviewed_snippets(state))
    assert claims[0]["label"] == "source-linked"
    state.update(draft=draft, proposal=draft, claims=claims)
    assert acceptance_questions(state, draft, "master-hash", False) == []
    assert claim_ledger(state, draft, "changed-hash")[0]["label"] == "needs review"
    assert any("master resume changed" in question for question in acceptance_questions(state, draft, "changed-hash", False))
    state["selected"][1]["revision"] = "new-snapshot"
    assert claim_ledger(state, draft, "master-hash")[0]["label"] == "needs review"
    state["selected"] = []
    assert claim_ledger(state, draft, "master-hash")[0]["label"] == "needs review"


def test_manual_edits_do_not_inherit_support_and_need_attestation(state):
    edited = state["draft"].replace("Use direct language.", "Use concise language.")
    ledger = claim_ledger(state, edited, "master-hash")
    assert all(entry["text"] != "Use direct language." for entry in ledger)
    assert ledger[-1]["source_id"] == "Manual edit"
    assert ledger[-1]["label"] == "user-attested"
    assert acceptance_questions(state, edited, "master-hash", True) == []
    assert any("Attest" in question for question in acceptance_questions(state, edited, "master-hash", False))
    assert acceptance_questions(state, state["draft"].replace("\n", "\r\n"), "master-hash", False) == []
    assert any("Draft numbers" in question for question in acceptance_questions(state, edited + "\n- Grew revenue 80%", "master-hash", True))
    state["claims"] = []
    assert any("Review a Claude draft" in question for question in acceptance_questions(state, edited, "master-hash", True))


def test_flagged_model_claim_blocks_acceptance_even_when_edits_are_attested(state):
    state["claims"][0]["flags"] = ["Invalid quote"]
    assert "Invalid quote" in acceptance_questions(state, state["draft"], "master-hash", True)


@pytest.mark.parametrize("separator", ["\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_claim_line_separators_cannot_bypass_acceptance(separator, state):
    payload = _payload()
    payload["sections"][0]["items"][0]["text"] = f"Owned all projects{separator}Invented facts"
    with pytest.raises(ValueError, match="malformed claim"):
        validate_proposal(payload, reviewed_snippets(state))


def test_voice_fact_misclassified_as_preference_cannot_borrow_an_unrelated_metric(state):
    payload = _payload()
    payload["sections"][0]["items"][0].update(text="I grew revenue 80%", quote="I grew revenue 80%", source_id="voice")
    sources = [{"id": "voice", "text": "I grew revenue 80%", "kind": "voice sample", "revision": "voice-hash"},
               {"id": "fact", "text": "Observed cache hit rate 80%", "kind": "career fact", "revision": "fact-hash"}]
    draft, claims = validate_proposal(payload, sources + reviewed_snippets(state))
    assert claims[0]["label"] == "needs review"
    state.update(draft=draft, proposal=draft, claims=claims, selected=sources)
    assert any("voice sample" in question for question in acceptance_questions(state, draft, "master-hash", True))


def test_related_project_sources_with_different_metrics_and_delivery_are_unresolved():
    sources = [{"id": "plan", "text": "Planned payment migration to reduce cost 42%", "kind": "career fact"},
               {"id": "ship", "text": "Shipped payment migration reducing cost 12%", "kind": "career fact"}]
    assert any("Conflicting" in question and "plan" in question and "ship" in question for question in source_questions(sources))


def test_attesting_manual_edits_does_not_authorize_unlinked_accomplishments(state):
    draft = state["draft"] + "\n- I shipped the payment migration.\n"
    assert any("factual additions" in question for question in acceptance_questions(state, draft, "master-hash", True))


@pytest.mark.parametrize("sources", [
    [{"text": "x", "kind": "career fact"}] * 257,
    [{"text": "x" * 8193, "kind": "career fact"}],
    [{"text": "x" * 8192, "kind": "career fact"}] * 9,
])
def test_sources_are_bounded_before_conflict_comparison(sources):
    with pytest.raises(ValueError, match="at most"):
        source_questions(sources)


def test_mixed_voice_preference_and_factual_sentence_cannot_be_attested(state):
    payload = _payload()
    source = {"id": "mixed", "text": "Use direct language. I owned all projects.", "kind": "voice sample", "revision": "mixed-hash"}
    payload["sections"][0]["items"][0].update(text=source["text"], quote=source["text"], source_id="mixed")
    draft, claims = validate_proposal(payload, [source, *reviewed_snippets(state)])
    state.update(draft=draft, proposal=draft, claims=claims, selected=[source])
    assert any("voice sample" in question for question in acceptance_questions(state, draft, "master-hash", True))


def test_unrecognized_heading_is_manual_content_requiring_review(state):
    draft = state["draft"] + "\n## I owned all projects.\n"
    assert any("factual additions" in question for question in acceptance_questions(state, draft, "master-hash", True))


def test_related_nonconflicting_sources_do_not_invent_a_conflict():
    assert source_questions([{"id": "a", "text": "Built billing service", "kind": "career fact"},
                             {"id": "b", "text": "Built billing pipeline", "kind": "career fact"}]) == []


def test_model_cannot_return_unbounded_claim_list(state):
    payload = _payload()
    payload["sections"][0]["items"] *= 33
    with pytest.raises(ValueError, match="too many"):
        validate_proposal(payload, reviewed_snippets(state))


@pytest.mark.parametrize("source_kind,source_text,draft_text,status,label", [
    ("career fact", "Built a service.", "Built a service.", "unknown", "source-linked"),
    ("career fact", "- Built a service.", "Built a service.", "unknown", "source-linked"),
    ("career fact", "Shipped a service.", "Shipped a service.", "shipped", "source-linked"),
    ("voice sample", "Grew revenue 80%.", "Grew revenue 80%.", "unknown", "needs review"),
    ("career fact", "Built a service.", "Owned every service.", "unknown", "needs review"),
])
def test_local_draft_review_binds_only_exact_selected_career_spans(state, source_kind, source_text, draft_text, status, label):
    state["selected"] = [{"id": "source", "text": source_text, "kind": source_kind, "revision": "source-hash"}]
    claims = review_draft(state, "# Grimoire\n\n## Identity\n- " + draft_text + "\n")
    assert claims[0]["status"] == status and claims[0]["label"] == label
    assert claims[0]["source_id"] == ("source" if label == "source-linked" else "Manual edit")


def test_local_review_keeps_ambiguous_sources_duplicates_and_style_edits_honest(state):
    state["selected"] = [{"id": "a", "text": "Built a service.", "kind": "career fact", "revision": "a"},
                         {"id": "b", "text": "Built a service.", "kind": "career fact", "revision": "b"}]
    draft = "# Grimoire\n- Built a service.\n- Use concise language.\n- Use concise language.\n"
    state["claims"] = review_draft(state, draft)
    assert state["claims"][0]["label"] == "needs review"
    assert state["claims"][1]["label"] == "user-attested"
    assert state["claims"][2]["label"] == "needs review"
    assert any("Duplicate" in question for question in acceptance_questions(state, draft, "master-hash", True))


@pytest.mark.parametrize("source_text,draft_text", [
    ("I have not shipped the release.", "shipped the release."),
    ("The team, not I, built the service.", "I, built the service."),
])
def test_local_review_rejects_clipped_negation_and_personal_attribution(state, source_text, draft_text):
    state["selected"] = [{"id": "career", "text": source_text, "kind": "career fact", "revision": "source-hash"}]
    draft = "# Grimoire\n\n## Identity\n- " + draft_text + "\n"
    state["claims"] = review_draft(state, draft)
    state["proposal"] = draft
    assert state["claims"][0]["label"] == "needs review"
    assert acceptance_questions(state, draft, "master-hash", True)
