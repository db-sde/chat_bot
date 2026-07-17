# DegreeBaba AI Admissions Advisor — UI Redesign

## Design basis

The production widget follows the local DegreeBaba reference in
`/Users/aryankinha/Documents/Degree/Chatbot design layout`:

- DM Sans with a compact 11–16 px widget type scale;
- navy `#0E1F3D` for authority and user messages;
- orange `#E84010` for AI accents and high-intent actions only;
- off-white `#F7F8FA` canvas, white answer surfaces, and `#E5E7EB` dividers;
- 4 / 8 / 12 / 16 px spacing increments;
- restrained shadows and 12–18 px radii.

No external visual system was introduced.

## Component hierarchy

```text
Widget shell
├── Navy assistant header
│   ├── DegreeBaba identity
│   ├── live status
│   └── minimize control
├── Conversation viewport
│   ├── sticky context card
│   │   ├── university line
│   │   ├── course / specialization line
│   │   ├── published metadata badges
│   │   └── clear control
│   ├── grouped assistant messages
│   ├── content-sized user messages
│   ├── cards / comparisons / guided answers
│   ├── quick-action chips
│   └── typing indicator
├── Compact composer
│   ├── question input
│   └── aligned send action
└── Privacy reassurance
```

## Desktop layout

- 400 px floating panel with a 650 px maximum height.
- Conversation rows use an 8 px stream gap and 10 px message separation.
- Assistant bubbles use a white surface, thin divider, subtle shadow, and 18 px radius.
- User bubbles size to their content and cap only when messages become long.
- Context is a compact white card rather than a large orange pill.
- Composer controls are 40 px high to preserve conversation space.

## Mobile layout

- Full-viewport sheet below 560 px.
- Reduced 6 px stream gap and 8 px message separation.
- Safe-area-aware composer and footer.
- Starter choices collapse to one column below 360 px.
- Follow-up chips wrap instead of hiding important options off-screen.

## Compact recommendation cards

- Recommendation cards use a 9–10 px inset, 12 px radius, hairline border, and restrained shadow.
- University/program naming remains first, followed by accreditation and one inline metadata row.
- Fee, duration, and specialization/program counts render as text separated by bullets; recommendation
  cards no longer contain nested metric boxes.
- Published EMI, career, establishment, and other available lower-priority facts move into the
  `Details` view instead of increasing every card's height.
- `Details` and `+ Compare` are 28 px compact actions rather than full-width button blocks.
- Recommendation lists use a 7 px gap so two complete results and part of the next can remain visible
  alongside the advisor's message on typical mobile viewports.

## Catalog picker

- The picker separates its sheet header, search control, optional published `Popular` results, and the
  complete catalog with explicit section labels.
- Search displays the current catalog count and changes the list heading to a live result count.
- Results use single-column rows, quiet dividers, deterministic monogram tones, and no heavy alphabet bars.
- Below 560 px the picker occupies the full viewport, includes a sheet handle and safe-area spacing, and
  hides the separate launcher while the widget is open.

## Interaction states

- **Hover:** neutral actions move to orange-soft; high-intent actions become solid orange.
- **Focus:** navy input border and a restrained focus ring.
- **Typing:** existing animated three-dot state remains visible beside the assistant identity.
- **Loading/error:** existing grounded loading and retry states keep their current behavior.
- **Grouped messages:** only the first message in a consecutive assistant group shows an avatar.
- **Context clear:** removes navigation focus without deleting rendered conversation history.
- **Apply Now:** reuses the existing phone-only counsellor flow with application-specific copy.

## UX rationale

- Reduced row spacing exposes more conversation history without shrinking readable text.
- Content-sized user bubbles prevent short values such as `BCOM` from wrapping.
- Avatar grouping preserves identity while removing repetitive visual noise.
- The context card separates institution, program, and trust metadata so scope is scannable.
- Orange is reserved for AI accents and conversion moments, improving hierarchy and trust.
- Quick actions keep common next steps tappable and prevent unnecessary keyboard use.
- Progressive disclosure keeps recommendations scannable while preserving published decision data in
  the detail surface.
- Apply actions appear after high-value answers; brochure actions are intentionally omitted until
  a real brochure URL or API field exists.
