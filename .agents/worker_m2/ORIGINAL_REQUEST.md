## 2026-07-14T07:57:54Z

You are the teamwork_preview_worker.
Your task is to implement the refactorings and fixes in the DegreeBaba chatbot codebase based on the explorer's handoff report.

Here are the requirements to fulfill:

1. Widget strict parameter issue:
   - File: `chatbot/schemas.py`.
   - Modify the `ChatRequest` class (around lines 26-37) to explicitly declare two new optional fields:
     `site_key: str | None = Field(default=None)`
     `page_university_slug: str | None = Field(default=None)`
   - Also, override Pydantic's configuration inside `ChatRequest` to allow/ignore extra parameters. Add `model_config = ConfigDict(extra="ignore")` as a class variable in `ChatRequest`.

2. Optimize Advisory Classification Regexes:
   - File: `chatbot/nlu/action_classifier.py`.
     Update the `_RECOMMEND_MARKER` regex to:
     Allow optional articles like "the" before "best" (e.g. `(?:the\s+)?best`) and singular/plural be verbs (e.g. `(?:is|are)\s+(?:the\s+)?best`).
     Example change for `is\s+best` -> `(?:is|are)\s+(?:the\s+)?best`.
     Example change for `best\b[^?]{0,80}\bfor\s+me` -> `(?:the\s+)?best\b[^?]{0,80}\bfor\s+me`.
   - File: `chatbot/nlu/intent.py`.
     Update the `_CATALOG_ADVISORY` regex in the same way (supporting optional "the" before "best" and optional be verbs like "is" or "are" before "best").
   - File: `chatbot/advisor/flow.py`.
     Update the `_PERSONAL_ADVISOR_RE` regex in the same way.

3. Refactor Lead Funnel message interception:
   - File: `chatbot/main.py`.
     Refactor `process_turn` (around lines 343-552). Specifically:
     Move the entire NLU Action Classification logic block (currently around lines 594-653, which computes `action`, `used_gemini`, `gemini_needs_clarification`, `action_source`, `source_label`, `action_ms`) to run *above* the `if self.lead_funnel.is_active(state):` check.
     Define `is_product_action = action not in {Action.CHITCHAT, Action.UNRELATED, Action.CALLBACK, Action.OPEN_LEAD_FORM, Action.FALLBACK, None}`.
     Update the `product_turn` logic in `process_turn`. Specifically, if `action` is a product action (i.e. `is_product_action` is `True`), then `product_turn` must be set to `True`, which deactivates the lead funnel and routes the request to normal catalog handlers.
     Verify that the old NLU action classification block is not executed twice. Ensure the code behaves correctly when the lead funnel is active or not.

4. Redis Latency and deployment topology:
   - Create a file `/Users/aryankinha/Documents/Degree/CHAT BOT/REDIS_LATENCY.md` in the root of the repository documenting:
     - The Redis connection parameters and RTT latency findings (1.0s timeout settings).
     - Recommended deployment topology changes for high availability and consistency (such as not using permanently sticky memory fallbacks under load-balanced nodes, configuring TCP keepalives, tenacity retries, and using a temporary circuit breaker retry mechanism).

Verification:
- Run the unit tests using `pytest` (`uv run pytest chatbot/tests/`). Make sure they all pass.
- Run `uv run uvicorn main:app --reload` in the background (or write/run a script if needed) to verify the curl manual verification works:
  - Test Turn with "which is the best online mba program" successfully routes to advisory.
  - Sending a widget request with `site_key` and `page_university_slug` to `/chat` succeeds with 200 OK.
  - Document all commands run and their exact outcomes in your handoff report.

Your output must be a detailed handoff report saved to `/Users/aryankinha/Documents/Degree/CHAT BOT/.agents/worker_m2/handoff.md`.
