from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from data.loader import CatalogStore
from nlu.action_classifier import (
    Action,
    classify,
    has_deferred_clarification,
    mention_summary,
)
from nlu.intent import Intent
from nlu.mention_extractor import extract_mentions
from routing.router import action_from_intent
from taxonomy.entity_matcher import EntityMatcher
from taxonomy.index_builder import build_indexes


@pytest.fixture(scope="module")
def action_matcher() -> EntityMatcher:
    path = Path(__file__).parents[1] / "data" / "catalog.sample.json"
    records = json.loads(path.read_text(encoding="utf-8"))["entities"]
    catalog = CatalogStore(records=records)
    indexes = build_indexes(catalog)
    return EntityMatcher(indexes, catalog)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Show MBA specializations", Action.LIST_SPECIALIZATIONS),
        (
            "Which universities offer Marketing specialization?",
            Action.LIST_PROVIDERS,
        ),
        (
            "I want an MBA in Marketing. What are my options?",
            Action.LIST_PROVIDERS,
        ),
        ("Compare LPU and NMIMS", Action.COMPARE),
        ("Compare Harvard and LPU", Action.COMPARE),
        ("Tell me about NMIMS", Action.GET_FACTS),
        ("Tell me about LPU MBA Marketing", Action.GET_FACTS),
        ("Which Online MBA is best for Marketing?", None),
        ("I need career guidance for MBA", None),
        ("Which MBA specialization is best for me?", None),
        ("Tell me about Marketing", Action.LIST_PROVIDERS),
        ("Tell me about Finance", Action.LIST_PROVIDERS),
        ("Tell me about HR", Action.LIST_PROVIDERS),
        ("Tell me about Business Analytics", Action.LIST_PROVIDERS),
        ("I'm confused", None),
    ],
)
def test_action_rules(
    action_matcher: EntityMatcher,
    message: str,
    expected: Action | None,
) -> None:
    mentions = extract_mentions(message, action_matcher)

    assert classify(mentions, message) is expected


def test_mention_summary_uses_only_deduplicated_catalog_names(
    action_matcher: EntityMatcher,
) -> None:
    mentions = extract_mentions(
        "Which universities offer Marketing specialization?",
        action_matcher,
    )

    assert mention_summary(mentions) == (
        "category=none, university=none, specialization=high(Marketing)"
    )
    assert "INR" not in mention_summary(mentions)


def test_action_classifier_stays_in_single_digit_milliseconds(
    action_matcher: EntityMatcher,
) -> None:
    message = "Which universities offer Marketing specialization?"
    mentions = extract_mentions(message, action_matcher)

    started = time.perf_counter()
    for _ in range(1_000):
        assert classify(mentions, message) is Action.LIST_PROVIDERS
    mean_ms = (time.perf_counter() - started) * 1_000 / 1_000

    assert mean_ms < 5


def test_unknown_names_route_to_unsupported_while_retaining_known_evidence() -> None:
    unknown_only = SimpleNamespace(
        universities=(),
        courses=(),
        specializations=(),
        unknown_entities=("Harvard",),
        unresolved_terms=(),
    )
    known_course = SimpleNamespace(
        entity_id="category:mba",
        confidence="HIGH",
        matched_span="MBA",
        canonical_name="MBA",
        start=0,
        end=1,
    )
    mixed = SimpleNamespace(
        universities=(),
        courses=(known_course,),
        specializations=(),
        unknown_entities=("Harvard",),
        unresolved_terms=(),
    )

    assert classify(unknown_only, "Tell me about Harvard") is Action.UNSUPPORTED_ENTITY
    assert classify(mixed, "Tell me about Harvard MBA") is Action.UNSUPPORTED_ENTITY


def test_medium_evidence_is_a_deferred_hint_not_an_early_action() -> None:
    medium = SimpleNamespace(
        entity_id="university:smu",
        confidence="MEDIUM",
        matched_span="SMU",
        canonical_name="Sikkim Manipal University",
        start=0,
        end=1,
    )
    mentions = SimpleNamespace(
        universities=(medium,),
        courses=(),
        specializations=(),
        unknown_entities=("SMU",),
        unresolved_terms=(),
    )

    assert has_deferred_clarification(mentions)
    assert classify(mentions, "Tell me about SMU") is None


@pytest.mark.parametrize(
    ("intent", "action"),
    [
        (Intent.FACTUAL, Action.GET_FACTS),
        (Intent.COMPARISON, Action.COMPARE),
        (Intent.ADVISORY, Action.RECOMMEND),
        (Intent.DISCOVERY, Action.DISCOVERY),
        (Intent.CALLBACK, Action.OPEN_LEAD_FORM),
        (Intent.CHITCHAT, Action.CHITCHAT),
        (Intent.UNRELATED, Action.UNRELATED),
        (Intent.UNRESOLVED_ENTITY, Action.UNSUPPORTED_ENTITY),
    ],
)
def test_legacy_intents_map_to_shared_actions(intent: Intent, action: Action) -> None:
    assert action_from_intent(intent) is action


def test_legacy_callback_action_normalizes_to_open_lead_form() -> None:
    assert action_from_intent(Action.CALLBACK) is Action.OPEN_LEAD_FORM
    assert action_from_intent(Action.OPEN_LEAD_FORM) is Action.OPEN_LEAD_FORM
