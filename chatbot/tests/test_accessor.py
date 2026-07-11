from pydantic import BaseModel

from data.accessor import safe_get


class Child(BaseModel):
    value: str | None = None


class Parent(BaseModel):
    child: Child | None = None


def test_safe_get_reads_dict_model_and_sequence_paths() -> None:
    payload = {"rows": [{"child": Child(value="ok")}]}
    assert safe_get(payload, "rows[0].child.value", "missing") == "ok"
    assert safe_get(Parent(child=Child(value="yes")), ("child", "value")) == "yes"


def test_safe_get_never_raises_for_missing_or_malformed_paths() -> None:
    hostile = Parent(child=None)
    assert safe_get(hostile, "child.value.deep", "unavailable") == "unavailable"
    assert safe_get({"items": []}, "items.100.name", "unavailable") == "unavailable"
    assert safe_get(object(), [object()], "unavailable") == "unavailable"


def test_safe_get_preserves_explicit_null_at_the_leaf() -> None:
    assert safe_get({"placement_content": None}, "placement_content", "fallback") is None
