# Handoff Report - Challenger 1 Verification (Milestone 3)

## 1. Observation

I verified the correctness of the chatbot implementation changes by writing and executing a new automated test suite. 

* **Verification Test File Path**: `/Users/aryankinha/Documents/Degree/CHAT BOT/chatbot/tests/test_challenger_verification.py`
* **Test Run Results**:
  * Running the new verification suite:
    ```bash
    .venv/bin/pytest tests/test_challenger_verification.py
    ```
    *Result*: `============================== 3 passed in 4.34s ===============================`
  * Running the entire test suite (including the new tests):
    ```bash
    .venv/bin/pytest
    ```
    *Result*: `======================= 394 passed, 1 warning in 24.04s ========================`

* **Verbatim Test Observations**:
  1. **Widget Parameter Tolerance**: 
     * Hitting `POST /chat?utm_source=widget&extra_param=123&another=xyz` with a valid payload succeeded with `200 OK`.
     * Hitting `POST /chat` with a payload containing extra body fields (`extra_param_1`, `extra_param_2`) succeeded with `200 OK`.
  2. **Advisory Classification**:
     * `"which is the best online mba program"` routed to `advisory` and returned:
       `"## Advisor profile\n\n### Current education\nWhat is your current or highest completed education?"`
     * `"tell me the best mba courses"` routed to `category` (MBA Programs overview).
     * `"are there any best specializations"` in a fresh session routed to `fallback` (with message: `"I couldn't confidently match that to the published catalog..."`).
     * `"are there any best specializations"` with a prior active focus on MBA routed to `category` (MBA Programs overview).
  3. **Lead Funnel Precedence**:
     * Sending `"Request Callback"` started the funnel and returned `"What name should our counsellor use?"`.
     * Sending a subsequent query `"what is the fee for LPU MBA?"` successfully exited the lead funnel, returned `'The published total fee for Online MBA is INR 1,34,000; the listed starting fee is INR 33,500 per semester.'`, and included suggested chips referencing Lovely Professional University (LPU).
     * The subsequent turn returned normal chat responses, verifying that the lead funnel was deactivated and not captured as the user's name.

---

## 2. Logic Chain

1. **Widget Parameter Tolerance**:
   * The `ChatRequest` schema in `chatbot/schemas.py` uses `model_config = ConfigDict(extra="ignore")`. This causes Pydantic to ignore any extra fields in the JSON body instead of raising validation errors. 
   * Query parameters (in the URL query string) are not defined in the FastAPI endpoint `chat_endpoint` function signature, so FastAPI ignores them automatically. 
   * As observed, both query parameters and extra body fields are accepted and the requests succeed, verifying widget parameter tolerance.

2. **Advisory Classification**:
   * `"which is the best online mba program"` matches `_PERSONAL_ADVISOR_RE` and `_RECOMMEND_MARKER` in `chatbot/advisor/flow.py` and `chatbot/nlu/action_classifier.py` due to the `"which is ... best"` pattern, routing successfully to the `advisory` flow.
   * `"tell me the best mba courses"` matches the high-confidence category "mba" but does not match `_RECOMMEND_MARKER` because "best" is not accompanied by "for me" or "which is". It therefore maps to `Action.GET_FACTS` and routes to `category`.
   * `"are there any best specializations"` contains no specific university or category catalog names, so in a fresh session, it resolves to `Action.UNRELATED` (fallback route). With an active "mba" focus in the session, it resolves as a `category` route.

3. **Lead Funnel Precedence**:
   * When `"what is the fee for LPU MBA?"` is sent during an active lead funnel name prompt, `_looks_like_product_turn` evaluates to `True` because it contains "?" and has explicit catalog mentions ("LPU", "MBA").
   * As a result, the code in `chatbot/main.py` deactivates the funnel (`self.lead_funnel.complete(state)`) and routes the query to the normal catalog handler (`factual`). The query is not saved as `state.lead.name` (which remains `None`), and the next user message is processed as normal chat.

---

## 3. Caveats

* **Redis connection**: Tests execute against process-memory session storage since a live Redis instance is not configured/running during the test execution.
* **CRM Webhook**: The CRM integration uses a mock webhook in unit tests, so real-time webhook pushing latency/failures are not tested.

---

## 4. Conclusion

The implemented changes are verified to be correct and robust. Widget parameter tolerance works for both URL query parameters and extra JSON payload properties. Advisory classification routes queries deterministically based on NLU patterns. Lead funnel precedence successfully exits active lead flows for catalog-related product queries, ensuring that product queries are not accidentally captured as contact details. No regressions were introduced.

---

## 5. Verification Method

To independently run the tests:
1. Navigate to `/Users/aryankinha/Documents/Degree/CHAT BOT/chatbot`.
2. Run:
   ```bash
   .venv/bin/pytest tests/test_challenger_verification.py
   ```
3. To run the full test suite including the new verification tests, run:
   ```bash
   .venv/bin/pytest
   ```
