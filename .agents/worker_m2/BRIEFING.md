# BRIEFING — 2026-07-14T13:32:00+05:30

## Mission
Implement refactorings and fixes in the DegreeBaba chatbot codebase for widget parameter validation, advisory classification regexes, lead funnel message interception, and document Redis latency/deployment topology.

## 🔒 My Identity
- Archetype: preview_worker
- Roles: implementer, qa, specialist
- Working directory: /Users/aryankinha/Documents/Degree/CHAT BOT/.agents/worker_m2
- Original parent: 94ac2d39-7725-4434-816c-ef85ed662392
- Milestone: milestone_2

## 🔒 Key Constraints
- CODE_ONLY network mode: no external internet accesses, curl/wget to external endpoints is prohibited.
- Minimal change principle: only modify code paths directly related to the specified requirements.
- Match existing naming, style conventions.

## Current Parent
- Conversation ID: 94ac2d39-7725-4434-816c-ef85ed662392
- Updated: not yet

## Task Summary
- **What to build**: 
  1. Add optional fields `site_key` and `page_university_slug` to `ChatRequest` schema in `chatbot/schemas.py` and allow/ignore extra fields.
  2. Optimize regexes for `_RECOMMEND_MARKER`, `_CATALOG_ADVISORY`, and `_PERSONAL_ADVISOR_RE` to support optional "the" and "be" verbs.
  3. Refactor NLU classification execution to run before Lead Funnel interception in `process_turn`, setting `product_turn = True` for product actions.
  4. Create `REDIS_LATENCY.md` in repository root.
- **Success criteria**:
  - `pytest` passes successfully.
  - Manual curl tests succeed.
  - Handoff report written to `.agents/worker_m2/handoff.md`.
- **Interface contracts**: `chatbot/schemas.py`, `chatbot/main.py`.
- **Code layout**: Source in `chatbot/`.

## Change Tracker
- **Files modified**:
  - `chatbot/schemas.py`: Added optional fields and ConfigDict(extra="ignore").
  - `chatbot/nlu/action_classifier.py`: Updated `_RECOMMEND_MARKER` regex pattern.
  - `chatbot/nlu/intent.py`: Updated `_CATALOG_ADVISORY` regex pattern.
  - `chatbot/advisor/flow.py`: Updated `_PERSONAL_ADVISOR_RE` regex pattern.
  - `chatbot/main.py`: Refactored `process_turn` NLU order of execution and lead funnel interception logic.
  - `REDIS_LATENCY.md`: Added Redis parameters and deployment topology guide.
- **Build status**: Pass (391 tests passed successfully)
- **Pending issues**: None

## Quality Status
- **Build/test result**: Pass (391 tests passed, 1 warning)
- **Lint status**: 0 violations
- **Tests added/modified**: Verified against all regression test cases.

## Loaded Skills
- **Source**: None
- **Local copy**: None
- **Core methodology**: None

## Key Decisions Made
- Unconditionally applied the name override safeguard block in `process_turn` to protect name replies that look like unknown entities from being misclassified as product turns.
- Avoided recording action source telemetry early to prevent corrupting metrics during early returns (callbacks, lifecycle commands, clarifications).

## Artifact Index
- /Users/aryankinha/Documents/Degree/CHAT BOT/.agents/worker_m2/handoff.md — Handoff report
