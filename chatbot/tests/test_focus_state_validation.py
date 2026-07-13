from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.accessor import validate_focus
from data.loader import CatalogStore
from session.state import Focus, hydrate_focus_concepts
from taxonomy.index_builder import TaxonomyIndexes, build_indexes


@pytest.fixture(scope="module")
def indexes() -> TaxonomyIndexes:
    path = Path(__file__).parents[1] / "data" / "catalog.sample.json"
    records = json.loads(path.read_text(encoding="utf-8"))["entities"]
    return build_indexes(CatalogStore(records=records))


def test_concept_state_defaults_are_isolated_and_clear_resets_both_schemas() -> None:
    first = Focus(
        university_concept="NMIMS Online",
        course_concept="mba",
        specialization_concept="Marketing",
        attribute="fee",
        source="explicit",
        sources={"university": "explicit", "course": "context"},
        unknown_entities=["Harvard"],
        university="uni-nmims",
        category="mba",
        specialization="Marketing",
        entity_id="spec-nmims-mba-marketing",
    )
    second = Focus()

    first.clear()

    assert first.model_dump(exclude_none=True) == {}
    assert second.sources == {}
    assert second.unknown_entities == []


def test_hydrate_focus_concepts_migrates_legacy_ids_once(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(
        university="uni-nmims",
        entity_id="course-nmims-mba",
    )

    hydrated = hydrate_focus_concepts(focus, indexes)
    first_snapshot = hydrated.model_dump()
    hydrate_focus_concepts(focus, indexes)

    assert hydrated is focus
    assert focus.university_concept == "NMIMS"
    assert focus.course_concept == "mba"
    assert focus.specialization_concept is None
    assert focus.source == "context"
    assert focus.sources == {"university": "context", "course": "context"}
    assert focus.model_dump() == first_snapshot


def test_hydrate_focus_concepts_uses_specialization_record_metadata(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(entity_id="spec-lpu-mba-finance")

    hydrate_focus_concepts(focus, indexes)

    assert focus.university_concept == "Lovely Professional University"
    assert focus.course_concept == "mba"
    assert focus.specialization_concept == "Finance Management"


def test_validate_focus_returns_one_concrete_course_for_valid_pair(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(
        university_concept="Narsee Monjee Institute of Management Studies Online",
        course_concept="mba",
        university="uni-nmims",
        sources={"university": "explicit", "course": "explicit"},
    )

    result = validate_focus(focus, indexes)

    assert result.valid
    assert result.compatible_entity_ids == ("course-nmims-mba",)
    assert not result.explicit_conflict


def test_validate_focus_returns_all_provider_records_for_one_concept_family(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(
        specialization_concept="Marketing",
        sources={"specialization": "explicit"},
    )

    result = validate_focus(focus, indexes)

    assert result.valid
    expected = {
        entity_id
        for entity_id in indexes.category_index.entities_for_specialization("Marketing")
        if indexes.entity_metadata[entity_id]["page_type"] == "specialization"
        and indexes.entity_metadata[entity_id]["specialization_name"] == "Marketing"
    }
    assert len(expected) > 1
    assert set(result.compatible_entity_ids) == expected


def test_validate_focus_late_binds_all_three_concepts(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(
        university_concept="Lovely Professional University",
        course_concept="mba",
        specialization_concept="Finance Management",
    )

    result = validate_focus(
        focus,
        indexes,
        explicit_slots={"university", "course", "specialization"},
    )

    assert result.valid
    assert result.compatible_entity_ids == ("spec-lpu-mba-finance",)


def test_validate_focus_marks_two_explicit_incompatible_concepts_as_conflict(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(
        university_concept="IGNOU",
        course_concept="mba",
        university="uni-ignou",
        category="mba",
    )

    result = validate_focus(
        focus,
        indexes,
        explicit_slots={"university", "course"},
    )

    assert not result.valid
    assert result.explicit_conflict
    assert result.compatible_entity_ids == ()
    assert result.reason == "explicit_catalog_conflict"
    # Explicit evidence is retained so a handler can explain the combination.
    assert focus.university_concept == "IGNOU"
    assert focus.course_concept == "mba"
    assert focus.university == "uni-ignou"
    assert focus.category == "mba"


def test_per_slot_context_provenance_overrides_stale_global_source(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(
        university_concept="IGNOU",
        course_concept="mba",
        source="explicit",
        sources={"university": "context", "course": "context"},
        university="uni-ignou",
        category="mba",
    )

    result = validate_focus(focus, indexes)

    assert not result.valid
    assert not result.explicit_conflict
    assert result.dropped_context_slots == ()


def test_validate_focus_drops_inherited_conflict_and_keeps_explicit_course(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(
        university_concept="IGNOU",
        course_concept="mba",
        source="explicit",
        sources={"university": "context", "course": "explicit"},
        university="uni-ignou",
        category="mba",
        entity_id="course-ignou-mca",
    )

    result = validate_focus(focus, indexes, explicit_slots={"course"})

    assert result.valid
    assert result.reason == "dropped_inherited_context"
    assert result.dropped_context_slots == ("university",)
    expected_courses = {
        entity_id
        for entity_id in indexes.category_index.entities_for_category("mba")
        if indexes.entity_metadata[entity_id]["page_type"] == "course"
    }
    assert set(result.compatible_entity_ids) == expected_courses
    assert focus.university_concept is None
    assert focus.university is None
    assert focus.course_concept == "mba"
    assert focus.category == "mba"
    assert focus.entity_id is None
    assert focus.sources == {"course": "explicit"}


def test_validate_focus_ignores_attribute_and_unknown_entity_metadata(
    indexes: TaxonomyIndexes,
) -> None:
    focus = Focus(
        attribute="fee",
        unknown_entities=["Harvard"],
        sources={"attribute": "explicit"},
    )

    result = validate_focus(focus, indexes, explicit_slots={"attribute"})

    assert result.valid
    assert result.compatible_entity_ids == ()
    assert result.reason == "no_entity_concepts"
    assert focus.attribute == "fee"
    assert focus.unknown_entities == ["Harvard"]
