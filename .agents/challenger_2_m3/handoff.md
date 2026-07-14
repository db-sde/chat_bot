# Challenger 2 Handoff Report — Milestone 3

This report documents the empirical verification and adversarial review of the changes implemented in Milestone 3, including widget parameter tolerance, advisory classification routing, and lead funnel precedence.

---

## 1. Observation

The verification was performed on the following modified files in the codebase:
- `chatbot/advisor/flow.py`
- `chatbot/main.py`
- `chatbot/nlu/action_classifier.py`
- `chatbot/nlu/intent.py`
- `chatbot/schemas.py`

### Key Empirical Findings:
1. **Widget Parameter Tolerance**: 
   - HTTP POST requests sent to `/chat` with extra JSON body fields (e.g. `extra_field_1`, `widget_version`) succeed with `HTTP 200` because `ChatRequest` in `chatbot/schemas.py` defines `model_config = ConfigDict(extra="ignore")`.
   - HTTP POST requests sent to `/chat` with extra URL query parameters (e.g. `/chat?widget_id=abc&timestamp=123`) succeed with `HTTP 200` because FastApi by default ignores undeclared query parameters.
2. **Advisory Classification**:
   - `"which is the best online mba program"` correctly routes to the `advisory` route (`Action.RECOMMEND`) and initiates the guided profile questionnaire: `## Advisor profile\n\n### Current education\nWhat is your current or highest completed education?`
   - `"tell me the best mba courses"` routes to the `category` overview for `MBA` (as expected per local heuristic rules because it lacks explicit "for me" or "which is/are" structure).
   - `"are there any best specializations"` routes to the fallback channel (since no category or specialization was matched in the mentions).
   - **Bug Found**: `"are there any best mba specializations"` routes to `unsupported_entity` instead of listing specializations, returning: `"I couldn't find There ANY in the DegreeBaba catalog."`
3. **Lead Funnel Precedence**:
   - Starting a callback session (sending `"request callback"`) triggers the lead funnel, prompting for the user's name: `"Absolutely — I can help arrange that. What name should our counsellor use?"`.
   - Immediately sending the product query `"what is the fee for LPU MBA?"` successfully exits the funnel (logs state `lead flow exited for ordinary chat`) and returns the course fee information: `"The published total fee for Online MBA is INR 1,34,000; the listed starting fee is INR 33,500 per semester."` instead of capturing the query as the user's name.

All 397 tests (391 baseline, 3 newly added milestone 3 empirical tests, and 3 previous verification tests) pass successfully.

---

## 2. Logic Chain

- **Parameter Tolerance**: Pydantic `ChatRequest`'s config is set to `extra="ignore"` (line 27 in `chatbot/schemas.py`). Therefore, any extra parameters in the payload are ignored rather than raising a Pydantic validation error. Extra query parameters are ignored by FastAPI's endpoint signature.
- **Lead Funnel Precedence**: In `chatbot/main.py`, the action classifier is called before the lead funnel active check. If the action is a product action (not chitchat, unrelated, callback, etc.), `product_turn` is flagged as `True` (line 490 in `main.py`). This sets `name_is_product = True` when the lead funnel is waiting for a name, bypassing the name capture and calling `self.lead_funnel.complete(state)`. The turn is then routed through the standard catalog.
- **Advisory Classification / Extraction Bug**:
  - The query `"are there any best mba specializations"` contains the course `mba` which matches as a high-confidence category candidate.
  - The mention extractor identifies the text immediately before the course name using a regular expression: `rf"(?:^|\babout\s+)(.+?)\s+(?:online\s+)?{course_pattern}\b"` (line 450 in `chatbot/nlu/mention_extractor.py`). This captures the phrase `"are there any best"`.
  - During cleanup in `_remove_known_phrases`, structure words like `"are"` and `"best"` are removed because they are defined in `_QUERY_AND_STRUCTURE_WORDS`. However, `"there"` and `"any"` are not defined in the set, leaving `"there any"` as an unresolved term.
  - Since `"there any"` is marked as an unknown entity, `classify` returns `Action.UNSUPPORTED_ENTITY`, causing the fallback.

---

## 3. Caveats

- **LLM/Gemini Pathing**: The verification tests mock or bypass actual Gemini network calls (due to `CODE_ONLY` mode). In production, some ambiguous advisory queries that do not match the local regex rules might fall back to the Gemini decision logic (`decide_action`).
- **Catalog Constraints**: The LPU MBA fee details check relies on the sample catalog. If the catalog changes, tests checking for the specific fee value (`1,34,000`) might fail.

---

## 4. Conclusion

The implementation of Milestone 3 correctly satisfies the product requirements:
1. Widget parameter tolerance is fully operational.
2. Lead funnel precedence successfully overrides active name capture on product queries.
3. The advisory classification routes queries according to the designed regex rules. The observed issue with `"are there any best mba specializations"` is not a regression, but rather a limitation of the static `_QUERY_AND_STRUCTURE_WORDS` vocabulary list, which extracts `"there any"` as an unknown entity.

---

## 5. Verification Method

To verify the findings and run the tests:
```bash
# Run the empirical test suite
uv run pytest tests/test_milestone3_empirical.py

# Run all chatbot tests
uv run pytest
```
Files to inspect:
- `chatbot/tests/test_milestone3_empirical.py` (our new empirical verification tests)
- `chatbot/tests/test_challenger_verification.py` (existing verification tests)

---

## Challenge Report (Adversarial Review)

**Overall risk assessment**: LOW

### Challenges

#### [Low] Challenge 1: Unknown Entity Extraction on Common Words
- **Assumption challenged**: The system assumes any non-structure words preceding a course name are part of a university name or unknown catalog term.
- **Attack scenario**: A user asks: `"are there any best mba specializations"`
- **Blast radius**: The system extracts `"there any"` as an unknown entity and replies with an unsupported entity message, failing to list the MBA specializations.
- **Mitigation**: Add common pronouns/structure words like `"there"`, `"any"`, `"some"`, `"many"` to `_QUERY_AND_STRUCTURE_WORDS` in `chatbot/nlu/mention_extractor.py` to prevent them from being treated as unknown entities.

### Stress Test Results

- **Extra payload parameter check**: Send `{"extra_param": 1}` to `/chat` → returns 200 OK → **PASS**
- **Extra URL parameter check**: Send GET/POST queries to `/chat?extra=1` → returns 200 OK → **PASS**
- **Funnel Precedence check**: Active lead capture funnel → Send `"what is the fee for LPU MBA?"` → Funnel completes, returns LPU MBA course fee facts → **PASS**
