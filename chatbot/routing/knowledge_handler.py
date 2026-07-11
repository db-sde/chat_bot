"""Small, curated answers to provider-independent education questions."""

from __future__ import annotations

from typing import Any

from response.builder import build_response
from schemas import ResponsePayload

NAAC_TEXT = (
    "NAAC is the National Assessment and Accreditation Council. It assesses the overall "
    "quality of an institution and awards an accreditation grade. A NAAC grade is useful "
    "context, but it is not the same as approval of every individual online program."
)

ONLINE_VALIDITY_TEXT = (
    "An online degree is generally valid when the university is recognized and was entitled "
    "by UGC-DEB to offer that exact online program for your admission session. Always verify "
    "the university, program, and academic year on the official UGC-DEB entitlement list "
    "before enrolling."
)


def knowledge_topic(message: str) -> str | None:
    text = str(message or "").casefold()
    if "naac" in text or "accreditation council" in text:
        return "naac"
    validity_markers = (
        "online degree valid",
        "valid online degree",
        "online degree recognized",
        "online degree recognised",
        "ugc-deb",
        "ugc deb",
        "degree validity",
    )
    if any(marker in text for marker in validity_markers):
        return "online_degree_validity"
    return None


async def handle_knowledge(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    topic: str | None = None,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Answer only curated topics; unknown questions remain an explicit fallback."""

    del state, catalog, category_index, llm
    selected = topic or knowledge_topic(message)
    if selected == "naac":
        return build_response(
            NAAC_TEXT,
            suggested_chips=["Is an online degree valid?", "Check university accreditations"],
        )
    if selected == "online_degree_validity":
        return build_response(
            ONLINE_VALIDITY_TEXT,
            suggested_chips=["What is NAAC?", "Browse universities", "Check UGC status"],
        )

    return build_response(
        "I can explain NAAC and online-degree validity, or look up a published university "
        "or course. Which of those would help?",
        suggested_chips=["What is NAAC?", "Is an online degree valid?", "Browse programs"],
    )


handle = handle_knowledge

__all__ = [
    "NAAC_TEXT",
    "ONLINE_VALIDITY_TEXT",
    "handle",
    "handle_knowledge",
    "knowledge_topic",
]
