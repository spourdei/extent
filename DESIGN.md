# Design System

## Direction

Extent is a daylit evidence desk: warm paper surfaces, dark botanical ink, compact document structure, and one restrained green accent. The interface should feel more like a careful review workspace than a chat toy or analytics dashboard. Evidence, coverage, and the next safe action lead; decorative technology signals do not.

## Tokens

Tokens are defined in `apps/web/tokens.css`, imported once by `apps/web/app/globals.css`, and consumed through semantic names.

### Color

- Canvas: `oklch(0.9798 0.0045 78.3)`
- Raised surface: `oklch(0.997 0.001 78.3)`
- Soft surface: `oklch(0.9651 0.0074 80.72)`
- Ink: `oklch(0.258 0.0086 75.21)`
- Muted ink: `oklch(0.5338 0.0216 83.03)`
- Hairline: `oklch(0.9142 0.0133 82.4)`
- Accent: `oklch(0.3919 0.0428 127.55)`
- Selection: `oklch(0.9585 0.0098 87.47)`
- Warning: `oklch(0.5292 0.1023 80.37)` with a pale amber surface
- Danger: `oklch(0.5404 0.1185 44.39)` with a pale red surface
- Focus ring: `oklch(0.56 0.15 250)`

Status is never communicated by color alone. Every status includes a label and, where useful, a shape or icon.

### Type

- UI family: Public Sans with an Arial-adjusted fallback
- Display family: Source Serif 4 with a Georgia-adjusted fallback
- Base: 15px with 1.55 line height
- Small metadata: 11–13px
- Body and controls: 14–15px
- Section titles: 19–26px
- Landing thesis: fluid 30–40px with compact line height
- Material values use tabular numerals and 600 weight

Use sentence case. Avoid all-caps except short machine-like labels such as PDF or USD. Keep copy literal around evidence, access, coverage, and failure.

### Space and shape

- Spacing scale: 2, 4, 8, 12, 16, 24, 40, 64, 96px
- Result column max width: 740px, increasing to 768px on wide screens
- Question rail: 180–232px; evidence panel: 300–384px
- Control minimum height: 44px
- Radius: 8px controls, 12px bounded panels; pills only for compact status tags
- Shadows: one subtle raised-surface shadow for overlays and inspectors; borders carry most separation

## Core patterns

### App header

A compact wordmark, current folder context, and one coverage control. Public routes use a single direct action. The header drops secondary context before it crowds a narrow viewport.

### Status notice

One semantic block for neutral, evidence-supported, warning, and error states. It contains a visible label, concise explanation, and recovery action when one exists. It does not nest another card.

### Evidence claim

Lead with the question, result state, and one plain-language finding. Each evidence row is a real button with the value, file, locator, and current inspection state. Citation text is not a decorative chip.

### Lineage inspector

Show the finding context, exact quote, file and locator, structured value metadata, source version, and observed time. Quote text remains selectable. Technical checks stay in a native disclosure below the human-readable evidence.

### Conversation composer

Use one labeled text input with preserved user text and one clear submit action. Loading exposes one coarse truthful announcement; unvalidated answer prose never streams. Disable only with a visible literal reason.

### Question history and file coverage

Desktop keeps previous questions in a narrow left rail. Mobile turns that rail into a native disclosure above the active result. File coverage opens in a native dialog so unavailable sources remain inspectable without competing with the current answer.

## Responsive behavior

- Desktop: question history, centered result column, and an evidence panel that becomes an in-flow third column at 1200px.
- Tablet: question history collapses; evidence opens as a fixed right panel.
- Mobile: one document flow with native question history, full-width evidence, and no horizontal scrolling.
- At 200% zoom, order remains header, question history, active result, evidence controls, and composer.

## Accessibility and motion

- WCAG 2.2 AA contrast for text and controls.
- Visible `:focus-visible` ring with at least 2px separation.
- Native buttons, links, labels, landmarks, headings, and disclosures before custom behavior.
- Coarse query status uses `aria-live="polite"`; decorative skeletons are hidden from assistive technology.
- Respect `prefers-reduced-motion`. Motion is limited to short opacity/position transitions that clarify inspector or result arrival; no looping or ornamental animation.
- Keyboard users can submit a question, switch history, open evidence, select exact quote text, traverse technical details, review file coverage, and restore focus after closing a panel.

## Avoid

No gradients, glass effects, card grids, icon tiles, giant centered hero copy, fabricated confidence scores, fake activity, raw model output, nested cards, or engineering traces in the primary reading flow.
