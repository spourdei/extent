# Design notes

## Direction

The product should feel like a focused evidence desk, not a general chat window. Keep the
question and answer easy to read while making the supporting material one direct action
away.

Use warm paper-like surfaces, dark ink, and one restrained green accent. Avoid decorative
technology cues, gradients, glass effects, and dense dashboard framing.

## Main workspace

The working layout has three regions:

- previous questions;
- the active answer and question input;
- evidence for the selected finding.

The answer stays central. Evidence opens beside it on larger screens and enters the normal
document flow on small screens. The user should not lose their place when opening or closing
an excerpt.

Evidence rows need to behave as controls, not citation ornaments. Show the file, a useful
location, and enough of the value or quote to choose the right excerpt.

## Type and structure

Use a readable sans serif for interface text and a restrained serif for important findings.
Keep metadata compact, but never make evidence locations or failure reasons hard to read.
Numerical values should align cleanly.

Prefer borders and spacing over stacks of cards. Status must use text as well as color.

## Responsive intent

Desktop can keep question history visible and place evidence alongside the result. Tablet
may collapse history and use a side panel. Mobile should become one vertical reading order
without horizontal scrolling.

## Still to resolve

- Exact spacing, color, and type tokens.
- Coverage and partial-preparation states.
- Keyboard focus when evidence opens and closes.
- How conflict and insufficient-evidence answers differ visually.
- Which technical lineage fields belong behind disclosure.

Start with native controls and landmarks. Add custom interaction only when the evidence
workflow requires it.
