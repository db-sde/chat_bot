# Guided Navigation — Production Widget 2.0

## Status

The validated guided-navigation experience now lives in the production embed:

```html
<script
  src="https://ai.degreebaba.com/widget.js"
  data-site-key="degreebaba"
></script>
```

`widget/prototype/*` remains available only as a historical UX reference. It is not loaded by
the production widget, the real-widget demo, or the application root, and future UX work should
target `widget/widget.js` and `widget/widget.css`.

## Migration plan and result

The production widget adopts the proven UX decisions without copying the simulator controller:

- page-aware opening actions for homepage, university, course, and specialization pages;
- a sticky university/course/specialization context chip with a non-destructive clear action;
- catalog-driven university → program → specialization navigation using questions and chips;
- searchable catalog pickers presented as bottom sheets;
- information cards for fees, eligibility, careers, syllabus, reviews, accreditations, and
  comparisons;
- a specialization card only when a specialization is resolved;
- a 650 ms guided-response pacing floor using the existing typing indicator;
- three visible follow-up actions with paged `More` overflow;
- per-journey viewed-action filtering;
- semantic accordion behavior that keeps only one guided information card expanded;
- the existing phone-only human counsellor flow.

The simulator scenario selector was migrated to `widget/demo.html`, which reloads the real
production widget with exact runtime page data.

## Widget 2.0 architecture

The widget keeps two explicit transports:

```text
Guided click
  -> production widget navigation helpers
  -> /api/widget/guide/context | catalog | compare
  -> existing CatalogStore projections

Typed message
  -> production composer
  -> /chat
  -> existing NLU -> resolver -> router -> response pipeline
```

Inside the existing Shadow DOM widget, `widget.js` now owns:

```text
Widget 2.0
├── Runtime page context
├── Guided navigation state
├── Sticky context chip
├── Catalog pickers
├── Guided questions and follow-up chips
├── Information and comparison cards
├── Existing finder and lead panels
├── Typed composer
└── Existing SSE chat transport
```

There is no second router, workflow engine, NLU path, or client-side catalog schema.

## Reused unchanged

- `/chat`, its SSE response handling, and session IDs;
- NLU, resolver, routing, and response payload contracts;
- immutable catalog entities and the existing guide projections;
- `/api/widget/lead` and its phone-only contract;
- `/api/widget/context/clear`;
- production Shadow DOM lifecycle, configuration, card primitives, finder, and overlays.

Guided entity changes also become the active page context for the next typed message. Clearing
the context removes that navigation focus without deleting rendered typed-chat history.

## Navigation and answer rules

Exploration and answers remain distinct:

- Selecting a university asks which program interests the visitor; it does not render a
  university card.
- Selecting a program asks which specialization interests the visitor; it does not render a
  course card.
- Selecting a specialization renders the grounded specialization card.
- Fees, eligibility, career, syllabus, reviews, accreditations, and comparison render cards only
  when explicitly requested.
- Missing publisher data uses admissions-friendly unavailable copy and is never invented.
- Each guided response offers at most three substantive follow-ups; `More` pages overflow without
  exposing a dense action wall.

## Real-widget scenario demo

Run from the `chatbot` directory:

```bash
uv run uvicorn main:app --reload
```

Then open:

```text
http://127.0.0.1:8000/
```

or:

```text
http://127.0.0.1:8000/widget/demo.html
```

The visible scenario selector reloads `widget.js` with these exact embed contexts:

| Scenario | Runtime dataset |
| --- | --- |
| Homepage | `pageType=homepage` |
| University | `pageType=university`, `pageUniversitySlug=nmims`, `pageEntitySlug=nmims-online` |
| Course | `pageType=course`, `pageUniversitySlug=nmims`, `pageEntitySlug=nmims-online-mba` |
| Specialization | `pageType=specialization`, `pageUniversitySlug=nmims`, `pageEntitySlug=nmims-mba-analytics` |

Every scenario uses the real guide APIs, lead API, session handling, and `/chat`; no prototype
asset is involved.

## Production URL integration

Real pages should continue supplying exact catalog-backed descriptors on the embed script or
document dataset:

```html
<script
  src="https://ai.degreebaba.com/widget.js"
  data-site-key="degreebaba"
  data-page-type="course"
  data-page-university-slug="nmims"
  data-page-entity-slug="nmims-online-mba"
></script>
```

The server-side page or canonical URL mapping should provide the exact entity slug. The widget
does not guess academic entities from arbitrary URL text.

## Reference prototype

The isolated reference remains available at `/widget/prototype/` for historical comparison.
It should not receive further product work and can be removed later once the production rollout
no longer needs a visual reference.
