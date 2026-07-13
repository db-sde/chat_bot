# DegreeBaba Chatbot

DegreeBaba Chatbot is a FastAPI service that answers university, course, fee, eligibility,
and specialization questions from DegreeBaba's published JSON envelopes. Its resolver keeps
category-level questions category-level, preserves ambiguity instead of selecting the first
record, and tolerates partial catalog content. Contact details are collected only after an
explicit callback/counsellor request, while a separate guided advisor can build a catalog-backed
shortlist from a learner's education, experience, goal, budget, and specialization preference.

## Setup

Python and dependencies are managed only through [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync
cp .env.example .env
uv run uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation. Run checks with:

```bash
uv run pytest
uv run ruff check .
```

Do not create or activate a separate virtual environment. `uv` maintains the ignored
`.venv/` directory itself.

## API

`POST /chat` accepts:

```json
{"session_id": "optional-stable-id", "message": "What is the fee for NMIMS MBA?"}
```

It returns `text/event-stream`. Templated responses emit one `response` event immediately.
LLM-backed responses emit real `token` events as provider deltas arrive, followed by a
`response` event containing the canonical payload:

```json
{
  "text": "...",
  "suggested_chips": ["Eligibility", "EMI options"],
  "cta": null
}
```

Every event also includes the effective `session_id`; send it on later turns to retain focus.

- `GET /health` reports catalog/database, Redis, and LLM states separately.
- `GET /metrics` reports deterministic/Gemini routing rates, Gemini failures, and intent latency
  percentiles for the current process lifetime.
- `POST /admin/reindex` refreshes the configured catalog source and atomically replaces the
  taxonomy indexes. If `ADMIN_API_KEY` is set, send it as `Authorization: Bearer <key>`.

## Configuration

Copy `.env.example` to `.env`. Important settings are:

- `CATALOG_PATH`: JSON file containing either an array of envelopes, an `entities` array, or
  an object keyed by entity id. Each record can include `id`, `slug`, `category`,
  `specialization_name`, and `aliases` beside the flat publisher envelope.
- `CATALOG_URL`: HTTP endpoint returning the same JSON shapes. It takes precedence over the
  file path during startup and reindex. With neither setting, a representative local catalog
  is used so the service starts safely.
- `REDIS_URL` and `SESSION_TTL_SECONDS`: sliding session persistence. An unavailable Redis
  automatically degrades to in-process memory.
- `GEMINI_API_KEY`: optional tiny outcome classification for unresolved, open-ended messages.
  Recognized catalog entities and deterministic discovery/comparison requests stay on the local
  fast path.
- `GROQ_API_KEY`: optional grounded answer synthesis provider.
- `OPENAI_API_KEY`: optional grounded answer synthesis. Common factual answers remain
  deterministic and do not invoke an LLM.
- `CRM_WEBHOOK_URL` and `CRM_WEBHOOK_SECRET`: optional CRM destination. Each newly captured
  lead field schedules a background update, but collection starts only from an explicit
  callback/counsellor action. Exhausted retries are written to `DEAD_LETTER_PATH`.

See `.env.example` for model names, timeouts, circuit-breaker thresholds, and admin
authentication. Legacy lead-timing variables remain accepted for deployment compatibility but
do not initiate collection during ordinary catalog chat.

## Catalog contract

The loader accepts the DegreeBaba publisher's flat `university`, `course`, and
`specialization` envelopes. `_meta.page_type` selects the typed model. All content fields are
optional and nullable; formatted strings and publisher HTML are preserved. Only the data
layer reads catalog fields directly. Routing code uses `safe_get()` so a missing or null field
produces a graceful unavailable answer.

## Adding a curated alias

Automatic canonical, acronym, n-gram, and fuzzy indexes handle most terminology. Add an alias
only when it is stable and unambiguous:

1. Open `taxonomy/alias_tables.py`.
2. Add the lowercase phrase to the correct slot table, pointing to a canonical id/name used by
   the index (for example the established `"hr"` specialization override).
3. Add a resolver acceptance test proving that the alias cannot steal a valid lower-layer
   match.
4. Run `uv run pytest` and call `POST /admin/reindex` in the running service.

Curated aliases are layer 1 and always win, so broad or brand-colliding terms do not belong in
that table.
