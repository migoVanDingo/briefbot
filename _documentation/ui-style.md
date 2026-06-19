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

## Concrete tokens (v1, proposed)

og briefbot uses MUI → rounded/pill-shaped everywhere. bbv2 will **not** use MUI;
it uses its own CSS tokens (the trader approach) for full control. **Light and
dark use different accents**, not just inverted neutrals.

**Radius (restrained — no pills):** `--radius-sm: 4px`, `--radius: 6px`,
`--radius-lg: 8px`. Cards/containers/inputs/buttons use 6–8px. The only round
elements are avatars and the theme toggle. Never pill-shaped buttons or chips
(chips ≤ 4px).

**Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32. **Motion:** 120–160ms;
honor `prefers-reduced-motion`.

**Dark theme**
```
--bg #0f1115  --surface #171a21  --border #262b36
--text #e6e9ef --dim #9aa3b2
--accent #7c5cff (violet)  --accent-2 #22d3ee (cyan)
--pos #34d399  --neg #fb7185
```
**Light theme** (distinct accents, warmer)
```
--bg #f6f8fb  --surface #ffffff  --border #e3e7ee
--text #1a1f2b --dim #5b6472
--accent #0ea5a4 (teal)  --accent-2 #f97316 (orange)
--pos #059669  --neg #e11d48
```

Tokens live in one source (a `theme.ts` + injected CSS vars, like trader). These
are a starting point — tune when building.

## Snackbar spec (v1)

Bottom-right stack; one toast per action. Variants `info | success | error` with
a left accent border (`--accent` / `--pos` / `--neg`). Auto-dismiss ~5s,
dismissable, optional **action** ("Undo" on unsubscribe/reject). Driven by a
small toasts store; reimplement trader's `Toasts` in bbv2's style.

## Scope note

This is the visual spec for the dashboard (plan 0006). It does **not** change og
briefbot.
