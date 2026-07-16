# Guided Navigation Prototype

## Purpose and boundary

The prototype is an additive, catalog-driven admissions explorer. It does not replace or
rewrite the production widget. The existing embedded loader, conversational response payload,
NLU, resolver, router, session focus, and catalog models remain unchanged.

Two transports are deliberately kept separate:

```text
Guided click -> GuidedNavigator -> /api/widget/guide/* -> CatalogStore
Typed message -> ChatTransport -> /chat -> existing chatbot pipeline
```

Changing the simulated page creates a new chat session. That prevents focus from a previous
scenario from influencing a typed turn in the new scenario.

## What the prototype adds

- A standalone simulator at `/widget/prototype` with Homepage, University, Course, and
  Specialization scenarios.
- An in-memory page-context controller and a visible JSON context inspector.
- Catalog-backed university, program, and specialization pickers.
- Catalog-backed entity, fee, eligibility, career, syllabus, review, accreditation, and
  comparison views.
- A direct phone lead form that reuses the existing `/api/widget/lead` endpoint.
- Read-only presentation endpoints under `/api/widget/guide/*`.

The rich information views intentionally render an explicit unavailable state when the
publisher has not supplied a field. The bundled sample catalog, for example, does not contain
semester-wise syllabus data, rating breakdowns, testimonials, or recruiter lists. The
prototype does not invent those facts.

## Conversation sequencing

The interaction layer treats navigation and answers differently without introducing another
router or state machine:

- **Exploration:** bot prompt -> chips or picker -> next bot prompt. University and program
  choices update context but do not render entity cards.
- **Information:** an explicit fees, eligibility, career, reviews, syllabus, accreditation,
  comparison, or details request renders the existing answer card.
- **Resolved recommendation:** choosing a specialization produces a short bot introduction and
  then the existing specialization card.

The UX audit found five places where navigation previously looked like a catalog dashboard:

| Previous behavior | Current behavior |
| --- | --- |
| University page immediately rendered a university card | Bot acknowledges the university and asks what the visitor wants to know |
| Course page immediately rendered a course card | Bot acknowledges the course and presents its information actions |
| University picker selection rendered a university card | Bot states the catalog program count and presents program chips |
| Program/category selection rendered selectable course cards | Bot asks for a university through the existing searchable picker, then presents specialization chips |
| Help/choose-first prompts used card containers | Bot bubbles and chips handle those exploration steps |

Specialization, information, comparison, lead-confirmation, explicit details, and typed-chat
cards remain answer states. Counts and labels come from the existing guide payload; the bundled
NMIMS sample currently resolves to two programs and two MBA specializations.

The prototype also applies four deliberately small pacing rules:

- Guided responses show an accessible three-dot thinking indicator for a fixed 650 ms. Catalog
  requests begin immediately, so the delay is a pacing floor rather than added network latency.
- Exploration prompts show three choices and progressively disclose extras with `More`. Opening
  context shows four homepage actions or three page actions, with secondary actions behind
  `More`.
- Completed actions are tracked for the current simulated-page journey and removed from later
  follow-ups.
- Rendering a new primary answer collapses the previous primary card into a quiet disclosure.

These behaviors live only in the simulator controller. They do not add a workflow engine or
change the guide API, catalog projections, card data, or typed-chat transport.

## Local review

From the `chatbot` directory:

```bash
uv run uvicorn main:app --reload
```

Then open:

```text
http://127.0.0.1:8000/widget/prototype
```

Use the scenario panel to simulate these future page contexts:

| Scenario | Logical context | Resolved sample catalog page |
| --- | --- | --- |
| Homepage | `{"page_type":"homepage"}` | None |
| University | `{"page_type":"university","university":"nmims"}` | `nmims-online` |
| Course | `{"page_type":"course","university":"nmims","course":"mba"}` | `nmims-online-mba` |
| Specialization | `{"page_type":"specialization","university":"nmims","course":"mba","specialization":"business-analytics"}` | `nmims-mba-analytics` |

## Guide API

The guide endpoints are presentation-only projections over the current immutable
`CatalogStore`:

- `GET /api/widget/guide/context` resolves a simulated context or exact entity and returns its
  existing card projection, related catalog records, and grounded information sections.
- `GET /api/widget/guide/catalog/{kind}` supplies searchable university, program-category,
  concrete course-provider, and specialization picker data (`universities`, `programs`,
  `courses`, and `specializations`).
- `POST /api/widget/guide/compare` builds the existing catalog-grounded comparison component
  from two or three exact entity IDs.

None of these routes imports or invokes the chatbot's NLU, resolver, routing, or LLM layers.

## Production integration path

The production embed remains:

```html
<script
  src="https://ai.degreebaba.com/widget.js"
  data-site-key="degreebaba"
></script>
```

When the prototype is approved, the production loader can adopt the guided controller behind
the existing Shadow DOM boundary. At bootstrap it should derive a small context object from a
server-provided page descriptor or an exact URL-to-catalog mapping, rather than guessing from
free-form path text. For example:

```js
const pageContext = {
  page_type: "course",
  university: "nmims",
  course: "mba",
};
```

The loader can pass that object to `GuidedNavigator` while continuing to pass typed composer
submissions to the current `/chat` transport. The additive guide endpoints and response
projections can be reused unchanged. The simulator-only scenario panel and JSON inspector are
not included in that production embed.

Before rollout, map real canonical page URLs to exact catalog IDs or slugs on the server, add
cache headers appropriate to the catalog publication cadence, and gate the guided layer with a
tenant feature flag so the current widget can remain the rollback path.
