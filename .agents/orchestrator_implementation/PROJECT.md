# Project: DegreeBaba Chatbot Refactoring and Fixes

## Architecture
The DegreeBaba Chatbot is a modular FastAPI application that processes chat requests, extracts entity mentions (universities, courses, specializations), resolves references and ambiguities, updates dialog state, and routes the request to specialized handlers (factual, category, advisory, leads, comparison, etc.).

This project implements refactorings and fixes based on forensic audit findings to:
1. Allow extra parameters in `ChatRequest` schema (`site_key` and `page_university_slug`) without Pydantic validation errors.
2. Adjust request processing pipeline in `main.py` so that the lead funnel does not intercept queries before NLU action classification runs.
3. Optimize advisory classification regexes in `action_classifier.py`, `intent.py`, and `flow.py` to be tolerant to variations like "the best".
4. Document Redis Latency and deployment topology recommendations in the repository.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Codebase Exploration & Fix Strategy | Spawn teamwork_preview_explorer to investigate schemas, NLU classifier, lead funnel, and compile a strategy report. | None | DONE |
| 2 | Implementation of Schema & NLU Fixes | Spawn teamwork_preview_worker to apply changes for ChatRequest schema, lead funnel precedence, and advisory regexes. | M1 | DONE |
| 3 | Verification & Testing | Spawn teamwork_preview_reviewer and teamwork_preview_challenger to verify correct behavior and test suite passes. | M2 | DONE |
| 4 | Documentation & Final Audit | Compile Redis Latency and deployment topology document and run Forensic Auditor check. | M3 | DONE |

## Interface Contracts
- `ChatRequest` schema must allow extra parameters (`site_key`, `page_university_slug`) without validation errors.
- ChatbotService `process_turn` must run NLU action classification before the lead funnel intercepts queries.
