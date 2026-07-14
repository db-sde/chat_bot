# Handoff Report: Codebase Investigation & Strategy Verification

This report documents the read-only investigation and verified implementation strategy for the four chatbot backend requirements.

---

## 1. Observation

### 1.1 Widget Strict Parameter Issue
- **File & Lines**: `chatbot/schemas.py:22-29`
- **Code Reference**:
  ```python
  class TransportModel(BaseModel):
      model_config = ConfigDict(extra="forbid")

  class ChatRequest(TransportModel):
      message: str = Field(min_length=1, max_length=4000)
      session_id: str | None = Field(default=None, min_length=1, max_length=200)
  ```
- **Context**: The `widget.js` script sends `site_key` and `page_university_slug` parameters in its chat API POST payload (lines 691-694 of `widget.js`):
  ```javascript
  const response = await fetch(`${apiBase}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, site_key: siteKey, message, page_university_slug: pageSlug })
  });
  ```
- **Error Behavior**: Because `ChatRequest` inherits from `TransportModel` which has `extra="forbid"`, any request containing `site_key` or `page_university_slug` throws a Pydantic 422 validation error.

### 1.2 Lead Funnel Message Interception
- **File & Lines**: `chatbot/main.py:373-458`
- **Code Reference**:
  - The NLU classification checks `preflight_action` and `preflight_heuristic` locally at lines 373-374:
    ```python
    preflight_action = classify_action(mentions, chat.message)
    preflight_heuristic = heuristic_intent(chat.message)
    ```
  - The lead funnel active check starts immediately after at line 379:
    ```python
    if self.lead_funnel.is_active(state):
        ...
        pending_answer = self.lead_funnel.inspect_pending_answer(state, chat.message)
    ```
  - Within `pending_answer` processing, the pipeline runs a simple check for product queries:
    ```python
    product_turn = _looks_like_product_turn(
        chat.message,
        mentions,
        action_hint=preflight_action,
        heuristic=preflight_heuristic,
    )
    ```
  - For name capture, the code explicitly overrides `product_turn` to `False` at lines 405-414:
    ```python
    if (
        pending_answer.field == "name"
        and pending_answer.valid
        and not mentions.has_explicit_mentions
        and not getattr(mentions, "attributes", ())
        and preflight_heuristic is Intent.FACTUAL
        and preflight_action in {None, Action.UNSUPPORTED_ENTITY}
        and "?" not in chat.message
    ):
        product_turn = False
    ```
- **Context**: If the user submits a recommendation query like *"which is the best online mba program"* while the name capture is active:
  - If "online mba" is not recognized as an explicit entity in the taxonomy, `mentions.has_explicit_mentions` is `False`.
  - The heuristic intent evaluates to `Intent.FACTUAL`, and `preflight_action` is `None`.
  - The query has no question mark `?`, so `product_turn` becomes `False`.
  - The lead funnel processes the turn as a name capture, saving the query as the user's name and moving to the phone capture stage, bypassing the normal NLU action pipeline.

### 1.3 Advisory Classification Regexes
We observed the following exact regex definitions in the codebase:
- **`_RECOMMEND_MARKER`** in `chatbot/nlu/action_classifier.py:43-52`:
  ```python
  _RECOMMEND_MARKER = re.compile(
      r"\b(?:best\b[^?]{0,80}\bfor\s+me|cheapest|lowest[-\s]+cost|top|"
      r"(?:under|below|within|up\s*to|upto)\s*"
      r"(?:a\s+budget\s+of\s*)?(?:₹\s*|rs\.?\s*|inr\s*)?\d|"
      r"recommend|suggest|help\s+me\s+choose|"
      r"career\s+(?:guidance|growth)|working\s+professional\s+(?:advice|guidance)|"
      r"which\b[^?]{0,80}\b(?:should\s+i|is\s+best|has\s+the\s+best)|"
      r"which\s+university\b[^?]{0,80}\b(?:highest|reasonable\s+fees?))\b",
      re.IGNORECASE,
  )
  ```
- **`_CATALOG_ADVISORY`** in `chatbot/nlu/intent.py:48-55`:
  ```python
  _CATALOG_ADVISORY = re.compile(
      r"\b(?:best\b[^?]{0,80}\bfor\s+me|"
      r"which\b[^?]{0,80}\b(?:should\s+i|is\s+best|has\s+the\s+best)|"
      r"which\s+university\b[^?]{0,80}\b(?:highest|reasonable\s+fees?)|"
      r"recommend|suggest|suit(?:s|able)?\s+(?:me|my)|help\s+me\s+choose|"
      r"career\s+(?:guidance|growth)|working\s+professional\s+(?:advice|guidance))\b",
      re.IGNORECASE,
  )
  ```
- **`_PERSONAL_ADVISOR_RE`** in `chatbot/advisor/flow.py:43-49`:
  ```python
  _PERSONAL_ADVISOR_RE = re.compile(
      r"\b(?:best\b[^?]{0,50}\bfor\s+me|which\b[^?]{0,50}\bis\s+best\b|"
      r"recommend(?:\s+me)?\s+(?:a\s+)?"
      r"(?:universit(?:y|ies)|programs?|courses?)|recommend\b[^?]{0,60}\bfor\s+me|"
      r"help\s+me\s+(?:choose|decide)|which\b[^?]{0,80}\bshould\s+i\s+choose)\b",
      re.IGNORECASE,
  )
  ```
- **Context**: The queries containing *"best"* require the presence of *"for me"* or direct adjacency to verbs/pronouns (e.g. `is best`). Thus, "which is the best online mba program" fails to match because of the intervening article "the" and the lack of "for me".

### 1.4 Redis Latency and Deployment Topology
- **File & Lines**: `chatbot/session/store.py:27-57`, `chatbot/config.py:58-61`
- **Code Reference**:
  - `redis_timeout_seconds` in `config.py` defaults to `1.0` seconds.
  - Connection options in `store.py` are:
    ```python
    self._redis = Redis.from_url(
        effective_url,
        decode_responses=True,
        socket_connect_timeout=self.timeout_seconds,
        socket_timeout=self.timeout_seconds,
    )
    ```
  - Fallback triggering logic in `store.py:76-83`:
    ```python
    def _fall_back(self, operation: str, error: Exception) -> None:
        if not self._redis_failed:
            logger.warning(
                "Redis %s failed; using process-memory session storage: %s",
                operation,
                error,
            )
        self._redis_failed = True
    ```
- **Context**: Any connection, read, write, or TTL refresh timeout/exception permanently sets `self._redis_failed = True`. Once set, the system degrades to in-process memory indefinitely without retry or recovery mechanisms.

---

## 2. Logic Chain

### 2.1 Widget Strict Parameter Issue
- **Observation**: `TransportModel` enforces `extra="forbid"`. `ChatRequest` inherits from `TransportModel`. `widget.js` transmits `site_key` and `page_university_slug`.
- **Reasoning**: To prevent validation errors while documenting these fields and remaining robust against any future frontend field additions:
  - We can override the model's configuration on the `ChatRequest` class level by setting `model_config = ConfigDict(extra="ignore")`.
  - To preserve the values of the known fields for future contextual grounding, we should explicitly list `site_key` and `page_university_slug` as optional fields.
- **Conclusion**: The best design strategy is a combination: declare `site_key: str | None = None` and `page_university_slug: str | None = None` explicitly inside `ChatRequest`, and add `model_config = ConfigDict(extra="ignore")` to prevent failures from other future frontend parameters.

### 2.2 Lead Funnel Message Interception
- **Observation**: The lead funnel active check intercepts incoming turns prior to executing full NLU classification. Under name capture, any message with 1-5 words and no "?" is classified as a valid name answer unless it contains catalog mentions or triggers `preflight_action` / `preflight_heuristic`.
- **Reasoning**: Cheap local preflight checks fail to resolve complex or implicit catalog queries (e.g. advisory questions like "which is the best online mba"). Only the main NLU classification (running deterministic rules, heuristic regexes, and Gemini `decide_action` at lines 553-645) can accurately detect them.
- **Conclusion**: The processing pipeline must be refactored to compute NLU action classification *prior* to evaluating the lead funnel. If the resolved action is categorized as a product query, the chatbot must immediately call `self.lead_funnel.complete(state)` and route to the product handlers. Otherwise, it should proceed to lead funnel processing.

### 2.3 Advisory Classification Regexes
- **Observation**: All three regexes fail on "which is the best online mba program" because:
  - `best` requires `for me` (e.g. `best\b[^?]{0,80}\bfor\s+me`).
  - `is best` requires direct adjacency (e.g. `is\s+best`).
- **Reasoning**:
  - Making "for me" optional or allowing "best" to stand alone when matching catalog queries allows it to match natural queries like "best online mba".
  - Allowing optional articles (e.g. `the`) and matching both plural and singular forms of "be" (e.g. `is` or `are`) permits matching "is the best" or "are the best".
- **Conclusion**: The patterns must be updated to be flexible, supporting `(?:the\s+)?best` and `(?:is|are)\s+(?:the\s+)?best`.

### 2.4 Redis Latency and Deployment Topology
- **Observation**: Any single failure sets `self._redis_failed = True` permanently. No retry policy is applied during client instantiation, and keepalive options are absent.
- **Reasoning**:
  - In a load-balanced, multi-server production environment, having an instance permanently fallback to in-process memory results in session inconsistency across pods/workers.
  - An aggressive 1.0s timeout with no retry policy can trigger false-positive fallbacks under normal network fluctuations or brief Redis latency spikes.
- **Conclusion**: We must configure TCP keepalives, a connection pool limit, and robust retry logic. More importantly, we should replace the permanent boolean flag with a temporary circuit-breaker fallback that periodically retries to establish a Redis connection.

---

## 3. Caveats

- **Taxonomy Matcher Accuracy**: When refactoring Task 2, we assume the NLU classifier can run effectively before lead funnel evaluation. If a query is extremely noisy, NLU might classify it as chitchat or unrelated, causing it to fall into the name capture. However, this is still better than the current behavior where all inputs of 1-5 words without "?" are unconditionally captured as names.
- **LLM Cost/Latency**: Moving the NLU classification step up means Gemini action classification (`decide_action`) may run before lead funnel checks on certain messages. This is mitigated since `should_use_reasoning_llm` guards the Gemini call, and direct names ("Aryan Kinha") do not match open reasoning regexes, keeping name captures local and fast.
- **No Redis Failures in Tests**: The existing test suite in `chatbot/tests/test_session_store.py` asserts that `store.using_memory` is `True` after failures. Modifying the sticky fallback behavior to allow recovery will require updating those specific assertions to match the new recovery lifecycle.

---

## 4. Conclusion

The codebase is highly structured but contains a few critical bugs and resilience issues:
1. **Schema Validation**: Fix the `ChatRequest` in `chatbot/schemas.py` by adding `site_key` and `page_university_slug` as optional fields and setting `model_config = ConfigDict(extra="ignore")`.
2. **Lead Funnel Pipeline**: Shift NLU Action Classification up in `process_turn` (before the `lead_funnel.is_active` block) to ensure product turns exit the funnel properly.
3. **Advisory Regexes**: Replace strict patterns in the three files with tolerant variations supporting articles (`the`) and optional structures.
4. **Redis Persistence**: Configure robust connection pools, TCP keepalive, tenacity-based retries, and replace the sticky memory fallback with a self-recovering circuit breaker.

---

## 5. Verification Method

### 5.1 Manual Verification Commands
Run the FastAPI application locally:
```bash
uv run uvicorn main:app --reload
```

- **Verify Schema Issue**:
  Send a POST request with extra parameters:
  ```bash
  curl -i -X POST http://127.0.0.1:8000/chat \
    -H "Content-Type: application/json" \
    -d '{"message": "What is the fee for LPU MBA?", "session_id": "test-session", "site_key": "custom_site", "page_university_slug": "lpu"}'
  ```
  *Validation condition*: Response must return `200 OK` (event stream) and NOT `422 Unprocessable Entity`.

- **Verify Lead Funnel and Regex Issues**:
  Initiate a lead capture flow (e.g. by requesting a callback), then send *"which is the best online mba program"*.
  *Validation condition*: The bot must exit the lead capture flow and execute the recommendation search route, rather than saving the query as the name of the user.

- **Verify Redis Recovery**:
  Simulate a temporary Redis outage by shutting down Redis or blocking the port, send a chat request (it should fall back to memory), restore Redis, and send another chat request.
  *Validation condition*: The subsequent request must successfully persist state back into Redis, proving that the fallback is not permanently sticky.

### 5.2 Unit Tests
Execute the project test suite using `pytest` to verify regression safety:
```bash
uv run pytest chatbot/tests/
```
