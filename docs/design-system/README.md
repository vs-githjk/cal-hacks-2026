# Tech Bazaar

A secure agentic marketplace. The buyer states a goal; seller agents bid in sealed knockout rounds; a referee ranks them by one rule; Shield screens every listing; a checker verifies fit and recalls; above the allowance the buyer approves by phone with a spoken code; a Stripe test-mode charge and a receipt close each part.

**Version 2 (Oct 25, 2026).** Version 1 was rejected as "AI sloppy": its palette was invented and its floor was neon. Version 2 takes every value from two live products Vidyut holds up as the bar, measured with Playwright on Oct 25: **BetterBill** (betterbill.matmanna.dev) for ink, primary blue, semantic pairs, radius and shadows, and **Prism** (meetprismai.com) for the cool canvas, glass cards, the signature shadow, the cyan live pulse and the larger type. Dark values and the floor's seller colours are derived from the same ink and are labelled "derived" in their usage notes. Nothing else is invented.

## Two worlds, one material

- **Outside** (landing, /start, /buyer, /buyer/agents, /buyer/decisions, /buyer/purchases, /sell, /seller, /market, /lot): a calm product on Prism's cool canvas (`canvas` #eef3f8) with white cards, BetterBill's ink (`ink` #0b1b2b) as the one text colour, one confident action colour (`pulse` #1e4ed8), thin borders and layered soft shadows. One glass card per screen at most, carrying `shadow-glass`.
- **Floor** (/floor only): the same ink as a stage (`floor-bg` #0b1b2b is the dark canvas), a ring in crisp minimal geometry, and the four sellers in the product's semantic colours. Not an arcade. See `floor.md` for the 2D spec and `floor-3d.md` for the three.js version built on it.
- **The crossing**: the dark app and the floor are one material. The wordmark, the tokens file, the status words (LIVE, SEALED, EATEN, BLOCKED, APPROVED) and the seller colours (`ghost-1..4` are the dot colours on decision rows) are shared.

The working name is Tech Bazaar. The wordmark is a token: render it from one `data-wordmark` string (see `handoff.md`) so the final name swaps in one place.

## Principles

1. **Trust first.** One hero number per screen, calm and large, in Geist 500 with tabular figures. Every state says its word next to its colour. Every number on screen comes from `data/scoreboard.json` or the reference run; nothing invented.
2. **Honesty labels everywhere.** Every bid, claim, screen and price carries LIVE, MIRROR (dated listing), SIM or Env-gated, driven by the `source` field. Planned work is labelled "planned, not built" on the screen itself.
3. **Readable in one second.** Geist only. Headings in Geist 500 with tightened tracking (-0.02 to -0.025 em above 28 px), the way Prism sets its 40 px headings. No serif display face, no novelty face anywhere, including the floor.
4. **Thin borders and layered shadows.** `line` on every card plus `shadow-card` (two soft layers, BetterBill). `shadow-lift` only for the hero mock, the phone shell and the PiP frame. `shadow-glass` only on a glass element. `shadow-focus` on at most one active card per screen.
5. **Motion with a reason.** Fades, 8 px rises with a soft spring curve, a 900 ms count-up, a 1.8 s pulse ring. On the floor, the phase table in `floor.md`. All of it pauses under `prefers-reduced-motion`; the floor shows its end frame.
6. **8 pt grid, precise alignment.** Spacing steps are multiples of 4 with 8 as the working unit; card padding 24 at 1440 and 16 at 390; every number column is tabular.
7. **Copy says "the buyer"**, never a person's name. Never "many buyers use it". Never call Shield "secure"; say what it stopped and what it missed.

## Colour

Light is the first theme for the outside; dark is the second. The floor is always dark and uses the `floor-*`, `pac`, `ghost-*`, `shield`, `checker` and `tag-*` tokens, which carry one value in both themes.

| Token | Means | Measured from |
| --- | --- | --- |
| `canvas` | page ground | Prism body #eef3f8; dark is BetterBill ink #0b1b2b |
| `ink` | the one text colour | BetterBill #0b1b2b |
| `ink-2`, `muted` | body text, captions | BetterBill #2a3440, #5b6b7c |
| `line`, `line-2` | hairlines, stronger rings | BetterBill border #e3e8ef and ring rgba(11,27,43,.14) |
| `pulse`, `pulse-soft` | the action colour and its soft tint | BetterBill primary #1e4ed8, secondary #eef2ff with text #1e3a8a |
| `live`, `live-soft` | the living pulse: dots, heartbeat rings, the Shield | Prism cyan #0891b2 and rgba(8,145,178,.14) |
| `mint`, `mint-mark`, `mint-soft` | good: approved, verified fit, paid | BetterBill #065f46, #0f9d76, #d1fae5 |
| `coral`, `coral-mark`, `coral-soft` | bad: eaten, vetoed, blocked, denied | BetterBill #b4232a, #e5484d, #fdecec |
| `amber`, `amber-soft` | caution: SIM, uncertain, stale | BetterBill #92400e, #fef3c7 |
| `slate`, `slate-soft` | neutral: sealed, pending, MIRROR | BetterBill #334155, #eef2f6 |
| `referee`, `referee-soft` | the CRS referee | BetterBill secondary pair, so the referee reads as the rule, not a new colour |
| `glass` | glass card fill | Prism rgba(255,255,255,.8) |

Rules: `*-mark` colours are for dots, icons and figures; `*` (the ink of the pair) is for text; `*-soft` is the ground behind that text. `live` cyan is a mark colour in light (3.7:1 on white) and never text under 18 px there; in dark it is 8.7:1 and may be text.

Contrast, computed from the hex values (text on its ground): `ink` 17.4:1 light and 14.1:1 dark on `surface`; `muted` 5.5:1 and 5.9:1; `pulse` 6.7:1 and 7.4:1; `pulse-ink` on `pulse` 6.7:1 and 8.2:1; every semantic pair between 5.7:1 and 9.3:1 in both themes. On the floor: `pac` 15.6:1, `ghost-1` 6.5:1, `ghost-2` 4.5:1, `ghost-3` 12.1:1, `ghost-4` 5.1:1, `shield` 9.6:1 on `floor-bg`. `floor-rope` is 3.2:1 and decorative.

Prism's own success (#036b4c) and danger (#a50f36) were measured too; the system uses BetterBill's pairs for those roles because they come with matching soft grounds. Noted so nobody re-measures.

## Type

- **Geist** 400, 500, 600 for everything. Display in 500 with tightened tracking; UI in 400 and 600. Prism sets body at 17.5 px and headings at 40 px in 500; BetterBill labels at 12 px in 500. The scale in the Typography view follows the Apple text-style rhythm (17/22 headline, 17/26 body, 15/20 subheadline, 13/18 footnote, 12/16 caption) so it sits naturally in a phone shell.
- **Geist Mono** 400, 500 for prices, codes, timestamps, agent addresses and the floor HUD; Prism uses it at 11.5 to 12 px for labels.
- Instrument Serif, Cinzel and Press Start 2P are gone. Both families are Google Fonts under the SIL Open Font License 1.1; `next/font/google` loads them at build time.

## Spacing, radius, layout

8 pt working grid on a 4 px base. Page gutter 16 px at 390 (never less), 32 at 1440. Cards padded 16 at 390 and 24 at 1440, 24 between cards, 48 between sections, 72 section padding on the landing. Container 1120 px. Radius 16 on cards (BetterBill), 20 on glass cards (Prism), 12 on buttons, rows and wells, 24 on the phone shell, pill for pills and dots. Tap targets 44 px; the nav links are 44 px tall even though they look 20. Shadows are layered and soft; never one hard drop.

## Shadows

| Token | Value (light) | Use |
| --- | --- | --- |
| `shadow-ring` | 0 0 0 1.5px rgba(11,27,43,.14), 0 1px 2px rgba(11,27,43,.08) | inputs, ghost buttons |
| `shadow-card` | 0 1px 2px rgba(11,27,43,.06), 0 8px 24px rgba(11,27,43,.06) | every card |
| `shadow-lift` | 0 24px 60px rgba(11,27,43,.18) | hero mock, phone shell, PiP |
| `shadow-glass` | inset 0 .5px 0 rgba(255,255,255,.95), 0 0 0 .5px rgba(14,23,38,.08), 0 4px 40px 8px rgba(14,23,38,.16), 0 34px 70px -34px rgba(14,23,38,.26) | glass cards, the approval sheet |

## Components

Live previews are in the Components view, grouped **Outside** and **Floor**. Each README states what the consumer provides and which states exist. Every demo-path screen has its empty, loading, success and error state designed: empty states are one sentence and one ghost action, loading is a `surface-2` skeleton at the card's final height, success is the mint check (420 ms), errors are a coral pill with the reason and the next step.

The **FloorPreview** runs as pure SVG and CSS keyframes (one 24 s loop), so it plays inside this viewer without a canvas. The same floor is published on its own as "Tech Bazaar Floor": https://claude.ai/artifact/GXt4CwUarWbzbWmvMFwaSi.

## Assets

No logo file yet: the wordmark is plain type (Geist 500, 16 px, letter-spacing -0.02em) beside a 22 px ink tile with a white buyer-disc cut-out. Agent avatars live in the repo at `agents/avatars/<role>.png`. Sponsor names (CRS, Bright Data, Apify, Stripe, Fetch.ai ASI:One, Cartesia, Tiger Data, Visa) are set as text labels in `caption` style; no sponsor marks are reproduced here.

## Where to go next

- `screens.md`: every route, its job, the data it shows, the components, and ready-to-paste React + Tailwind v4 snippets.
- `floor.md`: the 2D floor spec, phase table and timings; the base for the 3D version.
- `floor-3d.md`: the three.js spec mapped to `web/src/components/Floor3D.tsx`.
- `handoff.md`: the Tailwind v4 `@theme` block for `globals.css`, the `fonts.ts` replacement, and the build order split by owner.
