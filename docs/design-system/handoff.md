# Handoff: tokens for globals.css, fonts.ts, and the build order by owner

## 1. Paste into `web/src/app/globals.css` (Tailwind v4)

Replace the current `:root` and `@theme inline` blocks. Light is the default; dark comes from `[data-theme="dark"]` or the system setting when no attribute is set. The floor is always dark: give `/floor` `data-theme="dark"` on its root.

```css
@import "tailwindcss";

:root, [data-theme="light"] {
  --canvas: #f7f8fa; --surface: #ffffff; --surface-2: #eef0f4;
  --ink: #0f1419; --ink-2: #3f4857; --muted: #687283;
  --line: #e3e6ec; --line-2: #c9cfd9;
  --pulse: #2457f5; --pulse-ink: #ffffff; --pulse-soft: #2457f51a; --pulse-glow: #2457f559;
  --mint: #15803d; --mint-soft: #15803d1f; --coral: #c0392b; --coral-soft: #c0392b1f;
  --amber: #b45309; --amber-soft: #b453091f; --slate: #5b6575; --slate-soft: #5b657521;
  --royal: #6d28d9; --royal-soft: #6d28d91f;
  --shadow-card: 0 1px 2px #0f14190f; --shadow-pop: 0 12px 32px #0f14191f; --shadow-glow: 0 0 0 4px #2457f526;
  color-scheme: light;
}
[data-theme="dark"] {
  --canvas: #0b0d12; --surface: #121620; --surface-2: #1a1f2b;
  --ink: #edf0f5; --ink-2: #b7bfcc; --muted: #8b95a7;
  --line: #242b38; --line-2: #343d4d;
  --pulse: #6f93ff; --pulse-ink: #0b0d12; --pulse-soft: #6f93ff29; --pulse-glow: #6f93ff73;
  --mint: #4ade80; --mint-soft: #4ade8029; --coral: #f87171; --coral-soft: #f8717129;
  --amber: #fbbf24; --amber-soft: #fbbf2429; --slate: #98a2b3; --slate-soft: #98a2b329;
  --royal: #a78bfa; --royal-soft: #a78bfa29;
  --shadow-card: 0 1px 2px #00000080; --shadow-pop: 0 12px 32px #000000a6; --shadow-glow: 0 0 0 4px #6f93ff33;
  color-scheme: dark;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --canvas: #0b0d12; --surface: #121620; --surface-2: #1a1f2b;
    --ink: #edf0f5; --ink-2: #b7bfcc; --muted: #8b95a7;
    --line: #242b38; --line-2: #343d4d;
    --pulse: #6f93ff; --pulse-ink: #0b0d12; --pulse-soft: #6f93ff29; --pulse-glow: #6f93ff73;
    --mint: #4ade80; --mint-soft: #4ade8029; --coral: #f87171; --coral-soft: #f8717129;
    --amber: #fbbf24; --amber-soft: #fbbf2429; --slate: #98a2b3; --slate-soft: #98a2b329;
    --royal: #a78bfa; --royal-soft: #a78bfa29;
    --shadow-card: 0 1px 2px #00000080; --shadow-pop: 0 12px 32px #000000a6; --shadow-glow: 0 0 0 4px #6f93ff33;
    color-scheme: dark;
  }
}
/* Floor tokens: one value in both themes. */
:root {
  --floor-bg: #07080f; --floor-ground: #10131f; --floor-line: #f2efff; --floor-rope: #d9d4ff;
  --floor-post-a: #ff7a1a; --floor-post-b: #8b5cf6;
  --pac: #ffd21f; --pac-shade: #d9a900;
  --ghost-1: #ff4d4d; --ghost-2: #ff8fd6; --ghost-3: #45e0ff; --ghost-4: #ffb04a;
  --ghost-eaten: #4b5063; --ghost-blue: #3b6cff;
  --referee: #a78bfa; --shield: #6f93ff; --checker: #4ade80;
  --tag-bg: #ffffff; --tag-ink: #0b0d12; --crowd: #3a3d55;
  --t-fast: 160ms; --t-base: 240ms; --t-slow: 420ms; --t-pulse: 1800ms; --t-ticker: 900ms;
  --ease-out: cubic-bezier(0.2, 0.8, 0.2, 1); --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --f-reveal: 320ms; --f-dash: 600ms; --f-chomp: 420ms; --f-block: 500ms; --f-wander: 2400ms; --f-grow: 800ms; --f-walkout: 2000ms;
}

@theme inline {
  --color-canvas: var(--canvas); --color-surface: var(--surface); --color-surface-2: var(--surface-2);
  --color-ink: var(--ink); --color-ink-2: var(--ink-2); --color-muted: var(--muted);
  --color-line: var(--line); --color-line-2: var(--line-2);
  --color-pulse: var(--pulse); --color-pulse-ink: var(--pulse-ink); --color-pulse-soft: var(--pulse-soft); --color-pulse-glow: var(--pulse-glow);
  --color-mint: var(--mint); --color-mint-soft: var(--mint-soft); --color-coral: var(--coral); --color-coral-soft: var(--coral-soft);
  --color-amber: var(--amber); --color-amber-soft: var(--amber-soft); --color-slate: var(--slate); --color-slate-soft: var(--slate-soft);
  --color-royal: var(--royal); --color-royal-soft: var(--royal-soft);
  --color-floor-bg: var(--floor-bg); --color-floor-ground: var(--floor-ground); --color-floor-line: var(--floor-line); --color-floor-rope: var(--floor-rope);
  --color-floor-post-a: var(--floor-post-a); --color-floor-post-b: var(--floor-post-b);
  --color-pac: var(--pac); --color-pac-shade: var(--pac-shade);
  --color-ghost-1: var(--ghost-1); --color-ghost-2: var(--ghost-2); --color-ghost-3: var(--ghost-3); --color-ghost-4: var(--ghost-4);
  --color-ghost-eaten: var(--ghost-eaten); --color-ghost-blue: var(--ghost-blue);
  --color-referee: var(--referee); --color-shield: var(--shield); --color-checker: var(--checker);
  --color-tag-bg: var(--tag-bg); --color-tag-ink: var(--tag-ink); --color-crowd: var(--crowd);
  --radius-sm: 8px; --radius-md: 12px; --radius-card: 16px; --radius-xl: 24px; --radius-pill: 999px;
  --shadow-card: var(--shadow-card); --shadow-pop: var(--shadow-pop); --shadow-glow: var(--shadow-glow);
  --spacing-gutter: 16px; --container-tb: 1120px;
  --font-sans: var(--font-geist), ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-serif: var(--font-instrument-serif), ui-serif, Georgia, serif;
  --font-mono: var(--font-geist-mono), ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --font-arcade: var(--font-press-start), var(--font-geist-mono), ui-monospace, monospace;
  --ease-out: var(--ease-out); --ease-in-out: var(--ease-in-out);
  --animate-tb-pulse: tb-pulse 1800ms cubic-bezier(0.2, 0.8, 0.2, 1) infinite;
  @keyframes tb-pulse { 0% { transform: scale(1); opacity: 0.5; } 100% { transform: scale(2.6); opacity: 0; } }
}

body { background: var(--canvas); color: var(--ink); font-family: var(--font-sans); -webkit-font-smoothing: antialiased; }
:focus-visible { outline: 2px solid var(--pulse); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; } }
```

Utilities you get: `bg-canvas bg-surface bg-surface-2 text-ink text-ink-2 text-muted border-line border-line-2 bg-pulse text-pulse bg-pulse-soft text-mint bg-mint-soft text-coral bg-coral-soft text-amber bg-amber-soft text-slate bg-slate-soft text-royal bg-royal-soft rounded-sm rounded-md rounded-card rounded-xl rounded-pill shadow-card shadow-pop shadow-glow font-sans font-serif font-mono font-arcade animate-tb-pulse` plus every floor colour as `bg-pac`, `bg-ghost-1`, `text-checker`, and so on.

## 2. Replace `web/src/app/fonts.ts`

```ts
// Geist for UI, Instrument Serif for display and hero numbers, Geist Mono for codes and prices,
// Press Start 2P for the floor HUD only. All Google Fonts, SIL OFL 1.1; next/font downloads at build time.
import { Geist, Geist_Mono, Instrument_Serif, Press_Start_2P } from "next/font/google";

export const geist = Geist({ subsets: ["latin"], variable: "--font-geist", display: "swap" });
export const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });
export const instrumentSerif = Instrument_Serif({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--font-instrument-serif", display: "swap" });
export const pressStart = Press_Start_2P({ subsets: ["latin"], weight: "400", variable: "--font-press-start", display: "swap" });

/** Put on <html>: className={`h-full antialiased ${fontVars}`} */
export const fontVars = `${geist.variable} ${geistMono.variable} ${instrumentSerif.variable} ${pressStart.variable}`;
```

Grep for `font-cinzel` and `font-display` after the swap; `font-display` now maps to nothing, use `font-serif`.

## 3. The wordmark token

```ts
// web/src/lib/brand.ts
export const BRAND = { name: process.env.NEXT_PUBLIC_BRAND_NAME ?? "Tech Bazaar", tagline: "Your agent shops. You approve." };
```

Render `BRAND.name` everywhere (nav, floor HUD, receipts, page titles). When the name lands, set `NEXT_PUBLIC_BRAND_NAME` and redeploy; no file edits.

## 4. Build order

### Vedant: landing, /start, /buyer, /buyer/decisions, /buyer/purchases, /buyer/agents

1. Paste the tokens and fonts (15 min). Add `Pill`, `PulseDot`, `Card`, `HeroNumber`, `Empty`, `Skeleton`, `ErrorLine` from `screens.md` into `web/src/components/ui/`.
2. `/buyer` first (the demo path): the live round card from DecisionCard with SEALED pills and a closes-in timer, the ASI:One panel on the right at 1440 (grid 1fr 360px) and as a bottom sheet at 390. Seed with the reference round so it never starts empty.
3. The approval sheet (ApprovalCall) as a Radix Dialog over `/buyer`; the code comes from the backend event, never generated client-side.
4. `/buyer/decisions` (DecisionCard rows from `roundResult`), `/buyer/purchases` (ReceiptCard), `/buyer/agents` (AgentRoster with `agents/avatars/<role>.png`).
5. `/start` (GoalCard) and `/` (Nav, Hero with the three measured numbers, five steps as a plain numbered list in `title` and `body-sm`, honesty strip from StatusPill, roster teaser, WindTunnel numbers, Seller Kit teaser, footer sandbox line).
6. Screenshot each at 390 and 1440, light and dark; 16 px gutter, no horizontal scroll, 44 px tap targets.

### Abhinav: /floor

1. Paste the tokens; give the route `data-theme="dark"` and `bg-floor-bg`.
2. Build the stage from `floor.md`: projection, mat, posts, ropes, crowd (30 min). Then the sprites in the order buyer, ghost, referee, Shield, checker.
3. Wire the phase table to the round events; keep the preview's timings. The HUD, ledger strip and PiP are HTML over the canvas; reuse `ChatPip` from `screens.md`.
4. Reduced motion: skip tweens, keep phases; ship the Prev/Next/Pause controls.
5. Check at 1920x1080 at 25 percent zoom and in a 390 shell.

### Both

Every screen label reads from `source` and `status`. Copy says "the buyer". No invented numbers: if a value is missing, show the Empty or ErrorLine state with the reason.
