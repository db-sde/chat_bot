# Project: DegreeBaba Chatbot Forensic Audit

## Architecture
The DegreeBaba Chatbot is a modular FastAPI application that processes chat requests, extracts entity mentions (universities, courses, specializations), resolves references and ambiguities, updates dialog state, and routes the request to specialized handlers (factual, category, advisory, leads, comparison, etc.). It uses an asynchronous pipeline.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Exploration & Analysis | Spawn 3 Explorer agents to independently trace request lifecycle, lead funnel, action classifier, latency/response, advisory flow, and widget security, outputting detailed analysis files. | None | IN_PROGRESS |
| 2 | Metrics & Execution | Spawn 1 Worker agent to run tests, collect latency metrics, and audit live/test execution profiles. | M1 | PLANNED |
| 3 | Independent Review | Spawn 2 Reviewer agents to cross-verify the explorer findings against the codebase for strict grounding and completeness. | M2 | PLANNED |
| 4 | Final Synthesis | Synthesize all findings and compile the final forensic audit report. | M3 | PLANNED |

## Interface Contracts
- Read-only analysis. No changes to interfaces or components.
