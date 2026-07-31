# WordPress Catalog Sync Guide

This guide explains how WordPress should send university, course, and specialization changes to the DegreeBaba catalog sync endpoint.

It is written for the WordPress implementation. You do not need to know the widget code to use this integration.

## 1. Overview

The sync endpoint receives the current WordPress/ACF data for one catalog page and makes that page available in DegreeBaba.

Use it whenever an editor changes a supported catalog post. This keeps information such as fees, eligibility, accreditations, reviews, program relationships, and FAQs aligned with the published WordPress content.

Supported catalog entity types are:

| WordPress payload `post_type` | Catalog entity |
| --- | --- |
| `university` | University |
| `course` or `program` | Course / program |
| `specialization` or `specialisation` | Specialization |

Plural forms (`universities`, `courses`, `specializations`) are also accepted for compatibility. Use the singular names above for new work.

## 2. Architecture

```text
Editor clicks Save / Publish
        |
        v
WordPress saves ACF fields
        |
        v
acf/save_post (priority after ACF has saved)
        |
        v
Build the complete JSON payload for one post
        |
        v
POST /api/catalog/sync
        |
        v
Payload and secret are validated
        |
        v
Published entity is created or updated
or unpublished entity is removed
        |
        v
The updated catalog is immediately available from this running service
```

## 3. Endpoint

| Item | Value |
| --- | --- |
| Method | `POST` |
| URL | `https://chat-bot-id1n.onrender.com/api/catalog/sync` |
| Content type | `application/json` |
| Authentication | `X-Webhook-Secret` request header |
| Request unit | Exactly one WordPress entity per request |

### Minimal publish request

```http
POST /api/catalog/sync HTTP/1.1
Content-Type: application/json
Accept: application/json
X-Webhook-Secret: YOUR_CATALOG_WEBHOOK_SECRET

{
  "post_id": 412,
  "post_type": "course",
  "status": "publish",
  "slug": "online-mba-example-university",
  "modified": "2026-07-31T10:15:00+00:00",
  "acf": {
    "program_name": "Online MBA",
    "linked_university": 31,
    "total_fee": "₹1.58L"
  }
}
```

## 4. Authentication and setup

The integration uses one shared secret.

1. Set the chatbot server environment variable:

   ```dotenv
   CATALOG_WEBHOOK_SECRET=use-a-long-random-secret-here
   ```

2. Store the exact same value in WordPress configuration, ideally in `wp-config.php` or an environment variable rather than a theme file:

   ```php
   define('DEGREEBABA_CATALOG_WEBHOOK_SECRET', 'use-a-long-random-secret-here');
   ```

3. Send it with every request:

   ```http
   X-Webhook-Secret: use-a-long-random-secret-here
   ```

Do not expose this secret in browser JavaScript, page HTML, or a public repository.

### Authentication and availability responses

| HTTP status | Meaning | WordPress action |
| --- | --- | --- |
| `200` | The request was accepted. It may have created, updated, deleted, or found an unchanged entity. | Treat as success. |
| `401` | The header is missing or does not match the configured secret. | Do not retry automatically. Fix the secret. |
| `422` | The JSON envelope or catalog data is invalid. | Do not retry automatically. Fix the payload/data. |
| `503` | The chatbot has no `CATALOG_WEBHOOK_SECRET` configured. | Retry after the server configuration is corrected. |

Examples:

```json
// 401
{ "detail": "Invalid webhook secret" }
```

```json
// 422: example only; the detail identifies the actual invalid field
{ "detail": "Published course requires a display name in acf" }
```

```json
// 503
{ "detail": "Catalog webhook is not configured" }
```

## 5. When WordPress should send a webhook

Send a webhook after ACF has written the fields for every supported catalog post on:

- first publish;
- edits to published content;
- moving a post to trash;
- saving as draft;
- moving to pending review;
- any status change, including republishing;
- relationship changes, such as assigning a course to a university.

Use `acf/save_post` with a priority after ACF field values are available (the PHP example uses priority `20`). Ignore revisions and autosaves.

`publish` creates or updates the entity. `trash`, `draft`, and `pending` remove the matching entity from the live catalog. A later `publish` request restores it.

## 6. Payload

### Required envelope

Every request must include all six fields below, including when a post is being unpublished.

| Field | Type | Rules |
| --- | --- | --- |
| `post_id` | integer or non-empty string | The stable WordPress post ID. |
| `post_type` | string | Canonical values: `university`, `course`, or `specialization`. |
| `status` | string | `publish`, `trash`, `draft`, or `pending`. |
| `slug` | string | Non-empty WordPress post slug. |
| `modified` | string | ISO-8601 timestamp, for example `2026-07-31T10:15:00+00:00`. |
| `acf` | object | The full ACF state for that entity. Use `{}` only for an unpublish request. |

For a `publish` request, the display name is mandatory inside `acf`:

| Entity | Required display-name field | Accepted fallback fields |
| --- | --- | --- |
| University | `university_full_name` | `university_name`, `title` |
| Course | `program_name` | `name`, `specialization_name`, `spec_name`, `title` |
| Specialization | `specialization_name` | `spec_name`, `name`, `title` |

### Complete course example

This is a complete example of the envelope and shows the supported course fields in use. Only send fields that have real WordPress content; omit unavailable optional fields rather than inventing values.

```json
{
  "post_id": 412,
  "post_type": "course",
  "status": "publish",
  "slug": "online-mba-example-university",
  "modified": "2026-07-31T10:15:00+00:00",
  "acf": {
    "program_name": "Online MBA",
    "university_name": "Example University",
    "linked_university": 31,
    "aliases": ["online mba", "mba online"],
    "category": "management",
    "discipline": "Management",
    "hero_description": "A flexible online MBA for working professionals.",
    "duration": "2 years",
    "mode": "online learning",
    "naac_grade": "NAAC A++",
    "ugc_status": "UGC-DEB Entitled",
    "total_fee": "₹1.58L",
    "starting_fee": "₹79,000",
    "emi_amount": "₹6,600",
    "num_specializations": "8",
    "specialization_ids": ["marketing", "finance", "business-analytics"],
    "budget_bucket": "₹1L–₹2L",
    "difficulty_level": "Intermediate",
    "about_heading": "About the program",
    "about_content": "Program overview from ACF.",
    "highlights_heading": "Program highlights",
    "highlights": [
      {
        "highlight_title": "Flexible learning",
        "highlight_description": "Learn around your work schedule."
      }
    ],
    "accreditations_heading": "Approvals",
    "accreditations": [
      {
        "type": "UGC",
        "value": "Entitled",
        "body_name": "University Grants Commission",
        "body_descriptor": "Recognised",
        "body_detail": "Online programme entitlement"
      }
    ],
    "specializations_heading": "Specializations",
    "specializations_intro": "Choose an area aligned with your goals.",
    "fee_heading": "Fees and EMI",
    "fee_plans": [
      {
        "plan_name": "Semester-wise",
        "plan_amount": "₹79,000",
        "plan_total": "₹1.58L",
        "plan_note": "Two installments"
      },
      {
        "plan_name": "Monthly EMI",
        "plan_amount": "₹6,600",
        "plan_note": "Monthly estimate"
      }
    ],
    "eligibility_heading": "Eligibility",
    "eligibility_content": "A recognised bachelor's degree is required.",
    "eligibility_category": "Graduate",
    "eligibility_requirements": ["Recognised bachelor's degree", "Valid identity proof"],
    "admission_heading": "Admission process",
    "admission_steps": ["Submit application", "Upload documents", "Pay fee"],
    "admission_fee_note": "Application fee may apply.",
    "syllabus_heading": "Curriculum",
    "syllabus_content": "Semester-wise curriculum from ACF.",
    "placement_heading": "Career support",
    "placement_content": "Career services information from ACF.",
    "certificate_description": "Certificate information from ACF.",
    "validity": "Programme validity information from ACF.",
    "career_outcomes": ["Product Manager", "Business Analyst"],
    "career_tracks": ["Management", "Analytics"],
    "salary_outcomes": [{"role": "Business Analyst", "salary": "₹7 LPA"}],
    "job_profiles": [
      {"job_title": "Business Analyst", "avg_salary": "₹7 LPA"}
    ],
    "average_rating": 4.3,
    "review_count": 126,
    "reviews": [
      {
        "review_id": "review-1",
        "review_text": "The learning platform was easy to use.",
        "reviewer_name": "A. Sharma",
        "reviewer_label": "MBA learner",
        "rating": 4.5,
        "theme": "LMS"
      }
    ],
    "faqs_heading": "FAQs",
    "faqs": [
      {"question": "Is the programme online?", "answer": "Yes."}
    ],
    "recommendation_attributes": {"working_professional": true},
    "recommendation_profile": {"career_switch": true},
    "discovery_tags": ["mba", "management"],
    "finder_tags": ["business", "online"],
    "roi_tags": ["management"],
    "scholarship_available": true,
    "scholarship_types": ["Merit"],
    "lead_tags": ["mba", "example-university"],
    "search_keywords": ["online mba", "distance mba"],
    "normalized_search_keywords": ["online mba"],
    "seo_title": "Online MBA | Example University",
    "meta_description": "Online MBA details, fees and eligibility.",
    "eligibility_summary": "Graduates are eligible."
  }
}
```

## 7. ACF field reference

The endpoint retains the ACF object supplied with a published entity and normalizes the fields listed below. Field names are case-sensitive.

### Common identity, taxonomy, and discovery fields

| Field | Applies to | Type | Notes |
| --- | --- | --- | --- |
| `aliases` | All | array of strings | Additional names for the entity. |
| `search_keywords` | All | array of strings | Also used as aliases when `aliases` is absent. |
| `normalized_search_keywords` | All | array of strings | Pre-normalized search phrases. |
| `average_rating` or `rating` | All | number or numeric string | Average student rating. |
| `review_count` or `reviews_count` | All | integer or numeric string | Total number of reviews. |
| `category` | Course, specialization | string | Use a stable taxonomy slug/value. |
| `discipline` | Course, specialization | string | Broad study discipline. |
| `discovery_tags` | All | array of strings | Discovery taxonomy tags. |
| `lead_tags` | All | array of strings | Lead categorisation tags. |
| `finder_tags` | Course, specialization | array of strings | Finder taxonomy tags. |
| `roi_tags` | Course, specialization | array of strings | ROI taxonomy tags. |
| `career_quiz_categories` | Specialization | array of strings | Career quiz taxonomy tags. |
| `budget_bucket` | Course, specialization | string | Budget grouping. |
| `difficulty_level` | Course, specialization | string | Difficulty grouping. |
| `recommendation_attributes` | Course, specialization | object | Structured recommendation data. |
| `recommendation_profile` | Course, specialization | object | Structured recommendation data. |
| `comparison_attributes` | University | object | Structured comparison data. |
| `_edge_case_notes` | All | array of strings | Publisher notes for exceptional cases. |
| `seo_title` | All | string | SEO title. |
| `meta_description` | All | string | SEO description. |

### University fields

| Field | Type | Description |
| --- | --- | --- |
| `university_full_name` | string | Required published university display name. |
| `university_name` | string | Short/display name; defaults to full name. |
| `hero_description` | string | University introduction. |
| `established_year` | string or integer | Establishment year. |
| `naac_grade` or `naac` | string | For example `A++`; `NAAC` prefix is normalized away. |
| `ugc_approved` | boolean or string | UGC approval/status. |
| `mode_of_learning` | string | Delivery mode. |
| `starting_fee` or `fee` | number or string | Starting fee. Parsed amounts also get a numeric value. |
| `num_programs` | string | Published program count. |
| `program_ids` | array of strings | Related program identifiers. |
| `average_rating` or `rating` | number or numeric string | Average rating. |
| `review_count` or `reviews_count` | integer or numeric string | Total review count. |
| `placement_support` | boolean | Whether placement support is available. |
| `industry_projects` | boolean | Whether industry projects are available. |
| `nirf_rank` | integer | NIRF rank. |
| `fee_metadata` | object | Structured fee metadata. |
| `about_heading`, `why_choose_heading`, `facts_heading`, `accreditations_heading`, `programs_heading`, `admission_heading`, `emi_heading`, `exam_heading`, `faculty_heading`, `placement_heading`, `reviews_heading`, `faqs_heading` | string | Optional section headings. |
| `about_content`, `why_choose_content`, `admission_steps`, `admission_fee_note`, `emi_content`, `exam_content`, `faculty_intro`, `placement_content`, `programs_intro` | string | Section content. |
| `facts` | repeater | See [Repeaters](#repeaters). |
| `accreditations` | repeater | See [Repeaters](#repeaters). |
| `programs_table` | repeater | See [Repeaters](#repeaters). |
| `faculty_members` | repeater | See [Repeaters](#repeaters). |
| `reviews` | repeater | See [Repeaters](#repeaters). |
| `faqs` | repeater | See [Repeaters](#repeaters). |

### Course fields

| Field | Type | Description |
| --- | --- | --- |
| `program_name` | string | Required published course display name. |
| `university_name` or `provider_name` | string | University name; resolved parent data takes precedence when available. |
| `linked_university` | relationship | Parent university reference. See [Relationships](#relationships). |
| `hero_description`, `duration`, `mode`, `naac_grade`, `ugc_status` | string | Basic programme information. |
| `total_fee`, `starting_fee`, or `fee` | number or string | Fee values. `fee` is treated as `total_fee`. |
| `emi_amount` or `emi` | number or string | Monthly payment amount. |
| `num_specializations` | string | Published specialization count. |
| `specialization_ids` | array of strings | Related specialization identifiers. |
| `fee_metadata` | object | Structured fee metadata. A parsed total fee creates standard total-fee metadata automatically. |
| `about_heading`, `highlights_heading`, `accreditations_heading`, `specializations_heading`, `fee_heading`, `eligibility_heading`, `admission_heading`, `syllabus_heading`, `placement_heading`, `jobs_heading`, `faqs_heading` | string | Optional section headings. |
| `about_content`, `specializations_intro`, `eligibility_content`, `admission_steps`, `admission_fee_note`, `syllabus_content`, `placement_content`, `certificate_description`, `validity`, `eligibility_summary` | string or string array for `admission_steps` | Section content. |
| `eligibility_category` | string | Eligibility category. |
| `eligibility_requirements` | array of strings | Eligibility checklist. |
| `career_outcomes`, `career_tracks` | array of strings | Career information. |
| `salary_outcomes` | array of objects | Salary outcome rows. |
| `scholarship_available` | boolean | Scholarship availability. |
| `scholarship_types` | array of strings | Scholarship types. |
| `highlights`, `accreditations`, `fee_plans`, `job_profiles`, `reviews`, `faqs` | repeaters | See [Repeaters](#repeaters). |

### Specialization fields

| Field | Type | Description |
| --- | --- | --- |
| `specialization_name` | string | Required published specialization display name. |
| `spec_name` | string | Alternate specialization name. |
| `program_name` | string | Parent programme name. |
| `parent_course` | string or relationship | Parent course name/reference. Prefer `linked_course` for a relationship. |
| `university_name` or `provider_name` | string | University name; resolved parent data takes precedence when available. |
| `linked_university` | relationship | Parent university reference. |
| `linked_course` | relationship | Parent course reference. |
| `duration`, `mode`, `naac_grade`, `ugc_status` | string | Basic specialization information. |
| `total_fee`, `starting_fee`, or `fee` | number or string | Fee values. `fee` is treated as `total_fee`. |
| `emi_amount` or `emi` | number or string | Monthly payment amount. |
| `fee_metadata` | object | Structured fee metadata. A parsed total fee creates standard total-fee metadata automatically. |
| `about_heading`, `highlights_heading`, `eligibility_heading`, `fee_heading`, `other_specs_heading`, `syllabus_heading`, `exam_heading`, `admission_heading`, `placement_heading`, `jobs_heading`, `certificate_heading`, `faqs_heading` | string | Optional section headings. |
| `about_content`, `eligibility_content`, `syllabus_content`, `exam_content`, `admission_steps`, `admission_fee_note`, `placement_content`, `certificate_description`, `eligibility_summary` | string or string array for `admission_steps` | Section content. |
| `eligibility_category` | string | Eligibility category. |
| `eligibility_requirements` | array of strings | Eligibility checklist. |
| `career_outcomes`, `career_tracks` | array of strings | Career information. |
| `salary_outcomes` | array of objects | Salary outcome rows. |
| `highlights`, `other_specs`, `job_profiles`, `reviews`, `faqs` | repeaters | See [Repeaters](#repeaters). |

### Normalization performed by the endpoint

WordPress may send editor-friendly values. The endpoint standardizes these fields when possible:

| Input | Result |
| --- | --- |
| `₹1.58L`, `₹1,58,000`, or `158000` fee | A readable INR value and a numeric fee are stored. |
| `₹6,600` in `emi_amount` / `emi` | Stored as a monthly amount, for example `From INR 6,600 per month`, with a numeric value. |
| `2 years`, `2 yrs`, `24 months` | Standardized to `2 Years` or `24 Months`. |
| `NAAC A++` | Standardized to `A++`. |
| `online learning`, `distance learning`, `blended` | Standardized to `Online`, `Distance`, or `Hybrid`. |

If a monetary value cannot be parsed, its original non-empty text is retained. Use clear INR values to ensure the numeric amount is available.

## 8. Repeaters

Send ACF repeaters as JSON arrays of objects with these keys.

| Repeater | Applies to | Row fields |
| --- | --- | --- |
| `facts` | University | `fact_title`, `fact_description` |
| `accreditations` | University, course | `type`, `value`, `body_name`, `body_descriptor`, `body_detail` |
| `programs_table` | University | `program_name`, `program_fee`, `program_eligibility` |
| `faculty_members` | University | `member_name`, `member_program`, `member_designation`, `member_qualification` |
| `highlights` | Course, specialization | `highlight_title`, `highlight_description` |
| `fee_plans` or `payment_plans` | Course | `plan_name` / `name` / `title`, `plan_amount` / `amount` / `fee` / `value`, `plan_total` / `total`, `plan_note` / `note` / `description` |
| `job_profiles` or `career_profiles` | Course, specialization | `job_title` / `title` / `name`, `avg_salary` / `salary` / `value` |
| `other_specs` | Specialization | `other_spec_name`, `other_spec_fee` |
| `reviews` | All | `review_id`, `review_text`, `reviewer_name`, `reviewer_label`, `rating`, `theme` |
| `faqs` | All | `question`, `answer` |

For fee plans whose name contains `EMI`, `monthly`, `installment`, or `finance`, the amount is normalized as a monthly amount. For job profiles, a parseable salary also produces a numeric salary value.

## 9. Relationships

Relationships connect the catalog hierarchy:

```text
University
    |
    +-- Course
            |
            +-- Specialization
```

Use WordPress post IDs for reliability:

```json
{
  "linked_university": 31,
  "linked_course": 412
}
```

The endpoint also accepts a slug, a single value, an array of values, or an ACF relationship object containing one of `ID`, `id`, `post_id`, `slug`, or `post_name`.

| Child entity | Recommended relationship field | Parent type |
| --- | --- | --- |
| Course | `linked_university` | University |
| Specialization | `linked_university` | University |
| Specialization | `linked_course` | Course |

Compatibility aliases are accepted: `university`, `university_id`, `parent_university`, `course`, `course_id`, and `parent_course`.

If a child reaches the endpoint before its parent, the request still returns `200`. Its response lists the missing parent type in `unresolved_relationships`, for example:

```json
{
  "status": "ok",
  "action": "created",
  "post_id": "412",
  "entity_id": "wp-course-412",
  "changed": true,
  "catalog_version": 18,
  "last_updated": "2026-07-31T10:15:00+00:00",
  "unresolved_relationships": ["university"]
}
```

Send the parent normally. The next successful catalog sync rechecks relationships. A relationship reference must resolve to the expected parent type.

## 10. Payload rules

1. **Send the complete ACF state every time.** This is a full replacement for one entity, not a partial patch. Do not send only the field that changed.
2. **Send one entity per request.** Send parent and child posts as separate requests.
3. **Keep slugs stable and non-empty.** The WordPress post ID is the stable identity; a changed slug updates the same entity.
4. **Use ISO-8601 timestamps.** UTC is recommended: `2026-07-31T10:15:00+00:00`.
5. **Use taxonomy slugs/values consistently.** Arrays must be JSON arrays, not comma-separated strings.
6. **Use actual publication status.** `trash`, `draft`, and `pending` remove the entity from the live catalog. `publish` restores or updates it.
7. **Do not send generated catalog IDs.** The endpoint creates them from WordPress identity, for example `wp-course-412`.
8. **Avoid calculated display fields when source data exists.** Send the true ACF fee, duration, and relationship values; the endpoint handles the standard display normalization.

## 11. Successful responses

Every successful request returns `200` and this shape:

```json
{
  "status": "ok",
  "action": "created",
  "post_id": "412",
  "entity_id": "wp-course-412",
  "changed": true,
  "catalog_version": 18,
  "last_updated": "2026-07-31T10:15:00+00:00",
  "unresolved_relationships": []
}
```

| Field | Meaning |
| --- | --- |
| `action` | `created`, `updated`, `unchanged`, or `deleted`. |
| `changed` | `true` when this request changed the catalog; `false` for an idempotent repeat or deleting an entity that was already absent. |
| `entity_id` | Generated catalog ID. It is `null` when an unpublish request finds no matching entity. |
| `catalog_version` | Version after the request. It does not increase for `unchanged`. |
| `last_updated` | Timestamp attached to the latest successful catalog change. |
| `unresolved_relationships` | Missing parent types, if any. Empty means all supplied parent references resolved. |

## 12. Error handling and retries

Use the response code, not response text, to decide whether to retry.

| Situation | Retry? | What to do |
| --- | --- | --- |
| Network timeout / DNS / connection failure | Yes | Queue and retry with exponential backoff. The same full payload is safe to send again. |
| `500`-range server response, including `503` | Yes | Retry with backoff. Alert after repeated failures. |
| `401` | No | Correct the shared secret and resend. |
| `422` | No | Correct the ACF data or envelope and resend. |
| `200` with `unchanged` | No | This is a successful duplicate delivery. |
| `200` with `unresolved_relationships` | Usually no immediate retry | Ensure the parent post is sent. Re-send the child after the parent if needed. |

Recommended retry delays: 1 minute, 5 minutes, 15 minutes, then 1 hour. Keep a small persistent WordPress queue or log for failed events so edits are not lost if the endpoint is temporarily unavailable.

## 13. Copy-paste PHP example

Put this in a site plugin or a must-use plugin, not directly in a theme. Replace the two configuration values and map your actual WordPress custom post type slugs in `degreebaba_catalog_post_type()`.

```php
<?php
/**
 * wp-content/mu-plugins/degreebaba-catalog-sync.php
 */

define('DEGREEBABA_CATALOG_SYNC_URL', 'https://chat-bot-id1n.onrender.com/api/catalog/sync');
define('DEGREEBABA_CATALOG_WEBHOOK_SECRET', 'YOUR_CATALOG_WEBHOOK_SECRET');

function degreebaba_catalog_post_type($wp_post_type) {
    $map = array(
        // Replace the keys with your real custom post type slugs.
        'university'      => 'university',
        'course'          => 'course',
        'specialization'  => 'specialization',
    );

    return isset($map[$wp_post_type]) ? $map[$wp_post_type] : null;
}

function degreebaba_sync_catalog_post($post_id, $status_override = null) {
    if (wp_is_post_revision($post_id) || wp_is_post_autosave($post_id)) {
        return;
    }

    $post = get_post($post_id);
    if (!$post) {
        return;
    }

    $catalog_post_type = degreebaba_catalog_post_type($post->post_type);
    if (!$catalog_post_type) {
        return; // Not a catalog post type.
    }

    // get_fields() is called after ACF has saved. Keep all field values.
    $acf = get_fields($post_id);
    $acf = is_array($acf) ? $acf : array();

    // The endpoint requires a display name for published records. These
    // fallbacks use the WP title only if the matching ACF field is empty.
    if ($catalog_post_type === 'university' && empty($acf['university_full_name'])) {
        $acf['university_full_name'] = get_the_title($post_id);
    }
    if ($catalog_post_type === 'course' && empty($acf['program_name'])) {
        $acf['program_name'] = get_the_title($post_id);
    }
    if ($catalog_post_type === 'specialization' && empty($acf['specialization_name'])) {
        $acf['specialization_name'] = get_the_title($post_id);
    }

    $modified_timestamp = get_post_modified_time('U', true, $post);
    $payload = array(
        'post_id'   => (int) $post_id,
        'post_type' => $catalog_post_type,
        'status'    => $status_override ?: $post->post_status,
        'slug'      => $post->post_name,
        'modified'  => gmdate('c', (int) $modified_timestamp),
        'acf'       => $acf,
    );

    $response = wp_remote_post(DEGREEBABA_CATALOG_SYNC_URL, array(
        'timeout'     => 15,
        'data_format' => 'body',
        'headers'     => array(
            'Content-Type'     => 'application/json',
            'Accept'           => 'application/json',
            'X-Webhook-Secret' => DEGREEBABA_CATALOG_WEBHOOK_SECRET,
        ),
        'body' => wp_json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
    ));

    if (is_wp_error($response)) {
        error_log('DegreeBaba catalog sync network error for post ' . $post_id . ': ' . $response->get_error_message());
        // Add this payload to your persistent retry queue here.
        return;
    }

    $status_code = wp_remote_retrieve_response_code($response);
    $body = wp_remote_retrieve_body($response);
    $json = json_decode($body, true);

    if ($status_code < 200 || $status_code >= 300) {
        error_log(sprintf(
            'DegreeBaba catalog sync failed for post %d: HTTP %d: %s',
            $post_id,
            $status_code,
            $body
        ));

        // Retry only transient failures (for example 5xx). Do not retry 401
        // or 422 until the secret or source ACF data has been corrected.
        return;
    }

    if (!is_array($json) || ($json['status'] ?? null) !== 'ok') {
        error_log('DegreeBaba catalog sync returned an unexpected success body for post ' . $post_id);
        return;
    }

    if (!empty($json['unresolved_relationships'])) {
        error_log(
            'DegreeBaba catalog sync saved post ' . $post_id .
            ' with unresolved relationships: ' .
            implode(', ', $json['unresolved_relationships'])
        );
    }
}

// Priority 20 runs after ACF has saved the field values.
add_action('acf/save_post', 'degreebaba_sync_catalog_post', 20);

// ACF save covers normal editor updates. This hook additionally captures status
// changes such as trash, draft, pending, and direct publish transitions.
function degreebaba_sync_catalog_status_change($new_status, $old_status, $post) {
    if ($new_status === $old_status || !($post instanceof WP_Post)) {
        return;
    }

    if (!in_array($new_status, array('publish', 'trash', 'draft', 'pending'), true)) {
        return;
    }

    degreebaba_sync_catalog_post($post->ID, $new_status);
}
add_action('transition_post_status', 'degreebaba_sync_catalog_status_change', 20, 3);
```

## 14. Testing checklist

Run these checks against a non-production endpoint first.

| Test | Expected result |
| --- | --- |
| Publish a university | `200`, `action: "created"`, generated `wp-university-<post_id>` ID. |
| Edit a fee | `200`, `action: "updated"`, `changed: true`; readable and numeric fee are available. |
| Edit eligibility | `200`, `action: "updated"`; complete eligibility fields are retained. |
| Rename a course | `200`, `action: "updated"`; same generated ID, updated name/slug. |
| Send the same payload twice | Second response is `200`, `action: "unchanged"`, `changed: false`. |
| Add course → university relationship | Parent resolves and `unresolved_relationships` is empty once both records are sent. |
| Send child before parent | `200`, child is accepted with `unresolved_relationships`; send parent and then confirm resolution. |
| Delete/trash a course | `200`, `action: "deleted"`; course is no longer live. |
| Save course as draft or pending | Same removal behaviour as trash. |
| Republish the course | `200`, `created` or `updated`; course returns to the catalog. |
| Add a review repeater | `200`; review text, reviewer, rating, and theme are retained. |
| Add fee-plan repeater | `200`; EMI-style plan is represented as a monthly amount. |
| Invalid secret | `401`; no catalog change. |
| Invalid timestamp or missing required field | `422`; no catalog change. |
| Endpoint unavailable | WordPress records a retryable failure and later retries the same full payload. |

## 15. FAQ

### Why send the whole payload instead of only changed fields?

Each request represents the current complete state of one WordPress entity. This prevents stale fields from remaining after an editor removes or clears an ACF field.

### Can I send multiple entities in one request?

No. Send one university, course, or specialization per request. For a hierarchy change, send the parent and child as separate requests.

### What happens when content is unpublished?

When `status` is `trash`, `draft`, or `pending`, the matching entity is removed from the live catalog. Publishing it again adds it back.

### What happens if the endpoint is offline?

The endpoint cannot receive a request that WordPress never successfully delivers. WordPress should keep failed payloads in a retry queue and retry network failures and `5xx` responses with backoff.

### Does retrying create duplicate entries?

No. Identity is based on the entity type and WordPress post ID. Repeating an identical successful payload returns `action: "unchanged"`.

### How are relationships handled?

Use `linked_university` and `linked_course` with WordPress post IDs. A child may arrive first; it is accepted and reports the unresolved parent in the response. Send the parent normally and re-send the child if your integration needs immediate confirmation.

### Can I use ACF relationship field objects instead of IDs?

Yes. The endpoint accepts values with `ID`, `id`, `post_id`, `slug`, or `post_name`. Sending IDs is preferred because it is stable if a slug changes.

### Which monetary format should I send?

Send clear INR values such as `₹1,58,000`, `₹1.58L`, or `158000`. The endpoint standardizes parseable amounts and keeps the numeric value alongside the readable value.

### Why did I receive `422`?

The request was valid JSON but did not meet the catalog contract. Common causes are an unsupported `post_type` or status, a missing published display name, an empty slug, or a non-ISO timestamp. Correct the data and send the full payload again.
