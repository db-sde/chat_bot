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
{
  "session_id": "optional-stable-id",
  "message": "What is the fee for NMIMS MBA?",
  "site_key": "degreebaba",
  "page_type": "course",
  "page_entity_slug": "nmims-online-mba"
}
```

`site_key`, `page_type`, and `page_entity_slug` are optional context fields used by embedded
clients. The legacy `page_university_slug` field remains accepted. Exact page context seeds the
existing session focus only when that focus is empty; it never overrides a user-selected entity.

It returns `text/event-stream`. Templated responses emit one `response` event immediately.
LLM-backed responses emit real `token` events as provider deltas arrive, followed by a
`response` event containing the canonical payload:

```json
{
  "text": "...",
  "message": "...",
  "suggested_chips": ["Eligibility", "EMI options"],
  "cta": null,
  "quick_actions": [
    {"label": "Am I eligible?", "message": "NMIMS MCA eligibility", "action": "send_message"}
  ],
  "context": {
    "university": "NMIMS Global Access",
    "course": "MCA",
    "specialization": null,
    "entity_id": "course-nmims-mca",
    "label": "NMIMS Global Access · MCA"
  },
  "metadata": {"route": "factual", "page_type": "course", "entity_id": "course-nmims-mca"},
  "components": [
    {
      "type": "quick_actions",
      "actions": [
        {"label": "Eligibility", "message": "Eligibility", "action": "send_message"}
      ]
    }
  ]
}
```

Every event also includes the effective `session_id`; send it on later turns to retain focus.
Legacy `text`, `suggested_chips`, and `cta` remain available. New clients should render the
advisor-style `message`, `components`, `quick_actions`, and existing-focus `context` when present.

- `GET /health` reports catalog/database, Redis, and LLM states separately.
- `GET /metrics` reports deterministic/Gemini routing rates, Gemini failures, and intent latency
  percentiles for the current process lifetime.
- `POST /admin/reindex` refreshes the configured catalog source and atomically replaces the
  taxonomy indexes. If `ADMIN_API_KEY` is set, send it as `Authorization: Bearer <key>`.

## Widget 2.0

Embed the standalone widget on any allowed partner page:

```html
<script
  src="https://ai.degreebaba.com/widget.js"
  data-site-key="degreebaba"
></script>
```

The loader fetches tenant branding from `GET /api/widget/config/{site_key}`, creates an
isolated Shadow DOM UI, and uses the existing `/chat` SSE transport. It supports university,
program, specialization, stacked comparison, picker, guided-finder, detail, callback, and
quick-action states without adding dependencies to the host site. Add exact page context on
entity pages:

Widget JavaScript is edited only in `widget/src/`. Generate the production artifact with
`node widget/build.mjs`, or run `node widget/build.mjs --watch` during development. The backend
continues to serve the generated `widget/widget.js` at the public `/widget.js` URL.

```html
<script
  src="https://ai.degreebaba.com/widget.js"
  data-site-key="degreebaba"
  data-page-type="course"
  data-page-entity-slug="nmims-online-mba"
></script>
```

The experience layer uses these additive public endpoints:

- `GET /api/widget/page-context` resolves an exact page id, slug, or unique publisher alias.
- `GET /api/widget/catalog/{university|program|specialization}` supplies grounded picker data.
- `POST /api/widget/finder` applies the four deterministic catalog filters and returns at most
  three cheapest/middle/premium cards.
- `POST /api/widget/context/clear` calls the existing `Focus.clear()` for a session.
- `POST /api/widget/lead` validates one phone field and reuses the existing lead/CRM funnel.

For local review, run the API and open `http://127.0.0.1:8000/widget/demo.html`. Append
`?context=home`, `?context=course`, or `?context=specialization` to exercise other opening states. See
[`docs/WIDGET_2_ARCHITECTURE.md`](docs/WIDGET_2_ARCHITECTURE.md) for configuration, response
examples, CORS guidance, and the rollout plan.

The isolated guided-navigation simulator is available at
`http://127.0.0.1:8000/widget/prototype`. It uses read-only catalog guide endpoints for every
guided click while keeping typed messages on the existing `/chat` transport. See
[`docs/GUIDED_NAVIGATION_PROTOTYPE.md`](docs/GUIDED_NAVIGATION_PROTOTYPE.md) for its architecture,
catalog data constraints, scenario mappings, and production integration path.

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
- `WIDGET_CONFIG_PATH`: optional site-keyed Widget 2 configuration file. When blank, the
  bundled `widget/configs.json` is used.
- `WIDGET_ALLOWED_ORIGINS`: `*` for public local embeds or a comma-separated production
  origin allowlist.

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
