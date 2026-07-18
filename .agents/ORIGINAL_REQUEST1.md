# Original User Request

## Initial Request — 2026-07-14T13:02:36+05:30

# Teamwork Project Prompt

The goal of this project is to perform a detailed forensic audit of the DegreeBaba chatbot codebase, tracing the request lifecycle, auditing the lead funnel, action classifier, latency, response generation, advisory flow, and widget security, without implementing changes.

Working directory: /Users/aryankinha/Documents/Degree/CHAT BOT

## Requirements

### R1. Trace Request Lifecycle
Analyze the FastAPI request path from `POST /chat` to response delivery, identifying exact files, functions, and execution order.

### R2. Audit Lead Funnel
Identify where lead capture is invoked, determine if it intercepts messages before NLU, locate session field stores, and trace the "pending name captured before NLU" log.

### R3. Audit Action Classifier
Investigate the action classification logic, explaining why recommendation queries fall back to factual category lookups and identifying regex limitations.

### R4. Audit Latency, Response Generation, Advisory Flow, and Widget Security
Analyze the response latency, template structure, advisory flow reachability, and CORS/origin security models of the widget.

## Acceptance Criteria

### Audit Completion
- Detailed answers provided for all Phase 1–7 questions.
- Rankings of root causes by impact are provided.
- All findings are grounded in codebase files and execution paths without proposing speculative fixes.
