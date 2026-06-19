# bbv2 — UI style & design direction

Direction for the bbv2 dashboard (Phase 5). We reuse og briefbot's dashboard
**scaffolding/structure**, but **not its visual style** — bbv2 should look
distinct, modern, and alive.

## What to move away from (og briefbot)

- Heavy/everywhere rounded corners.
- Elements that "fit weird" — inconsistent spacing and weak alignment.

## Principles

- **Tighter, deliberate layout.** One spacing scale (e.g. 4/8/12/16/24), a real
  grid, consistent alignment. Cards/sections share padding and rhythm.
- **Restrained radii.** Small, consistent corner radius (≈4–8px) or squared
  edges — not pill-shaped everything. Pick one and apply it uniformly.
- **Accent-driven and lively.** Dark-first surface palette with a vivid **accent**
  (plus an optional secondary) for interactive/active states, highlights, and the
  occasional tasteful gradient. It should feel energetic, not noisy.
- **Alive through motion.** Purposeful micro-interactions: hover lifts, clear
  press/active feedback, fast (120–180ms) transitions, subtle entrance for new
  Headlines. Always honor `prefers-reduced-motion`.
- **Design tokens, single source.** Colors / spacing / radius / motion defined
  once (like the trader app's `theme.ts`), so the look is consistent and easy to
  retune. Light + dark.

## Snackbar / toast notifications

Transient feedback for **every meaningful user action**, e.g.:

- subscribed/unsubscribed to a topic
- approved/rejected a candidate source
- liked an item · saved to a collection
- saved settings · added a topic
- errors (distinct error tone)

Behavior: appear (top-right or bottom-center), **stack**, auto-dismiss (~4–6s),
dismissable, with an optional **action** (e.g. "Undo" on unsubscribe). One small
toast system, driven by a store (cf. the trader app's `Toasts` component as a
reference implementation — reimplement here in bbv2's style).

## Scope note

This guides Phase 5 (dashboard). It does **not** change og briefbot. When we build
the dashboard, this doc becomes the visual spec; refine it then with concrete
tokens (hex values, type scale).
