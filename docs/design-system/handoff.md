# Handoff: tokens into the app (v2, Oct 25 2026)

Version 2 replaces every colour, shadow and type value from version 1. Source of truth is `tokens.json`; the blocks below are generated from it. The app runs Next 16, React 19 and Tailwind v4 (`web/package.json`), so tokens go into `globals.css` as an `@theme` block and dark mode as a `[data-theme="dark"]` override. Floor tokens carry one value in both themes.

Artifacts: Design System https://claude.ai/artifact/NA8XcfWVXwVmEeuWNwY4o5 (this system) and the standalone "Tech Bazaar Floor" page https://claude.ai/artifact/GXt4CwUarWbzbWmvMFwaSi.

## `globals.css`

```css
@theme {
  --color-canvas: #eef3f8;
  --color-surface: #ffffff;
  --color-surface-2: #f4f6fa;
  --color-glass: #ffffffcc;
  --color-ink: #0b1b2b;
  --color-ink-2: #2a3440;
  --color-muted: #5b6b7c;
  --color-line: #e3e8ef;
  --color-line-2: #0b1b2b24;
  --color-pulse: #1e4ed8;
  --color-pulse-ink: #ffffff;
  --color-pulse-soft: #eef2ff;
  --color-pulse-soft-ink: #1e3a8a;
  --color-live: #0891b2;
  --color-live-soft: #0891b224;
  --color-mint: #065f46;
  --color-mint-mark: #0f9d76;
  --color-mint-soft: #d1fae5;
  --color-coral: #b4232a;
  --color-coral-mark: #e5484d;
  --color-coral-soft: #fdecec;
  --color-amber: #92400e;
  --color-amber-soft: #fef3c7;
  --color-slate: #334155;
  --color-slate-soft: #eef2f6;
  --color-referee: #1e3a8a;
  --color-referee-soft: #eef2ff;
  --color-floor-bg: #0b1b2b;
  --color-floor-ground: #112437;
  --color-floor-line: #eef3f8;
  --color-floor-rope: #5b6b7c;
  --color-pac: #eef3f8;
  --color-ghost-1: #8fa0b2;
  --color-ghost-2: #e5484d;
  --color-ghost-3: #fcd34d;
  --color-ghost-4: #0f9d76;
  --color-ghost-eaten: #334155;
  --color-shield: #22d3ee;
  --color-checker: #0f9d76;
  --color-tag-bg: #eef3f8;
  --color-tag-ink: #0b1b2b;
  --shadow-ring: 0 0 0 1.5px #0b1b2b24, 0 1px 2px #0b1b2b14;
  --shadow-card: 0 1px 2px #0b1b2b0f, 0 8px 24px #0b1b2b0f;
  --shadow-lift: 0 24px 60px #0b1b2b2e;
  --shadow-glass: inset 0 0.5px 0 #fffffff2, 0 0 0 0.5px #0e172614, 0 4px 40px 8px #0e172629, 0 34px 70px -34px #0e172642;
  --shadow-focus: 0 0 0 4px #1e4ed833;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-12: 48px;
  --space-16: 64px;
  --space-20: 80px;
  --container: 1120px;
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 24px;
  --radius-pill: 999px;
  --font-sans: "Geist", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "Geist Mono", ui-monospace, Menlo, monospace;
}

[data-theme="dark"] {
  --color-canvas: #0b1b2b;
  --color-surface: #112437;
  --color-surface-2: #16304a;
  --color-glass: #112437cc;
  --color-ink: #eef3f8;
  --color-ink-2: #c5d0dc;
  --color-muted: #8fa0b2;
  --color-line: #1f3a55;
  --color-line-2: #eef3f833;
  --color-pulse: #8fb0ff;
  --color-pulse-ink: #0b1b2b;
  --color-pulse-soft: #1e4ed838;
  --color-pulse-soft-ink: #c7d4ff;
  --color-live: #22d3ee;
  --color-live-soft: #22d3ee29;
  --color-mint: #6ee7b7;
  --color-mint-mark: #0f9d76;
  --color-mint-soft: #0f9d7633;
  --color-coral: #fca5a5;
  --color-coral-mark: #e5484d;
  --color-coral-soft: #e5484d33;
  --color-amber: #fcd34d;
  --color-amber-soft: #92400e4d;
  --color-slate: #cbd5e1;
  --color-slate-soft: #33415566;
  --color-referee: #c7d4ff;
  --color-referee-soft: #1e4ed838;
  --shadow-ring: 0 0 0 1.5px #eef3f829, 0 1px 2px #00000066;
  --shadow-card: 0 1px 2px #00000066, 0 8px 24px #00000059;
  --shadow-lift: 0 24px 60px #000000a6;
  --shadow-glass: inset 0 0.5px 0 #ffffff1f, 0 0 0 0.5px #eef3f81f, 0 4px 40px 8px #00000066, 0 34px 70px -34px #00000099;
  --shadow-focus: 0 0 0 4px #8fb0ff4d;
}
```

Usage rules: `*-mark` for dots, icons and figures; the bare semantic token (`mint`, `coral`, `amber`, `slate`, `referee`) for text; `*-soft` for the ground behind that text. `live` cyan is never text under 18 px in light. `pulse` is the one action colour; `ink` buttons are allowed for a dark nav CTA (Prism does this) but never two primaries on one screen.

## `fonts.ts`

```ts
import { Geist, Geist_Mono } from "next/font/google";
export const sans = Geist({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-sans", display: "swap" });
export const mono = Geist_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono", display: "swap" });
```

Remove Instrument Serif, Cinzel and Press Start 2P. Both faces are SIL OFL 1.1.

## Type scale (Tailwind classes to add as utilities)

| Style | Class | Value |
| --- | --- | --- |
| display-xl | `text-[56px]/[60px] font-medium tracking-[-0.025em]` | landing hero at 1440; `text-[40px]/[44px]` at 390 |
| display-lg | `text-[40px]/[44px] font-medium tracking-[-0.02em]` | section heads |
| number-hero | `text-[48px]/[52px] font-medium tracking-[-0.02em] tabular-nums` | one per screen |
| display-md | `text-[28px]/[34px] font-medium tracking-[-0.015em]` | moment titles |
| title | `text-[22px]/[28px] font-semibold tracking-[-0.01em]` | page titles |
| headline | `text-[17px]/[22px] font-semibold` | card titles |
| body | `text-[17px]/[26px]` | landing and sheets |
| body-sm | `text-[15px]/[20px]` | product UI |
| footnote | `text-[13px]/[18px]` | supporting detail |
| caption | `text-[12px]/[16px] font-medium tracking-[0.04em] uppercase` | labels, pills |
| price | `font-mono text-[15px]/[20px] font-medium tabular-nums` | prices |
| label-mono | `font-mono text-[12px]/[16px] font-medium tracking-[0.04em] uppercase` | addresses, HUD |

## Wordmark

`<span data-wordmark="Tech Bazaar" class="font-medium text-[16px] tracking-[-0.02em]">` beside a 22 px `ink` tile (radius 6) with a white disc cut-out (the buyer). One string, swapped in one place when the name lands.

## Component rules that changed from v1

- Cards: `bg-surface border border-line rounded-2xl shadow-card p-4 md:p-6`. The active card adds `shadow-focus` and `border-pulse`.
- Glass: `bg-glass rounded-[20px] shadow-glass backdrop-blur-xl`, one per screen, for the hero mock, the approval sheet and the PiP.
- Buttons: primary `bg-pulse text-pulse-ink`, secondary `bg-pulse-soft text-pulse-soft-ink`, ghost `bg-surface shadow-ring`. All `min-h-11 rounded-xl px-5 font-medium`. Pressed state `scale-[0.98]` over 160 ms.
- Pills: 24 px, `rounded-full px-2.5 text-[12px]/[16px] font-medium`, soft ground plus semantic ink. The live pill is `bg-live-soft text-ink` with a `text-live` dot.
- Motion: enter `translate-y-2 opacity-0` to rest over 420 ms with `cubic-bezier(0.2, 0.9, 0.3, 1)`; exits 200 ms opacity only; everything under `motion-reduce:transition-none`.

## Build order

Unchanged from version 1 (Abhinav: /floor; Vedant: landing, /start, /buyer screens). Floor work now starts from `floor.md` and, for the TV, `floor-3d.md`.
