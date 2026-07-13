"""Extract raw, independent slot candidates without making resolution decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from taxonomy.alias_tables import normalize_text

TOKEN_RE = re.compile(r"[a-z0-9]+(?:['&-][a-z0-9]+)?", re.IGNORECASE)
REFERENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "course",
        re.compile(
            r"\b(?:this|that|the)\s+(?:course|program|degree)\b|\b(?:universit(?:y|ies)|uni)\s+(?:that\s+)?provide\s+(?:this|it)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "university",
        re.compile(r"\b(?:this|that|the)\s+(?:university|uni|college|institute)\b", re.IGNORECASE),
    ),
    (
        "entity",
        re.compile(r"\b(?:it|this\s+one|that\s+one|this\s+program)\b", re.IGNORECASE),
    ),
    (
        "course",
        re.compile(
            r"\b(?:for\s+)?which\s+(?:uni(?:versity)?|universities)\b|"
            r"\bwho\s+offers\s+(?:this|it)\b",
            re.IGNORECASE,
        ),
    ),
)

_TITLE_OR_ACRONYM = re.compile(r"\b(?:[A-Z]{2,}|[A-Z][a-z]+)(?:\s+(?:[A-Z]{2,}|[A-Z][a-z]+))*\b")
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")
_BARE_TITLE_OR_ACRONYM = re.compile(
    r"^\s*(?:[A-Z]{2,}|[A-Z][a-z]+)(?:\s+(?:[A-Z]{2,}|[A-Z][a-z]+))*"
    r"(?:\s+(?:[Uu]niversity|[Uu]ni|[Cc]ollege|[Ii]nstitute))?\s*[?.!,]*\s*$",
)
_ENTITY_FRAME = re.compile(
    r"\b(?:about|at|from|compare|comparison|versus|vs\.?|"
    r"university|uni|college|institute)\b",
    re.IGNORECASE,
)
_OPEN_REASONING_ENTITY_FRAME = re.compile(
    r"\b(?:guide\s+me|confus(?:ed|ing)(?:\s+between)?|"
    r"help\s+(?:me\s+)?(?:decid(?:e|ing)|choose)|"
    r"which\s+should\s+i(?:\s+choose)?|recommend|suggest)\b",
    re.IGNORECASE,
)
_QUERY_AND_STRUCTURE_WORDS = frozenset(
    {
        "a",
        "about",
        "advice",
        "advisory",
        "affordable",
        "all",
        "an",
        "and",
        "are",
        "at",
        "available",
        "best",
        "better",
        "browse",
        "budget",
        "bye",
        "can",
        "career",
        "careers",
        "cheap",
        "cheapest",
        "choose",
        "college",
        "colleges",
        "compare",
        "comparison",
        "complete",
        "completed",
        "confused",
        "counsellor",
        "counselor",
        "cost",
        "could",
        "course",
        "courses",
        "deciding",
        "degree",
        "degrees",
        "distance",
        "do",
        "explain",
        "explore",
        "flexible",
        "for",
        "from",
        "give",
        "good",
        "graduated",
        "graduation",
        "guidance",
        "guide",
        "hello",
        "help",
        "hey",
        "highest",
        "hi",
        "how",
        "have",
        "i",
        "in",
        "information",
        "institute",
        "institutes",
        "is",
        "know",
        "list",
        "lakh",
        "lakhs",
        "low",
        "lower",
        "me",
        "my",
        "need",
        "news",
        "no",
        "of",
        "offer",
        "offers",
        "online",
        "options",
        "or",
        "please",
        "program",
        "programme",
        "programmes",
        "programs",
        "provide",
        "provider",
        "providers",
        "provides",
        "reasonable",
        "recommend",
        "recommendation",
        "show",
        "should",
        "somebody",
        "someone",
        "specialisation",
        "specialisations",
        "specialization",
        "specializations",
        "starting",
        "suggest",
        "tell",
        "thank",
        "thanks",
        "the",
        "this",
        "today",
        "to",
        "top",
        "uni",
        "universities",
        "university",
        "versus",
        "vs",
        "want",
        "what",
        "which",
        "why",
        "who",
        "with",
        "would",
        "yes",
        "you",
    }
)
_QUERY_WORD_ALTERNATION = "|".join(
    sorted(map(re.escape, _QUERY_AND_STRUCTURE_WORDS), key=len, reverse=True)
)
_QUERY_AND_STRUCTURE_PATTERN = re.compile(rf"\b(?:{_QUERY_WORD_ALTERNATION})\b")


@dataclass(slots=True)
class MentionResult:
    """Raw matcher output; candidate arbitration belongs to resolver/."""

    universities: list[Any] = field(default_factory=list)
    courses: list[Any] = field(default_factory=list)
    specializations: list[Any] = field(default_factory=list)
    reference: str | None = None
    tokens: list[str] = field(default_factory=list)
    # Terms requested in a structured entity-bearing phrase that the taxonomy did
    # not resolve.  This is deliberately conservative: it is used to acknowledge a
    # partial match, never to manufacture a new catalog entity.
    unresolved_terms: list[str] = field(default_factory=list)
    # Normalized unknown catalog-looking concepts retained after all deterministic
    # match layers have run. Existing response code continues to consume the
    # display-oriented ``unresolved_terms`` compatibility projection above.
    unknown_entities: list[str] = field(default_factory=list)
    # Catalog-generated attribute concepts (fee, eligibility, duration, etc.)
    # are independent of university/course/specialization candidates.
    attributes: list[str] = field(default_factory=list)

    @property
    def has_explicit_mentions(self) -> bool:
        return bool(self.universities or self.courses or self.specializations)

    @property
    def has_high_confidence_mention(self) -> bool:
        return any(
            getattr(candidate, "confidence", None) == "HIGH"
            for candidate in (
                *self.universities,
                *self.courses,
                *self.specializations,
            )
        )

    @property
    def has_medium_confidence_mention(self) -> bool:
        return any(
            getattr(candidate, "confidence", None) == "MEDIUM"
            for candidate in (
                *self.universities,
                *self.courses,
                *self.specializations,
            )
        )

    def candidates_for(self, slot_type: str) -> list[Any]:
        return {
            "university": self.universities,
            "course": self.courses,
            "category": self.courses,
            "specialization": self.specializations,
        }.get(slot_type, [])


def tokenize(message: str) -> list[str]:
    """Normalize a user utterance into taxonomy-safe lowercase tokens."""

    return [match.group(0).lower().strip("-'&") for match in TOKEN_RE.finditer(message)]


def detect_reference(message: str) -> str | None:
    for kind, pattern in REFERENCE_PATTERNS:
        if pattern.search(message):
            return kind
    return None


def _prefer_precise_catalog_families(
    candidates: list[Any],
    indexes: Any = None,
) -> list[Any]:
    """Prune broad publisher aliases when a more precise catalog label exists.

    Large feeds can legitimately repeat one alias across provider records. They
    can also attach a broad alias such as ``marketing`` to both ``Marketing`` and
    ``Digital Marketing``. For one input span, an exact canonical concept wins.
    Otherwise, only an explicit publisher alias may narrow a shared-token cluster
    (``Jain`` vs ``Arka Jain``); prefix position alone must not collapse a genuine
    brand family such as ``Manipal``. Provider duplicates remain intact.
    """

    groups: dict[tuple[Any, ...], list[Any]] = {}
    order: list[tuple[Any, ...]] = []
    for candidate in candidates:
        key = (
            getattr(candidate, "slot_type", None),
            getattr(candidate, "start", None),
            getattr(candidate, "end", None),
            normalize_text(getattr(candidate, "matched_span", "")),
            getattr(candidate, "confidence", None),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(candidate)

    result: list[Any] = []
    for key in order:
        values = groups[key]
        span = key[3]
        if not span or len(values) == 1:
            result.extend(values)
            continue
        exact = [
            candidate
            for candidate in values
            if normalize_text(getattr(candidate, "canonical_name", "")) == span
        ]
        if exact:
            result.extend(exact)
            continue

        alias_index = getattr(indexes, "alias_index", {})
        slot_aliases = alias_index.get(key[0], {}) if hasattr(alias_index, "get") else {}
        explicit_alias_ids = (
            slot_aliases.get(span, ()) if hasattr(slot_aliases, "get") else ()
        )
        explicit_aliases = [
            candidate
            for candidate in values
            if getattr(candidate, "entity_id", None) in explicit_alias_ids
        ]
        result.extend(explicit_aliases or values)
    return result


def _drop_query_language_fuzzy_matches(candidates: list[Any]) -> list[Any]:
    """Never turn conversational control words into typo-corrected entities."""

    result: list[Any] = []
    for candidate in candidates:
        span_tokens = set(normalize_text(getattr(candidate, "matched_span", "")).split())
        fuzzy = int(getattr(candidate, "layer", 0) or 0) == 4
        if fuzzy and span_tokens and span_tokens <= _QUERY_AND_STRUCTURE_WORDS:
            continue
        result.append(candidate)
    return result


def _display_unresolved(value: str) -> str:
    words = [word for word in value.strip(" ,.-").split() if word]
    return " ".join(word.upper() if len(word) <= 3 else word.title() for word in words)


def _attribute_index(matcher: Any) -> Any:
    indexes = getattr(matcher, "indexes", None)
    return getattr(indexes, "attribute_index", {}) if indexes is not None else {}


def _extract_attributes(message: str, attribute_index: Any) -> list[str]:
    tokens = normalize_text(message).split()
    if not tokens or not attribute_index:
        return []
    longest = max((len(str(term).split()) for term in attribute_index), default=1)
    attributes: list[str] = []
    seen: set[str] = set()
    for size in range(min(longest, len(tokens)), 0, -1):
        for start in range(len(tokens) - size + 1):
            term = " ".join(tokens[start : start + size])
            for concept in sorted(attribute_index.get(term, ())):
                if concept not in seen:
                    seen.add(concept)
                    attributes.append(concept)
    return attributes


def _remove_known_phrases(
    value: str,
    candidates: list[Any],
    attribute_index: Any | None = None,
) -> str:
    remaining = normalize_text(value)
    phrases = sorted(
        {
            normalize_text(getattr(candidate, "matched_span", ""))
            for candidate in candidates
            if getattr(candidate, "matched_span", None)
        },
        key=len,
        reverse=True,
    )
    remaining_tokens = set(remaining.split())
    if remaining_tokens and any(
        remaining_tokens.issubset(set(phrase.split())) for phrase in phrases
    ):
        return ""
    for phrase in phrases:
        remaining = re.sub(rf"\b{re.escape(phrase)}\b", " ", remaining)
    for phrase in sorted(attribute_index or (), key=len, reverse=True):
        remaining = re.sub(rf"\b{re.escape(str(phrase))}\b", " ", remaining)
    remaining = _QUERY_AND_STRUCTURE_PATTERN.sub(" ", remaining)
    remaining = " ".join(remaining.split())

    # A frame can precede an otherwise fully resolved catalog name, for example
    # ``Tell me about Manipal University Jaipur``. Recheck containment after
    # removing the frame words so ``manipal`` is not emitted as an unknown beside
    # the resolved full university span.
    remaining_tokens = set(remaining.split())
    if remaining_tokens and any(
        remaining_tokens.issubset(set(phrase.split())) for phrase in phrases
    ):
        return ""
    # Numeric remnants from preference phrasing (``budget of 1.8 lakh``) are
    # values, not absent catalog concepts.
    if remaining and all(token.isdigit() for token in remaining.split()):
        return ""
    return remaining


def _is_contained_token_span(value: str, other: str) -> bool:
    """Return whether ``value`` is a proper contiguous token span of ``other``."""

    tokens = tuple(value.split())
    other_tokens = tuple(other.split())
    if not tokens or len(tokens) >= len(other_tokens):
        return False
    return any(
        other_tokens[start : start + len(tokens)] == tokens
        for start in range(len(other_tokens) - len(tokens) + 1)
    )


def _comparison_clauses(message: str) -> tuple[str, str] | None:
    patterns = (
        r"\bcompare\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:[?.!]|$)",
        r"\bdifference\s+between\s+(.+?)\s+and\s+(.+?)(?:[?.!]|$)",
        r"\bwhich\b[^?]*?\bbetter\b\s*[,;:]?\s*(.+?)\s+or\s+(.+?)(?:[?.!]|$)",
        r"^\s*(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:[?.!]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
    return None


def _unknown_entities(
    message: str,
    *,
    universities: list[Any],
    courses: list[Any],
    specializations: list[Any],
    attribute_index: Any | None = None,
) -> list[str]:
    """Retain conservative catalog-looking spans after deterministic matching."""

    candidates = [*universities, *courses, *specializations]
    fragments: list[str] = []

    # Unknown qualifier immediately before, or specialization phrase after, any
    # resolved course concept. The rule is catalog-derived from matched spans;
    # it does not enumerate MBA/MCA/BBA/etc. in code.
    for course in courses:
        term = normalize_text(getattr(course, "matched_span", ""))
        if not term:
            continue
        course_pattern = re.escape(term).replace(r"\ ", r"\s+")
        before = re.search(
            rf"(?:^|\babout\s+)(.+?)\s+(?:online\s+)?{course_pattern}\b",
            message,
            re.IGNORECASE,
        )
        if before:
            fragments.append(before.group(1))
        after = re.search(
            rf"\b{course_pattern}\s+in\s+([a-z][a-z0-9&' -]*?)"
            r"(?=[?.!,;]|\b(?:what|which|who|how)\b|$)",
            message,
            re.IGNORECASE,
        )
        if after:
            fragments.append(after.group(1))

    # An explicit institution suffix is strong enough to retain a lowercase
    # unknown (``harward uni``) without treating arbitrary prose as an entity.
    institution = re.search(
        r"(?:^|\b(?:about|at|from)\s+)(.+?)\s+(?:online\s+)?"
        r"(?:university|uni|college|institute)\b",
        message,
        re.IGNORECASE,
    )
    if institution:
        fragments.append(institution.group(1))

    # Preserve an unknown side of a named comparison (Harvard vs LPU). Known
    # category/specialization/provider words are removed before deciding that a
    # clause contains a missing operand.
    comparison = _comparison_clauses(message)
    if comparison and candidates:
        fragments.extend(comparison)

    # Bare title/acronym input is useful catalog evidence. Inside a sentence,
    # require catalog evidence or an entity-bearing frame before considering
    # casing, which avoids treating ordinary capitalized prose as a university.
    has_entity_context = bool(candidates) or bool(
        _ENTITY_FRAME.search(message) or _OPEN_REASONING_ENTITY_FRAME.search(message)
    )
    bare_title = bool(_BARE_TITLE_OR_ACRONYM.fullmatch(message))
    if has_entity_context or bare_title:
        fragments.extend(match.group(0) for match in _TITLE_OR_ACRONYM.finditer(message))
    # Uppercase acronyms are catalog-looking even inside a neutral frame
    # (``What is BBA?``). Catalog-derived attributes such as NAAC/UGC are
    # removed by the attribute index during cleanup below.
    fragments.extend(match.group(0) for match in _ACRONYM.finditer(message))

    # A bare unmatched lowercase token cannot safely be corrected to an absent
    # catalog concept, but it must not disappear or reach an LLM for entity
    # recognition. Retain it locally unless it is query/greeting/reasoning
    # language or a catalog-derived attribute.
    normalized_message_tokens = normalize_text(message).split()
    if len(normalized_message_tokens) == 1:
        token = normalized_message_tokens[0]
        if (
            re.fullmatch(r"[a-z][a-z0-9]{2,}", token)
            and token not in _QUERY_AND_STRUCTURE_WORDS
            and token not in (attribute_index or {})
        ):
            fragments.append(token)

    unknown: list[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        value = _remove_known_phrases(fragment, candidates, attribute_index)
        if not value:
            continue
        # Long free-form remnants are more likely sentence prose than a missing
        # catalog name. Structured entity names in this catalog are short.
        if len(value.split()) > 6:
            continue
        normalized = normalize_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unknown.append(normalized)
    # Prefer the most informative span when multiple extraction frames overlap;
    # e.g. retain ``iit bombay`` and discard the contained acronym ``iit``.
    return [
        value
        for value in unknown
        if not any(_is_contained_token_span(value, other) for other in unknown if other != value)
    ]


def extract_mentions(message: str, matcher: Any) -> MentionResult:
    """Resolve all slot types independently and retain every candidate."""

    tokens = tokenize(message)
    indexes = getattr(matcher, "indexes", None)
    courses = _prefer_precise_catalog_families(
        _drop_query_language_fuzzy_matches(
            list(matcher.resolve_slot(tokens, "course"))
        ),
        indexes,
    )
    specializations = _prefer_precise_catalog_families(
        _drop_query_language_fuzzy_matches(
            list(matcher.resolve_slot(tokens, "specialization"))
        ),
        indexes,
    )
    high_category_spans = [
        (candidate.start, candidate.end)
        for candidate in courses
        if getattr(candidate, "confidence", None) == "HIGH"
    ]
    # Category scope wins only where its matched interval contains the specialization
    # interval. Disjoint evidence such as "MBA Marketing" must remain independently usable.
    specializations = [
        candidate
        for candidate in specializations
        if not any(
            start <= getattr(candidate, "start", 0) and getattr(candidate, "end", 0) <= end
            for start, end in high_category_spans
        )
    ]
    universities = _prefer_precise_catalog_families(
        _drop_query_language_fuzzy_matches(
            list(matcher.resolve_slot(tokens, "university"))
        ),
        indexes,
    )
    attribute_index = _attribute_index(matcher)
    attributes = _extract_attributes(message, attribute_index)
    unknown_entities = _unknown_entities(
        message,
        universities=universities,
        courses=courses,
        specializations=specializations,
        attribute_index=attribute_index,
    )
    return MentionResult(
        universities=universities,
        courses=courses,
        specializations=specializations,
        reference=detect_reference(message),
        tokens=tokens,
        unresolved_terms=[_display_unresolved(value) for value in unknown_entities],
        unknown_entities=unknown_entities,
        attributes=attributes,
    )
