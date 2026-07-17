# DegreeBaba Widget — Design-System Audit and Implementation Notes

## Source hierarchy

The implementation was checked against every named file in
`/Users/aryankinha/Documents/Degree/chatbotDesign`:

1. `_ds/.../colors_and_type.css` and `_ds_manifest.json` define the canonical tokens.
2. `_ds/.../README.md` defines the canonical visual and interaction rules.
3. `DegreeBaba Chatbot.dc.html` defines the chatbot-specific component anatomy.
4. The two designer specifications define journeys, state limits, responsive behavior, and tool states.
5. `_ds_bundle.js` confirms the shared Button, Input, Card, Badge, and icon treatments.
6. `ios-frame.jsx` is a presentation frame, not a production widget dependency.
7. `support.js` is generated Design Canvas runtime plumbing and contains no DegreeBaba component rules.

Where an old specification preamble mentions Cormorant Garamond, warm dark surfaces, or gold,
the actual token CSS, manifest, bundle, and rendered chatbot canvas all agree on DM Sans, navy,
orange, off-white, white, and cool grey. Those executable design sources take precedence.

## 1. Design-system summary

### Color tokens

| Role | Token | Value |
|---|---|---|
| Primary | `--color-navy` | `#0E1F3D` |
| Primary hover | `--color-navy-hover` | `#162D54` |
| Accent / CTA | `--color-orange` | `#E84010` |
| Accent hover | `--color-orange-hover` | `#C93509` |
| Canvas | `--color-bg` | `#F7F8FA` |
| Surface | `--color-surface` | `#FFFFFF` |
| Border | `--color-border` | `#E5E7EB` |
| Primary text | `--gray-900` | `#111827` |
| Secondary text | `--gray-600` | `#4B5563` |
| Disabled / placeholder | `--gray-400` | `#9CA3AF` |
| Soft hover | `--gray-100` | `#F3F4F6` |
| Success | text / bg / border | `#3B6D11` / `#EAF3DE` / `#B6D98A` |
| Warning | text / bg / border | `#854F0B` / `#FAEEDA` / `#F5C97A` |
| Error | text / bg / border | `#A32D2D` / `#FCEBEB` / `#F09595` |
| Info | text / bg / border | `#185FA5` / `#E6F1FB` / `#93C4EE` |

The chatbot canvas also publishes restrained supporting colors for monogram tiles and its
orange-soft verdict treatment. These are used only where the chatbot asset explicitly defines them.

### Typography

- UI family: DM Sans.
- Numeric/technical family: JetBrains Mono.
- Supported weights: 400 body, 500 controls/labels, 600 headings.
- Canonical scale: 11, 12, 14, 16, 20, and 24 px.
- Chatbot-specific compact labels in the canvas use 9.5–13 px where viewport density requires it.
- Body line height is 1.6; compact controls use 1.2–1.5.

### Spacing, radius, shadow, and motion

- Spacing unit: 4 px; scale is 4, 8, 12, 16, 24, 32, 48 px.
- Radius scale: 4 px badges, 8 px controls, 12 px cards, 16 px modal surfaces.
- Chat bubbles use the canvas's asymmetric `4px 15px 15px 15px` treatment.
- Card shadow: `0 1px 3px rgba(0,0,0,0.06)`.
- Modal shadow: `0 8px 24px rgba(0,0,0,0.12)`.
- Dropdown shadow: `0 4px 12px rgba(0,0,0,0.10)`.
- Standard interaction transition: `all 0.15s ease`.
- Progress transition: `all 0.3s ease`.
- No decorative gradients or frosted-glass blur.
- Reduced-motion mode removes non-essential animation.

### Chat-specific layout and states

- Navy identity header, off-white transcript, white assistant bubbles, navy user bubbles.
- Input remains unfocused on widget open; selection-first guidance remains primary.
- New bot content anchors at its first line.
- Guided options are a two-column grid, with at most three follow-ups after answers.
- Picker is a separate sheet with search, optional catalog-backed Popular section, and All/results.
- Context remains sticky and dismissible.
- Cards, comparison, details, lead, loading, empty, timeout, and finder states reuse existing data.
- Mobile uses a full-viewport panel and safe-area-aware sheet/composer spacing.

## 2. Existing widget architecture

The production widget is a dependency-free Shadow DOM embed:

```text
widget.js bootstrap
├── config and session storage
├── typed chat SSE transport
├── response/component renderer
├── catalog-guided navigation
├── picker / finder / comparison / detail overlays
├── lead capture
└── DOM construction and keyboard handlers

widget.css
├── shell and launcher
├── header / transcript / bubbles
├── guided actions and context
├── recommendation and rich cards
├── overlays and picker
├── composer / lead / comparison
└── responsive, forced-color, and reduced-motion behavior
```

Existing event handlers, API endpoints, session behavior, SSE parsing, routing, guided selection,
comparison, lead submission, and context clearing remain unchanged.

## 3. Gap analysis

| Area | Before | Expected | Implemented change |
|---|---|---|---|
| Tokens | Partial aliases plus legacy warm values | Canonical token set available inside Shadow DOM | Mirrored the published token names and mapped widget aliases to them |
| Fonts | DM Sans named but not loaded by the widget | DM Sans 400/500/600 and JetBrains Mono 400 | Added the same Google Fonts import used by the source token file |
| Text colors | Several legacy brown/blue-grey values | `#111827`, `#4B5563`, `#9CA3AF` | Removed legacy warm values and normalized semantic text aliases |
| Hover states | Neutral chips turned orange | Grey hover with navy focus; orange reserved for CTA | Updated guided and More states |
| Focus | Orange glow rings | Navy outline/border without glow | Unified keyboard focus and search/input focus |
| Chat bubbles | Rounder, heavier surfaces | Canvas's asymmetric 4/15 px bubbles and minimal lift | Updated radius, shadow, and text color |
| Composer | Input had its own boxed field inside the composer | One pill field plus aligned circular send action | Restored the canvas anatomy using CSS only |
| Launcher | Gradient rounded square | Solid orange circular launcher | Removed gradient and normalized radius/shadow |
| Elevation | Navy-tinted and complex shadows | Published card/modal/dropdown shadows | Replaced component elevation with tokens |
| Overlays | Backdrop blur | Opaque/dim separation without frosted glass | Removed backdrop filters |
| Progress | Orange gradient and glow | Solid orange with 0.3 s fill | Updated progress styling |
| Picker | Visually dense and previously offset on mobile | Full sheet, clear search/Popular/All hierarchy | Preserved the corrected responsive picker and source-backed monogram tones |
| Accessibility | Native controls and Escape support, but incomplete state metadata | Dialog labelling, busy state, expansion state, visible focus | Added ARIA metadata without changing handlers |

## 4. Implementation plan and completed file changes

### Component hierarchy

```text
Widget
├── Launcher
└── Dialog panel
    ├── Header
    ├── Transcript
    │   ├── Context
    │   ├── Message groups
    │   ├── Cards / rich answers
    │   └── Guided actions
    ├── Composer
    ├── Privacy line
    ├── Compare tray
    └── Overlay dialog
        ├── Picker
        ├── Finder support
        └── Details / lead
```

### File modifications

- `widget/widget.css`: canonical tokens, font loading, component styling, focus, elevation,
  composer anatomy, overlay treatment, and responsive sheet behavior.
- `widget/widget.js`: only visual fallback color and ARIA state/labelling metadata.
- `tests/test_widget_2_contract.py`: design-token and accessibility regression contracts.
- This document: design summary, architecture, gap analysis, plan, and conflict decisions.

## 5. Deliberately not changed

These requirements conflict with either newer approved widget decisions or the instruction not to
change working logic:

- The text specification says four opening chips, while the production flow is explicitly tested at
  three visible choices plus More. The tested behavior remains unchanged.
- The text specification mentions A–Z picker headers; the rendered canvas and latest approved picker
  reference use Popular + All. The rendered reference remains authoritative.
- The older card specification uses three nested stat pills. The current approved compact-card system
  intentionally replaced those with inline metadata and progressive Details. It was not reverted.
- The tools specification describes ROI, career quiz, and scholarship product flows that are not part
  of the current production widget renderer/API contract. Adding them would be new working logic, so
  they were documented but not introduced.
- No university logos, deadlines, urgency indicators, or unsupported differentiator claims were added.

## 6. Responsive and accessibility behavior

- Desktop: 400 × 650 px bounded panel with modal elevation.
- Tablet/narrow embed: panel remains viewport-bounded with flexible message/card widths.
- Mobile (≤560 px): fixed full-viewport panel; picker becomes a safe-area-aware full sheet; the
  separate open launcher is hidden while the panel is active.
- Narrow mobile (≤360 px): option and metadata grids collapse where needed.
- Keyboard: all actions remain native buttons; Escape closes overlays/panel; visible navy focus is
  consistent; overlay title labels the dialog; More exposes `aria-expanded`; transcript exposes
  `aria-busy` while the typing state is active.
- Forced-colors and reduced-motion rules remain intact.

