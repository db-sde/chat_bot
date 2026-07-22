# DegreeBaba Guided Admissions Widget

DegreeBaba is a catalog-grounded, chips-only admissions experience. Page context
selects an opening chip set; each chip invokes a deterministic catalog surface,
picker, comparison, conversion form, or guided tool flow.

## Runtime flow

```text
Page context
  → Journey Engine opening chips
  → chip selection
  → catalog card / picker / tool / lead flow
  → Chip Engine follow-up chips
```

The browser widget does not expose a free-text composer. The server does not run
intent classification, entity extraction, fuzzy text resolution, narrative
generation, or a conversational routing pipeline.

## Run locally

```bash
uv sync
uv run uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/` for the simulator.

## Public widget integration

```html
<script
  src="https://your-host.example/widget.js"
  data-site-key="degreebaba"
  data-page-type="course"
  data-page-entity-slug="course-nmims-mca"
></script>
```

The customer-facing script URL remains `/widget.js`. The production bundle is
generated from `widget/src/`:

```bash
node widget/build.mjs
node widget/build.mjs --watch
```

## Guided API

- `GET /api/widget/guide/context` — catalog context, opening chips, and resumable tool state.
- `POST /api/widget/guide/chips` — persisted funnel progression and follow-up chips.
- `GET /api/widget/guide/catalog/{kind}` — searchable catalog pickers.
- `POST /api/widget/guide/compare` — exact-ID catalog comparison.
- `POST /api/widget/guide/tool` — validated ActiveFlow tool tokens only.
- `POST /api/widget/lead` — lead capture and gated tool reveal.
- `POST /api/widget/context/clear` — clear page context or an active tool.
- `POST /api/widget/analytics` — non-blocking widget analytics.

## Configuration

Copy `.env.example` to `.env`. The principal settings are:

- `CATALOG_PATH` or `CATALOG_URL`
- `REDIS_URL` and `SESSION_TTL_SECONDS`
- `WIDGET_CONFIG_PATH`
- `CHIP_MAP_PATH`
- `TOOLS_CONTENT_PATH`
- `WIDGET_ALLOWED_ORIGINS`
- CRM and analytics webhook settings

No model-provider credentials are required or consumed.

## Verification

```bash
uv run pytest -q
```
