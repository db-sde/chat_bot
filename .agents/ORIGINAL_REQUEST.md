# Original User Request

## Initial Request — 2026-07-14T07:52:21Z

# Teamwork Project Prompt

The goal of this project is to implement refactorings and fixes in the DegreeBaba chatbot codebase based on the forensic audit findings.

Working directory: /Users/aryankinha/Documents/Degree/CHAT BOT/chatbot

## Requirements

### R1. Resolve Widget strict parameter issue
Modify `ChatRequest` schema to allow extra parameters (`site_key` and `page_university_slug`) without throwing Pydantic validation errors (422), either by explicitly adding them as optional fields or changing extra handling settings.

### R2. Refactor Lead Funnel message interception
Adjust the request processing pipeline so that the lead funnel does not intercept queries before NLU action classification runs. Catalog/product queries should take precedence over lead name capture.

### R3. Optimize Advisory Classification Regexes
Make the advisory regexes (`_RECOMMEND_MARKER`, `_CATALOG_ADVISORY`, `_PERSONAL_ADVISOR_RE`) more tolerant to natural language variations (e.g. allowing optional articles like "the" before "best").

### R4. Document Redis Latency and deployment topology
Document the latency findings and recommendations regarding Redis RTT in the project repository.

## Acceptance Criteria

### Verification
- Pytest suite runs successfully and passes.
- No regression on existing tests.
- A test turn with "which is the best online mba program" successfully routes to advisory.
- Sending a widget request to `/chat` with `site_key` and `page_university_slug` succeeds with 200 OK.
