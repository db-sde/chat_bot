# BRIEFING — 2026-07-14T07:56:30Z

## Mission
Investigate the chatbot codebase for schemas, request pipeline, regexes, and Redis config, and write a handoff report.

## 🔒 My Identity
- Archetype: teamwork_preview_explorer
- Roles: explorer
- Working directory: /Users/aryankinha/Documents/Degree/CHAT BOT/.agents/explorer_m1
- Original parent: 94ac2d39-7725-4434-816c-ef85ed662392
- Milestone: Milestone 1 - Codebase Investigation & Strategy Verification

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Run no build/test commands yourself
- Read relevant files and verify all claims with evidence

## Current Parent
- Conversation ID: 94ac2d39-7725-4434-816c-ef85ed662392
- Updated: 2026-07-14T13:24:53+05:30

## Investigation State
- **Explored paths**: `chatbot/schemas.py`, `chatbot/main.py`, `chatbot/nlu/action_classifier.py`, `chatbot/nlu/intent.py`, `chatbot/advisor/flow.py`, `chatbot/session/store.py`, `chatbot/config.py`, `widget.js`, `chatbot/resilience/health.py`
- **Key findings**: 
  - `ChatRequest` schema forbids extra parameters because of inheritance from `TransportModel` (`extra="forbid"`). Adding optional parameters (`site_key`, `page_university_slug`) and setting `extra="ignore"` on `ChatRequest` resolves validation errors.
  - The Lead Funnel intercepts message turns early, relying on cheap preflight checks rather than full NLU action/intent classification, which causes catalog queries without explicit entities (e.g. "tell me the best online mba program") to be swallowed as name capture inputs.
  - Regex patterns `_RECOMMEND_MARKER`, `_CATALOG_ADVISORY`, and `_PERSONAL_ADVISOR_RE` require "for me" after "best" or "is best" verbatim, failing on common queries like "which is the best online mba program".
  - Redis session store has a sticky permanent fallback behavior: once any Redis call fails or times out (default 1.0s), the instance permanently falls back to local in-process memory, which breaks session state sharing across multiple application processes/containers.
- **Unexplored areas**: None. Complete coverage of the requested investigation.

## Key Decisions Made
- Recommended combining `extra="ignore"` and explicit optional parameters on `ChatRequest`.
- Recommended shifting the NLU action classification block above the lead funnel active check in `process_turn`.
- Formulated optimized regexes to handle articles and wider advisory variations.
- Outlined a resilience strategy for Redis connection pools and fallback states.

## Artifact Index
- /Users/aryankinha/Documents/Degree/CHAT BOT/.agents/explorer_m1/handoff.md — Handoff report of the codebase investigation.
