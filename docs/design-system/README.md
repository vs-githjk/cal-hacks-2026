# Tech Bazaar

A secure agentic marketplace. The buyer states a goal; seller agents bid in sealed knockout rounds; a referee ranks them by one rule; Shield screens every listing; a checker verifies fit and recalls; above the allowance the buyer approves by phone with a spoken code; a Stripe test-mode charge and a receipt close each part.

The product has two worlds and one pulse:

- **Outside** (landing, /start, /buyer, /buyer/agents, /buyer/decisions, /buyer/purchases, /sell, /seller, /market, /lot): a calm finance app that shows agents. White canvas, one ink, one action colour, thin borders, a living pulse (status dots, agent heartbeat, number tickers, one soft glow on the active card). Nothing neon.
- **Floor** (/floor only): a 2.5D Pac-Man boxing ring on black line art, used in the demo video and on a TV. Colour lives here. See `floor.md`.
- **The crossing**: both worlds share the wordmark, the tokens file, the `pulse` colour (the Shield hexagon on the floor is the same value as the dark-theme action colour), the status words (LIVE, SEALED, EATEN, BLOCKED, APPROVED) and the same seller colours (`ghost-1..4` are the dot colours on decision rows). A "Watch the floor" ghost button on the outside opens the floor; the floor's HUD wordmark links back.

The working name is Tech Bazaar. **The wordmark is a token**: render it from one `data-wordmark` string (see `handoff.md`) so the final name swaps in one place.

## Principles

1. **Trust first.** One hero number per screen, calm and large (Instrument Serif). Every state says its word next to its colour. Every number on screen comes from `data/scoreboard.json` or the reference run; nothing invented.
2. **Honesty labels everywhere.** Every bid, claim, screen and price carries LIVE, MIRROR (dated listing), SIM or Env-gated, driven by the `source` field. Planned work is labelled "planned, not built" on the screen itself.
3. **Readable in one second.** Headings in Geist 600 or Instrument Serif 400, normal widths. No novelty display faces on the outside; Press Start 2P is allowed only on the floor HUD at 11 px and up.
4. **Thin borders, not shadows.** `line` on every card; `shadow-pop` only for the picture-in-picture frame, menus and the approval sheet; `shadow-glow` on at most one card per screen.
5. **Motion with a reason.** Fades, 8 px rises, a 900 ms count-up, a 1.8 s pulse ring. On the floor, dashes, chomps and a walk-out at the timings in `timing`. All of it pauses under `prefers-reduced-motion`; the floor becomes a stepped slideshow with the same frames.
6. **Copy says "the buyer"**, never a person's name. Never "many buyers use it". Never call Shield "secure"; say what it stopped and what it missed.

## Colour

Light is the first theme for the outside; dark is the second. The floor is always dark and uses the `floor-*`, `pac`, `ghost-*`, `referee`, `shield`, `checker`, `tag-*` and `crowd` tokens, which carry the same value in both themes.

| Token | Means | Where |
| --- | --- | --- |
| `ink` | the one text colour and the primary button | everywhere outside |
| `pulse` | the action and the living pulse | links, active state, status dots, the Shield on the floor |
| `mint` | good: approved, verified fit, paid, verified_stable | pills, checker tick |
| `coral` | bad: eaten, vetoed, blocked, denied | pills, the eaten row, the floor's EATEN tag |
| `amber` | caution: SIM, uncertain, stale, env-gated | pills only |
| `slate` | neutral: sealed, pending, MIRROR | pills |
| `royal` | the CRS referee only | referee pill, the referee call banner |
| `pac` | the buyer agent | floor only; the only yellow in the product |

Contrast on `surface`: `muted` 4.9:1 light and 6.5:1 dark, `pulse` 5.6:1 light and 6.7:1 dark, `mint` 5.2:1 light, `coral` 5.3:1 light, `amber` 5.0:1 light, `royal` 6.9:1 light. Pills put each colour on its own soft tint, which keeps those ratios. On the floor, `tag-ink` on `tag-bg` is 18:1; callouts in `pac`, `checker`, `shield` and `referee` on `floor-bg` are all above 7:1. `ghost-eaten` is decorative, never text.

## Type

- **Geist** for UI (400, 500, 600). Replaces nothing; already in `fonts.ts`.
- **Instrument Serif** (400) for display and the hero number. **Replaces Cinzel.** Cinzel's wide caps fought the one-second readability rule; Instrument Serif is narrow, quiet and reads as finance.
- **Geist Mono** for prices, codes, timestamps, agent addresses and the spoken approval code.
- **Press Start 2P** for the floor HUD and the one-word floor callouts only.

All four are Google Fonts under the SIL Open Font License 1.1; `next/font/google` loads them at build time. The type scale is in the Typography view; use `display-xl` once per landing, `number-hero` once per screen, `caption` for every uppercase label.

## Spacing, radius, layout

4 px base. Page gutter 16 px at 390 (never less), cards padded 16 at 390 and 20 at 1440, 24 between cards, 32 between sections, 64 section padding on the landing. Container 1120 px. Radius 16 on cards, 12 on buttons and rows, 24 on the hero mock, the PiP frame and the phone shell, pill for pills and dots. Tap targets 44 px; the nav links are 44 px tall even though they look 20.

## Components

Live previews are in the Components view, grouped **Outside** and **Floor**. Each README states what the consumer provides and which states exist. Every demo-path screen has its empty, loading, success and error state designed: empty states are one sentence and one ghost action, loading is a `surface-2` skeleton at the card's final height, success is the mint check (420 ms pop), errors are a coral pill with the reason and the source link.

## Assets

No logo file yet: the wordmark is plain type (Geist 600, 16 px, letter-spacing -0.01em) beside a 22 px ink tile with a `pulse` Pac-Man cut-out. Agent avatars live in the repo at `agents/avatars/<role>.png` (navy tile, colour ring, initials). Sponsor names (CRS, Bright Data, Apify, Stripe, Fetch.ai ASI:One, Cartesia, Tiger Data, Visa) are set as text labels in `caption` style; no sponsor marks are drawn here.

## Where to go next

- `screens.md`: every route, its job, the data it shows, the components, and ready-to-paste React + Tailwind v4 snippets.
- `floor.md`: the 2.5D floor sprite spec with sizes, colours and timings.
- `handoff.md`: the Tailwind v4 `@theme` block for `globals.css`, the `fonts.ts` replacement, and the build order split by owner (Abhinav: /floor; Vedant: landing, /start, /buyer screens).
