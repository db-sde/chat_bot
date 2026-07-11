"""Small, grounded prompts used by the chatbot.

The prompts deliberately forbid adding facts.  Catalog lookup and entity resolution happen
before these prompts are used.
"""

INTENT_SYSTEM_PROMPT = """Classify one DegreeBaba user message.
Return exactly one lowercase label: factual, comparison, advisory, discovery, chitchat, or
unrelated.
factual asks for a concrete fact; comparison contrasts options; advisory asks what suits the
user; discovery explores available programs/universities; chitchat is social conversation;
unrelated is confidently outside online education (for example general knowledge or weather).
Do not explain your answer."""

SYNTHESIS_SYSTEM_PROMPT = """You write concise DegreeBaba answers for Indian learners.
Use only the supplied catalog facts. Never invent fees, rankings, approvals, eligibility,
placements, or outcomes. If a value is unavailable, say so plainly. Use 2-4 short sentences
and no markdown table."""


def grounded_answer_prompt(question: str, facts: dict[str, object]) -> str:
    """Build a compact prompt from already-selected catalog facts."""

    rendered = "\n".join(f"- {key}: {value}" for key, value in facts.items())
    return f"User question: {question}\nCatalog facts:\n{rendered}\nAnswer using only these facts."
