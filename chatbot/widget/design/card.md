# DegreeBaba Widget — Card Components Report

> All cards are extracted from the design files:
> - CSS: [`design.css`](file:///Users/aryankinha/Documents/Degree/chatbotDesign/design.css)
> - JS: [`design.js`](file:///Users/aryankinha/Documents/Degree/chatbotDesign/design.js)

---

## Card Inventory (9 card types + 3 overlays + 2 inline widgets)

| # | Card Name | CSS Class | JS Function | Triggered by |
|---|-----------|-----------|-------------|--------------|
| 1 | Program Card | `.db-card` | `renderCard()` | `m.kind === 'cards'` |
| 2 | Compare Table | `.db-compare` | `renderCompare()` | `m.kind === 'compare'` |
| 3 | Lead Capture | `.db-lead` | `renderLead()` | `m.kind === 'lead'` |
| 4 | Fees Card | `.db-fees` | `renderFees()` | `m.kind === 'fees'` |
| 5 | Eligibility Card | `.db-elig` | `renderElig()` | `m.kind === 'elig'` |
| 6 | Career Card | `.db-career` | `renderCareer()` | `m.kind === 'career'` |
| 7 | Reviews Card | `.db-reviews` | `renderReviews()` | `m.kind === 'reviews'` |
| 8 | Syllabus Card | `.db-syllabus` | `renderSyllabus()` | `m.kind === 'syllabus'` |
| 9 | Tool Result Card | `.db-tool-result` | `renderToolResult()` | `m.kind === 'toolResult'` |
| 10 | Picker Sheet | `#db-picker` | `renderPicker()` | Overlay (slide-up) |
| 11 | Details View | `#db-details` | `renderDetails()` | Overlay (full-screen) |
| 12 | End Screen | `#db-end-screen` | `renderEndScreen()` | Overlay (full-screen) |
| 13 | Tool Widget | `#db-tool-widget` | `renderToolWidget()` | Inline interactive |
| 14 | Finder Widget | `#db-finder-widget` | `renderFinderWidget()` | Inline interactive |

---

## 1. Program Card (`.db-card`) — CSS Lines 299–404

The core card shown when the bot recommends a university or program.

### Structure
```
.db-card                    ← white card, 12px radius, 1px border, subtle shadow
  .db-card-head             ← flex row
    .db-card-mono           ← 42×42 colored square, initials, white bold text
    div
      .db-card-title        ← 15px 600 weight, navy (#0E1F3D)
      .db-card-trust        ← 11px grey subtitle (e.g. "NAAC A+  ·  56k students")
  .db-pills-row             ← flex row of pills
    .db-pill                ← monospace font, grey bg, shows: duration · fee · batch
  .db-card-emi              ← 12px grey text, EMI note
  .db-card-job              ← optional, orange bg box (#FDF1EC), placement highlight
  .db-card-actions          ← flex row with 2 buttons
    .db-btn-primary         ← "View details", navy bg
    .db-btn-compare         ← "+ Compare" / "✓ Added", white/orange toggle state
```

### Data fields consumed
- `c.mono` — 2-letter initials (e.g. "JU")
- `c.bg` — hex color for the monogram background
- `c.title` — program/university name
- `c.trust` — trust line (accreditation, student count)
- `c.pills[]` — array of text strings shown as pills
- `c.emi` — EMI note string (optional)
- `c.job` — job placement note (optional)

### States
- Default: white `.db-btn-compare`
- Added to compare: `.db-btn-compare.db-in-compare` → orange bg

---

## 2. Fees Card (`.db-fees`) — CSS Lines 549–630

Shows a full fee breakdown for a program.

### Structure
```
.db-fees                    ← white card, overflow hidden
  .db-fees-hero             ← flex row, space-between, bottom-border
    div
      .db-fees-total-label  ← 11px grey, "Total programme fee"
      .db-fees-total-value  ← 24px 600, JetBrains Mono, navy — big number (e.g. ₹3,42,000)
    div
      .db-fees-sem-label    ← 11px grey, "Per semester", right-align
      .db-fees-sem-value    ← 14px 600, Mono, navy, right-align
  .db-fees-plans            ← list of payment plan rows
    .db-fees-plan-row       ← space-between row, bottom border
      div
        .db-fees-plan-label ← 13px 500, plan name (e.g. "One-time payment")
        .db-fees-plan-note  ← 11px grey, note (e.g. "Save ₹8,550")
      .db-fees-plan-value   ← 13px 600, Mono, navy
  .db-fees-emi              ← orange-tinted box (#FDF1EC + border), dollar icon + EMI note
```

### Data fields consumed (`f` object)
- `f.total` — total fee string
- `f.perSem` — per-semester fee string
- `f.plans[]` — array of `{label, note, value}`
- `f.emiNote` — EMI summary string

---

## 3. Eligibility Card (`.db-elig`) — CSS Lines 632–699

Shows whether the user qualifies for a program.

### Structure
```
.db-elig                    ← white card, overflow hidden
  .db-elig-hero             ← green tinted header row (#EAF3DE)
    .db-elig-check          ← 32×32 dark green circle, white check SVG
    div
      .db-elig-verdict      ← 15px 600, "Eligible!" or "Not eligible"
      .db-elig-sub          ← 11px green text, supporting note
  .db-elig-list             ← list of requirement rows
    .db-elig-row            ← flex row, bottom border
      .db-elig-icon.ok      ← green background circle, check icon
      .db-elig-icon.opt     ← grey background, dash icon
      div
        .db-elig-req-title  ← 13px 500, requirement description
        .db-elig-req-note   ← 11px grey, sub-note
```

### Data fields consumed (`elig` object)
- `elig.verdict` — "Eligible!" / "Borderline" / etc.
- `elig.sub` — sub text, e.g. "Meets all core requirements"
- `elig.reqs[]` — array of `{ok: bool, t: string, note: string}`

---

## 4. Career Card (`.db-career`) — CSS Lines 701–786

Shows salary data and career paths for a program.

### Structure
```
.db-career                      ← white card, overflow hidden
  .db-career-hero               ← navy (#0E1F3D) header, white text
    .db-career-label            ← 11px uppercase grey, "Average starting salary"
    div
      .db-career-avg            ← 26px 600 Mono, salary figure (e.g. "₹8.2 LPA")
      .db-career-range          ← 12px, range note (e.g. "₹5–18 LPA")
  .db-career-roles              ← white section
    .db-career-roles-label      ← 10.5px uppercase grey, "Roles you can target"
    .db-career-role-row × N     ← each role, space-between
      .db-career-role-title     ← 13px 500 navy
      .db-career-role-salary    ← 12.5px 600 Mono navy
  .db-career-recruiters         ← white section
    .db-career-recruiters-label ← 10.5px uppercase grey, "Top recruiters"
    .db-recruiter-tags          ← flex-wrap tag cloud
      .db-recruiter-tag × N     ← grey bg pill per company
```

### Data fields consumed (`c` object)
- `c.avg` — average salary string
- `c.range` — range string
- `c.roles[]` — array of `{t: title, s: salary}`
- `c.recruiters[]` — array of company name strings

---

## 5. Reviews Card (`.db-reviews`) — CSS Lines 788–909

Shows aggregated student reviews, ratings and sentiment.

### Structure
```
.db-reviews
  .db-reviews-summary             ← flex row, bottom border
    div
      .db-rating-big              ← 30px 600 Mono, e.g. "4.3"
      .db-rating-stars            ← 13px orange, star characters
      .db-rating-count            ← 10.5px grey, "2,847 reviews"
    .db-rating-bars               ← bar chart for each star level
      .db-bar-row × 5
        .db-bar-label             ← "5", "4" etc
        .db-bar-track             ← grey track
          .db-bar-fill            ← orange (#E84010) fill, width=pct
  .db-reviews-sentiment           ← flex 2 cols
    .db-praised                   ← green bg, "Most praised" section
      .db-praised-label           ← 10px uppercase green
      .db-praised-text            ← 12px text
    .db-flagged                   ← amber bg (#FEF3E2), "Most flagged"
      .db-flagged-label           ← 10px uppercase amber
      .db-flagged-text            ← 12px text
  .db-reviews-quotes
    .db-quote × N                 ← individual quote rows
      .db-quote-text              ← 13px italic quote
      .db-quote-name              ← 11px grey, reviewer name
```

### Data fields consumed (`rv` object)
- `rv.rating` — number string
- `rv.stars` — star characters string
- `rv.count` — total reviews count
- `rv.bars[]` — `{stars: "5", pct: "72%"}`
- `rv.praised` — praised text
- `rv.flagged` — flagged text
- `rv.quotes[]` — `{t: quote text, n: reviewer name}`

---

## 6. Syllabus Card (`.db-syllabus`) — CSS Lines 911–997

Expandable accordion showing curriculum by semester.

### Structure
```
.db-syllabus                      ← white card
  .db-syllabus-head               ← flex space-between row, bottom border
    .db-syllabus-title            ← 14px 600 navy
    .db-syllabus-meta             ← 11px Mono grey (e.g. "6 semesters · 120 credits")
  .db-sem-item × N               ← one per semester (border-top)
    button.db-sem-toggle          ← clickable header, bg changes on open/close
      .db-sem-toggle-inner
        .db-sem-num               ← 26×26 rounded, "S1"–"S6", navy bg when open
        .db-sem-title             ← 13px 500, semester name
      .db-sem-chevron             ← rotates 180° on open
    .db-sem-subs                  ← only rendered when open
      .db-sem-sub × N             ← 12.5px, orange dot + subject name
        .db-sub-dot               ← 5px orange circle
```

### Data fields consumed (`sy` object)
- `sy.title` — program name
- `sy.meta` — "6 semesters · 120 credits"
- `sy.items[]` — `{n: "S1", title: "Semester 1", subs: ["Subject A", ...]}`

### Interactivity
- `data-action="toggleAcc"` on each `.db-sem-toggle`
- State stored in `state.acc[mid+':'+idx]`

---

## 7. Tool Result Card (`.db-tool-result`) — CSS Lines 999–1058

Displays a calculated result (scholarship amount, ROI, etc.) in-chat.

### Structure
```
.db-tool-result                     ← white card
  .db-tool-result-hero              ← colored header (green default, custom via headBg)
    .db-tool-result-label           ← 11px uppercase, colored (labelColor)
    .db-tool-result-value           ← 26px 600 Mono navy, the big result
  .db-tool-steps                    ← "How to claim it" section
    .db-tool-steps-label            ← 10.5px uppercase grey
    .db-tool-step × N
      .db-tool-step-num             ← 22×22 navy circle, step number
      .db-tool-step-text            ← 13px, step instruction
```

### Data fields consumed (`tr` object)
- `tr.label` — section label string
- `tr.labelColor` — hex color (default `#3B6D11`)
- `tr.value` — big display value
- `tr.headBg` — header bg color (default `#EAF3DE`)
- `tr.steps[]` — optional array of `{n: "1", t: "step description"}`

---

## 8. Compare Table (`.db-compare`) — CSS Lines 406–460

Side-by-side comparison of two programs, rendered as a grid table.

### Structure
```
.db-compare                         ← white card, overflow hidden
  .db-compare-head                  ← 3-col grid
    .db-compare-head-empty          ← navy bg, empty first cell
    .db-compare-head-cell × 2       ← navy bg, white 12px 600 text, each program name
  .db-compare-row × N               ← 3-col grid, top border
    .db-compare-key                 ← 11px grey, metric name (e.g. "Fees", "Duration")
    .db-compare-val × 2             ← 12px navy, centered values
  .db-compare-verdict               ← orange-tinted box
    .db-verdict-label               ← "Verdict" in orange
    span                            ← verdict text
```

### Data fields consumed (`m` object)
- `m.aName`, `m.bName` — program names
- `m.rows[]` — `{k: metric, a: valueA, b: valueB}`
- `m.verdict` — recommendation text

---

## 9. Lead Capture Card (`.db-lead`) — CSS Lines 462–547

Phone number collection form shown in-chat.

### Structure (two states)

**Default state:**
```
.db-lead
  .db-lead-text       ← 14px message text
  .db-lead-form       ← flex row
    .db-phone-wrapper ← pill input with +91 prefix
      .db-phone-prefix ← "+91"
      input.db-phone-input
    button.db-lead-send ← orange "Send" button
  .db-lead-note       ← 11px grey disclaimer
```

**Done state (after submission):**
```
.db-lead
  .db-lead-done       ← flex row
    .db-lead-done-icon ← green circle, check icon
    .db-lead-done-text ← "Done — a counsellor will call..."
```

### Data fields consumed (`m` object)
- `m.text` — message prompt
- `m.leadDone` — boolean, switches to done state
- `m.id` — message ID for action routing

---

## 10. Picker Sheet (`#db-picker`) — CSS Lines 1187–1324

Slide-up overlay for selecting a university or specialization.

### Structure
```
#db-picker                          ← absolute full-screen overlay
  .db-picker-scrim                  ← 88px dark scrim at top, tap to dismiss
  .db-picker-sheet                  ← white rounded-top panel, flex column
    .db-picker-header
      .db-picker-handle             ← 38×4 grey drag handle
      .db-picker-title-row          ← title + close X button
      .db-picker-search             ← search bar with search icon
    .db-picker-list                 ← scrollable
      .db-picker-section-label      ← "⭐ Popular" / "All" labels
      .db-picker-row × N            ← each item row
        .db-picker-mono             ← 36×36 colored monogram square
        div
          .db-picker-row-name       ← 14px 500 navy
          .db-picker-row-meta       ← 11px grey
      .db-picker-empty              ← "Nothing matched" state
```

### Two modes (`p.kind`)
- `'uni'` — searches UNIS list, "Search 56 universities…"
- `'spec'` — searches SPECS list, "Search 40 disciplines…"

---

## 11. Details View (`#db-details`) — CSS Lines 1326–1532

Full-screen overlay showing complete program/university details.

### Structure
```
#db-details                         ← absolute full-screen, navy header
  .db-details-header                ← navy bg
    button.db-details-back          ← "‹ Back" button
    .db-details-title-row
      .db-details-mono              ← 46×46 monogram
      .db-details-name              ← 17px 600 white
      .db-details-trust             ← 12px white/65%
  .db-details-body                  ← scrollable content
    .db-details-pills               ← flex row of stat pills (duration, fee, batch)
    .db-info-card                   ← hero description text
    .db-info-card → accreditations  ← .db-accr-tag pills (green)
    .db-info-card → admission steps ← numbered step list
    .db-info-card → learner reviews ← reviewer name + text
    .db-info-card → FAQs            ← Q&A pairs
  .db-details-footer
    .db-cta-primary                 ← orange "Ask about fees & EMI"
```

---

## 12. End Screen (`#db-end-screen`) — CSS Lines 1896–2160

Full-screen result screen shown after tool completion (ROI or Scholarship).

### Structure
```
#db-end-screen                      ← absolute full-screen, navy header
  .db-end-header                    ← navy bg
    .db-end-header-top              ← "DB" badge + close button
    .db-end-hero                    ← centered result display
      .db-end-check-ring            ← green glow ring
        .db-end-check-inner         ← dark green circle, white check
      .db-end-head-label            ← "Your ROI result" / "Scholarship unlocked"
      .db-end-hero-value            ← 34px Mono — big value ("14 months" / "25% off")
      .db-end-hero-sub              ← supporting sub text
  .db-end-body                      ← scrollable
    .db-end-confirm                 ← green confirmation card
      .db-end-confirm-icon          ← phone icon in green circle
      .db-end-confirm-name          ← "Locked in, [FirstName]."
      .db-end-confirm-sub           ← call back notice + masked number
    (detail card — two variants)
  .db-end-footer
    .db-cta-primary                 ← orange "See matching programs"
    .db-cta-secondary               ← grey "Back to chat"
```

### ROI Variant detail card
```
.db-info-card
  .db-roi-stats                     ← 3-col flex
    .db-roi-stat × 3                ← Investment | Avg Salary | EMI/mo
      .db-roi-stat-label            ← 10px uppercase grey
      .db-roi-stat-value            ← 13.5px 600 Mono
  .db-roi-verdict                   ← orange-tinted verdict text box
```

### Scholarship Variant detail card
```
.db-info-card
  .db-schol-fee-row                 ← space-between
    .db-schol-net-value             ← 24px 600 Mono, net fee after waiver
    .db-schol-std-value             ← 14px 600 Mono, strikethrough original
  .db-schol-reasons                 ← flex-wrap green tags
    .db-schol-reason × N            ← green pill with check icon + reason text
.db-info-card
  .db-tool-step × N                 ← numbered "How to claim" steps
  .db-offer-locked                  ← amber pill, "Offer locked for 7 days"
```

---

## 13. Tool Widget (`#db-tool-widget`) — CSS Lines 1534–1815

Inline interactive tool for Career Quiz, ROI Calculator, Scholarship Checker. Renders inside the message stream, goes through multiple phases.

### Phases

| Phase | What renders |
|-------|-------------|
| `entry` | Title, promise text, step count badge, "Start" button |
| `step` | Progress bar, question text, 2×col option grid, optional Back button |
| `partial` | Green partial result box, "See full result" button |
| `lead` | Name + phone inputs, "Reveal my result" + "Skip" buttons |

### Key sub-elements
- `.db-tool-icon-badge` — 24×24 orange-tinted badge with emoji icon
- `.db-progress-track / .db-progress-fill` — orange progress bar
- `.db-tool-opt` — selectable option button, orange border+bg when `.selected`
- `.db-tool-partial-box` — green (#EAF3DE) result preview box
- `.db-tool-name-input / .db-tool-phone-row` — lead capture inputs

---

## 14. Finder Widget (`#db-finder-widget`) — CSS Lines 1817–1894

4-question wizard to help users find the right program.

### Structure
```
#db-finder-widget                   ← inline in message stream
  .db-finder-title-row              ← "Help me choose" + X close button
  .db-tool-progress                 ← shared progress bar (uses tool classes)
  .db-prefill-note                  ← green note if page context pre-filled
  .db-finder-question               ← 15px 600 question text
  .db-finder-opts                   ← 2-col grid of option buttons
    .db-finder-opt × N
  button.db-finder-skip             ← orange text "Skip → show results now"
```

---

## Chip Grid (`.db-chip-grid`)

Not a card, but the quick-action chip area that appears before/after messages.

```
.db-chips-area
  .db-chips-hint        ← "Or type your question below." (only on first load)
  .db-chip-grid         ← CSS grid, 2 columns
    .db-chip × N        ← white card button, 44px min-height, hover grey bg
  .db-more-btn          ← dashed border "More ⌄" button (when hasMore=true)
```

---

## Color Reference

| Color | Hex | Usage |
|-------|-----|-------|
| Navy (primary) | `#0E1F3D` | Headers, text, primary buttons |
| Orange (accent) | `#E84010` | CTA buttons, star ratings, accents |
| Green (positive) | `#3B6D11` / `#EAF3DE` | Eligibility, scholarship, confirm states |
| Amber (warning) | `#9A6412` / `#FEF3E2` | "Most flagged", offer-locked badge |
| Light grey (bg) | `#F7F8FA` | Widget background, input bg |
| Mid grey (border) | `#E5E7EB` | All card borders |
| Orange tint | `#FDF1EC` / `#F6D3C4` | Job highlight, compare verdict, tool selected |

## Typography Reference

| Font | Usage |
|------|-------|
| DM Sans | All body text, headings, buttons |
| JetBrains Mono | Fees, salaries, pills, progress labels, phone input |
