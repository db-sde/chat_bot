# DegreeBaba Chatbot — Catalog Sync Architecture (Dev Spec)

**For:** Aryan (endpoint side) **and** the WordPress developer (webhook side)
**Scope:** How edits to `university` / `course` / `specialization` in WordPress reach the chatbot catalog in near-real-time. WordPress remains the single source of truth; the bot syncs from it.

**Model:** Option C — **webhook on post save** (primary), with an **optional nightly full reindex** (backstop). WordPress pushes each change the instant it's saved; the nightly job catches anything a webhook dropped.

**The contract between the two developers is §3 (the payload).** Aryan defines the endpoint; the WordPress developer builds the webhook to send exactly this shape.

```
WordPress (edit saved)
   │  acf/save_post hook, after ACF writes fields
   ▼
POST https://chat-bot-id1n.onrender.com/api/catalog/sync   (auth header, JSON body = §3)
   ▼
Chatbot endpoint → validate auth → upsert/delete by post_id → normalisation pass → catalog store
                                                                     │
Nightly cron (optional backstop) ──── full rebuild from WordPress ───┘
```

---

## 1. Division of ownership

| Piece | Owner |
|---|---|
| `/api/catalog/sync` endpoint (auth, upsert, delete, normalisation) | **Aryan** |
| Auth secret (generation + storage) | **Aryan** issues, WordPress dev stores |
| `acf/save_post` webhook + payload assembly | **WordPress developer** |
| Nightly reindex job (if used) | **Aryan**, needs a read-all-with-ACF route from **WordPress developer** |

**Sequence:** Aryan finalises §2–§4 first → Swanand relays the endpoint URL, payload shape (§3), and auth header to the WordPress developer → WordPress dev builds §5 → test together (§7).

---

## 2. Endpoint contract (Aryan)

```
POST /api/catalog/sync
Content-Type: application/json
X-Webhook-Secret: <shared secret>       # rejected with 401 if missing/wrong
Body: single entity payload (§3)
```

- **Response:** `200` on successful upsert/delete; `401` on bad auth; `400` on malformed payload; `422` if the payload is valid JSON but missing required keys (`post_id`, `post_type`, `status`). Non-2xx signals the WordPress side to retry (§5.5).
- **Idempotent upsert:** key on `post_id`. Re-sending the same payload produces an identical result — upsert, never append. A double-fire is harmless.
- **Delete handling:** if `status` is `trash`, `draft`, or `pending` (i.e. not `publish`), **remove** that entity from the catalog rather than storing it. Otherwise the bot keeps recommending an unpublished page. A subsequent re-publish re-adds it via a normal upsert.
- **Authentication:** validate `X-Webhook-Secret` against the stored secret before doing anything else. `/api/catalog/sync` is a public Render URL that mutates the catalog — no auth means anyone can corrupt it.
- **Relationship integrity:** on upsert of a `course` or `specialization`, resolve `linked_university` / `linked_course` to catalog ids. If a linked parent isn't in the catalog yet (e.g. a spec synced before its course), store the entity but flag the dangling link and resolve it on the next sync or nightly reindex rather than rejecting.

---

## 3. Payload shape (THE CONTRACT — both developers build to this)

One entity per POST. The WordPress webhook assembles this; the endpoint consumes it. Field names match the ACF doc exactly.

```json
{
  "post_id": 1234,
  "post_type": "course",                       // university | course | specialization
  "status": "publish",                         // publish | trash | draft | pending
  "slug": "nmims-online-mba",
  "permalink": "/online-mba/nmims-online-mba",
  "modified": "2026-07-26T10:14:00Z",

  "taxonomies": {
    "program":       ["online-mba"],
    "discipline":    ["marketing"],
    "approval_body": ["ugc", "naac", "ugc-deb"],
    "mode":          ["online"],
    "institution":   ["nmims"]
  },

  "acf": {
    "program_name": "NMIMS Online MBA",
    "university_name": "NMIMS Global",
    "linked_university": 1180,                  // post_id of the related university
    "duration": "24 Months",
    "mode": "Online",
    "naac_grade": "A+",
    "ugc_status": "UGC Entitled",
    "total_fee": "₹1,71,000",
    "starting_fee": "₹1,71,000",
    "num_specializations": "9",
    "emi_amount": "₹4,750/month",
    "validity": "…",
    "eligibility_summary": "…",
    "certificate_description": "…",

    "fee_plans": [
      { "plan_name": "Semester", "plan_amount": "₹42,750", "plan_total": "₹1,71,000" }
    ],
    "job_profiles": [
      { "job_title": "Marketing Manager", "avg_salary": "₹8 LPA" }
    ],
    "faqs": [
      { "question": "Is NMIMS UGC approved?", "answer": "…" }
    ],
    "highlights": [ { "highlight_title": "…", "highlight_description": "…" } ],
    "reviews": [ { "review_text": "…", "reviewer_name": "…", "reviewer_label": "…" } ]
  }
}
```

**Rules for the payload:**
- **Send the FULL ACF set for the post type**, including all repeaters — not a subset. The bot's chips/cards/tools depend on the complete field set (fees, careers, FAQs, reviews, etc.). Send the same structure the micro-app already produces.
- **`linked_university` / `linked_course` as post IDs**, not names — the relationship is canonical; names drift.
- **Taxonomy terms as slugs**, matching the seeded slugs (`online-mba`, `marketing`, `ugc-deb`, …). The bot's filters key on these.
- Fields absent for a post type are simply omitted (a `university` payload has no `linked_course`, etc.).

---

## 4. Normalisation on arrival (Aryan)

The normalisation pass runs **on the bot side, after the payload lands**, before writing to the store — never in WordPress. Parses the text fields into numeric shadows (`fee_numeric`, `duration_months`, `naac_score`, `emi_numeric`, plus per-row `salary_numeric`, `plan_amount_numeric`). Fail-to-null + `unparsed_values` review table exactly as the ingestion spec defines. This keeps the bot's numeric truth independent of how the data arrived.

---

## 5. Webhook (WordPress developer)

### 5.1 Hook and scope
Fire on **`acf/save_post`**, scoped to post types `university`, `course`, `specialization` only. Ignore all other post types.

### 5.2 Timing — critical
Use `acf/save_post` **at a priority that runs AFTER ACF writes its fields** (priority > 10, e.g. 20). A plain `save_post` hook, or an early priority, captures the **previous** field values and the bot ends up one edit behind. This is the single most common failure in these integrations — please confirm the hook fires post-ACF-write.

### 5.3 Payload assembly
Assemble the full §3 payload for the saved post: post meta (id, type, status, slug, permalink, modified), all taxonomy terms as slugs, and the complete ACF field set including repeaters. Match §3 field names exactly.

### 5.4 Send
`POST` to the sync URL with the `X-Webhook-Secret` header. JSON body = §3.

### 5.5 Status changes and retries
- Fire on **trash / unpublish / status change too** (not only publish/update), sending the new `status`, so the bot can remove unpublished entities.
- On a non-2xx response, **retry once or twice** with a short backoff before giving up. If retries aren't feasible, the nightly reindex (§6) is the safety net — but retries are cheap and worth doing.

### 5.6 Bulk edits
A micro-app bulk import can fire many webhooks at once. The endpoint is idempotent so correctness is fine; if volume is a concern, debounce or queue on the WordPress side. Confirm expected burst size with Aryan.

---

## 6. Nightly reindex — optional backstop (recommended)

**Why:** webhooks can silently fail (Render down, timeout, mid-deploy). Without a backstop, a dropped webhook leaves one entity stale indefinitely, with no signal. For a bot that quotes fees and commits to real ₹5–10k waivers, a silently stale entity is a trust/commercial risk, not a cosmetic lag.

**What:** a nightly cron (Aryan) does a **full** rebuild — read every `university` / `course` / `specialization` with ACF, run normalisation, replace the store. Anything a webhook missed during the day is corrected. Guarantees the bot is never more than 24h from WordPress even if webhooks misbehave.

**WordPress-side requirement:** a way to **read all posts of these types with their ACF fields** — a custom REST route returning the §3 shape in a paginated list, or ACF-to-REST on the existing endpoints. Same "full ACF payload" requirement as the webhook, in readable-list form.

**If skipped:** everything still works via webhooks alone — you're betting no webhook ever silently fails over months of editing 800 pages. Not a bet I'd recommend on a money-claims bot, but it's a valid choice; drop this section if so.

**Manual `/reindex`** stays available regardless — for forcing an immediate full refresh (e.g. after a micro-app bulk import).

---

## 7. Testing (both, together)

1. Shared secret in place on both sides.
2. Edit one course's fee in WordPress → save → confirm the payload lands, normalises (`fee_numeric` correct), and the bot reflects it within seconds.
3. Confirm the hook sends **new** values, not previous (edit a field, verify the synced value matches the edit — this catches the §5.2 timing bug).
4. Trash the post → confirm the bot removes it. Re-publish → confirm it returns.
5. Send a request with a wrong/missing secret → confirm `401`.
6. Fire the same edit twice → confirm identical result (idempotency).
7. If using the backstop: run the nightly job manually once → confirm a deliberately-desynced entity self-corrects.

---

## 8. Analytics / ops

- Log every sync (`post_id`, `post_type`, action `upsert|delete`, parse result) so a missed or malformed sync is visible.
- Surface `unparsed_values` growth after syncs — a spike means a new fee/duration format the parser doesn't handle.
- Optionally emit a `catalog_sync_failed` event (non-2xx after retries) so drops are noticed rather than silent — this is what makes webhook-only mode less risky if you skip the nightly job.
