# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** TermSub
**Generated:** 2026-07-26 16:36:17
**Category:** Subtitle Translation & Terminology Management SaaS (Developer/Technical Tool)
**Design Dials:** Variance 2/10 (Centered / Minimal) | Motion 2/10 (Subtle)
**Mode:** Dark only — this is the single documented mode; no light-mode variant is in scope.

---

## Global Rules

### Color Palette

Anchored to the colors already shipping in `frontend/index.html`/`frontend/js/main.js` (Tailwind's default `slate`/`blue` scales) — this design system formalizes the existing brand color into tokens rather than replacing it.

| Role | Hex | Tailwind | CSS Variable |
|------|-----|----------|--------------|
| Primary / Accent / CTA | `#2563EB` | `blue-600` | `--color-primary` |
| Primary Hover | `#1D4ED8` | `blue-700` | `--color-primary-hover` |
| On Primary | `#FFFFFF` | `white` | `--color-on-primary` |
| Background | `#0F172A` | `slate-900` | `--color-background` |
| Surface / Card | `#1E293B` | `slate-800` | `--color-surface` |
| Surface Hover | `#334155` | `slate-700` | `--color-surface-hover` |
| Foreground (primary text) | `#F1F5F9` | `slate-100` | `--color-foreground` |
| Muted Foreground (secondary text) | `#94A3B8` | `slate-400` | `--color-muted-foreground` |
| Border | `#334155` | `slate-700` | `--color-border` |
| Destructive | `#F87171` | `red-400` | `--color-destructive` |
| Success | `#34D399` | `emerald-400` | `--color-success` |
| Warning | `#FBBF24` | `amber-400` | `--color-warning` |
| Ring (focus) | `#2563EB` | `blue-600` | `--color-ring` |

**Color Notes:** Blue-600 primary on a slate-900/800 dark surface stack — the existing brand identity, now expressed as reusable tokens instead of ad hoc utility classes repeated across files.

### Typography

- **Heading Font:** Inter
- **Body Font:** Inter
- **Mood:** minimal, clean, swiss, functional, neutral, professional
- **Google Fonts:** [Inter + Inter](https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap)

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
```

### Spacing Variables

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Section padding |
| `--space-xl` | `32px` / `2rem` | Large gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

---

## Component Specs

### Buttons

```css
/* Primary Button — matches existing bg-blue-600 hover:bg-blue-700 usage */
.btn-primary {
  background: var(--color-primary);       /* #2563EB */
  color: var(--color-on-primary);
  padding: 12px 24px;
  border-radius: 12px;                    /* rounded-xl, the app's dominant radius */
  font-weight: 500;
  transition: background-color 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  background: var(--color-primary-hover); /* #1D4ED8 */
}

/* Secondary Button */
.btn-secondary {
  background: var(--color-surface);       /* #1E293B */
  color: var(--color-foreground);
  border: 1px solid var(--color-border);
  padding: 12px 24px;
  border-radius: 12px;
  font-weight: 500;
  transition: background-color 200ms ease;
  cursor: pointer;
}

.btn-secondary:hover {
  background: var(--color-surface-hover); /* #334155 */
}
```

### Cards

```css
.card {
  background: var(--color-surface);       /* #1E293B */
  border: 1px solid var(--color-border);  /* #334155 */
  border-radius: 16px;                    /* rounded-2xl for containers */
  padding: 24px;
  transition: border-color 200ms ease;
}

.card:hover {
  border-color: var(--color-surface-hover);
}
```

### Inputs

```css
.input {
  background: var(--color-background);    /* #0F172A, matches dark input fields */
  color: var(--color-foreground);
  padding: 12px 16px;
  border: 1px solid var(--color-border);  /* #334155 */
  border-radius: 12px;
  font-size: 16px;
  transition: border-color 200ms ease, box-shadow 200ms ease;
}

.input:focus {
  border-color: var(--color-primary);
  outline: none;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.2); /* blue-600 @ 20% */
}
```

### Modals

```css
.modal-overlay {
  background: rgba(2, 6, 23, 0.7); /* near-black scrim over dark UI */
  backdrop-filter: blur(4px);
}

.modal {
  background: var(--color-surface);       /* #1E293B */
  border: 1px solid var(--color-border);
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Minimalism & Swiss Style

**Keywords:** Clean, simple, spacious, functional, white space, high contrast, geometric, sans-serif, grid-based, essential

**Best For:** Enterprise apps, dashboards, documentation sites, SaaS platforms, professional tools

**Key Effects:** Subtle hover (200-250ms), smooth transitions, sharp shadows if any, clear type hierarchy, fast loading

### Page Pattern

**Applies to the marketing site only** (`/`) — TermSub has two distinct surfaces, and the app itself (`/app`) is a step-by-step wizard (upload → transcribe → review terms → translate → export), which should follow its own existing step-flow structure, not a marketing page pattern. Use the pattern below for landing-page work; use the Global Rules (colors, spacing, components, motion) for both surfaces.

**Pattern Name:** Bento Grid Showcase

- **Conversion Strategy:** Scannable value props. High information density without clutter. Mobile stack.
- **CTA Placement:** Floating Action Button or Bottom of Grid
- **Section Order:** 1. Hero, 2. Bento Grid (Key Features), 3. Detail Cards, 4. Tech Specs, 5. CTA

---

## Motion

**Stagger List** (Subtle) — Trigger: load or scroll | Duration: 250-350ms | Easing: `power1.out`

```js
gsap.from('.list-item', { opacity: 0, y: 8, duration: 0.3, stagger: 0.03 });
```

**Framework notes:** Select items with a stable class/data-attribute (not array index) so re-renders in React don't break targeting

- ✅ Keep per-item stagger delay small (0.02-0.04s) for lists longer than 10 items
- ❌ Don't stagger by more than 0.1s per item on long lists; total reveal time becomes sluggish
- ⚡ For virtualized lists, only animate items currently mounted in the DOM

---

## Anti-Patterns (Do NOT Use)

- ❌ Light mode as the primary/default surface — dark is the only documented mode
- ❌ Slow performance

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons), or FontAwesome to match the icon set already in use
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio against the dark surface colors above
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y
- ❌ **Bright/saturated colors on dark surfaces** — keep the muted slate + single blue-600 accent discipline; don't introduce a second competing accent color

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead, or FontAwesome to match existing usage)
- [ ] All icons from a consistent icon set
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Dark surface text contrast 4.5:1 minimum (verify against `--color-background`/`--color-surface`, not against a light background)
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
- [ ] Only one accent color (`--color-primary`, blue-600) used for calls-to-action — status colors (success/warning/destructive) stay reserved for actual status, not decoration
