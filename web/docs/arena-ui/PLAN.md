# Arena UI: "Colosseum at night"

> **v2, restraint (Sat 19:10, after review: "looks AI generated, too red").** This supersedes the motif and component notes below where they differ.
> - One memorable element per screen. On the build panel it is the segmented budget bar (each part's price as a share of the cap), the only gold.
> - Cinzel only in the wordmark and the landing headline. Labels are sentence case in the body sans; no all-caps eyebrows, no Roman numerals, no per-row WON pills.
> - Red is a small dot or one word, only for something that went wrong (clash, out, blocked, failed). Never a fill or a border. Green is the build state "Locked" and a winning bid row.
> - Status is a dot and a word, not a pill. The agent's steps are a quiet timeline with a dot per step.
> - /buyer has no Question card: the goal card already is the question.

The app stops being a black-and-white ledger and becomes the stands around the 3D arena. Dark warm stone, gold for the house,
laurel green for a win, Pompeian red for a knockout, Tyrian purple only for the referee. Every round is framed as **one question**
put to the arena ("Who sells the best RTX 5070 Ti under $750?"), and the six-part build is the **program of the day**: Bouts I to VI.

Hue now carries meaning, but never alone: every colored state still says its word (WON, KNOCKED OUT, VETOED, LIVE, MIRROR, SIM).

## Tokens (`src/app/globals.css`, `:root`)

Keep every existing token name so untouched components restyle for free. Values:

| token | value | role |
|---|---|---|
| canvas / canvas-2 | `#0D0A08` / `#120E0B` | night sky, warm black |
| panel / soft | `#17120E` / `#211A14` | stone slab, inset |
| glass | `rgba(13,10,8,0.78)` | |
| ink / ink-2 | `#F3E9D7` / `#D6C8B0` | travertine |
| muted / slate | `#9A8B75` / `#8A7D6B` | |
| line / line-2 | `#2B231B` / `#43372A` | |
| accent / accent-2 | `#E9B949` / `#F2CC6B` | imperial gold (same gold as the 3D trophy) |
| accent-ink | `#1A1208` | text on gold |
| accent-soft | `rgba(233,185,73,0.12)` | |
| coral / coral-soft | `#DE5B41` / `rgba(222,91,65,0.14)` | Pompeian red: veto, knocked out, clash, error |
| mint / mint-soft | `#6DBF7E` / `rgba(109,191,126,0.14)` | laurel green: won, approved, LIVE |
| amber / amber-soft | `#C8925A` / `rgba(200,146,90,0.12)` | bronze: SIM, caution |
| sky / sky-soft | `#93B4C8` / `rgba(147,180,200,0.12)` | marble blue: MIRROR, source links |
| royal / royal-soft (new) | `#9B4A86` / `rgba(155,74,134,0.16)` | Tyrian purple: the referee only |
| grid | `rgba(233,185,73,0.05)` | |

Add `--color-royal` and `--color-royal-soft` to `@theme inline`.

## Type (`src/app/fonts.ts`)

- Display: **Cinzel** (Google, OFL) replaces Instrument Serif as `--font-display`. Used for: page titles, the question, card labels, hero numbers, Roman numerals.
- Body Geist, mono Geist Mono: unchanged.
- `Label` becomes `font-display`, 12px, tracking 0.14em, color `accent` at 80% (`text-accent/80`).

## Motifs (CSS only, no images, no new deps)

- **Colonnade**: replace the blueprint grid in `body::before` with a faint row of arches across the top (repeating radial-gradient semicircles, ~72px wide), masked to fade out by 40% of the viewport.
- **Card**: stone slab, 1px `line`, top edge 1px inner highlight `rgba(243,233,215,0.04)`. The pointer border glow (`.card::before`) is gold.
- **Laurel mark**: one inline SVG (two leaf arcs) in the shell logo. No icon library.
- **Roman numerals**: `src/lib/roman.ts` exports `roman(n)` for 1 to 3999, with `roman.test.ts` (node --test).
- Motion: one gold pulse (`@keyframes torch`) for "in the arena now"; nothing else animates. Reduced motion already kills all of it.

## The Question (`src/components/arena.tsx`, new)

One component, used on landing, /buyer and /floor.

```ts
type QuestionProps = {
  question: string;              // "Who sells the best RTX 5070 Ti under $750?"
  bout?: number;                 // shown as "BOUT III" via roman()
  of?: number;                   // "of VI"
  status: "open" | "sealed" | "verdict";
  contenders?: number;
  verdict?: { kind: "won" | "knocked"; text: string }; // only with status "verdict"
  origin?: string;               // LIVE / MIRROR / SIM, shown with OriginChip; omitted = no chip
};
export function Question(props: QuestionProps): JSX.Element
```

Layout: eyebrow row "THE QUESTION · BOUT III of VI" (Cinzel, gold) and a status pill on the right (OPEN = gold torch pulse,
SEALED = bronze, VERDICT = green or red). The question itself in Cinzel 28px (20px on phones), ink. A thin gold rule.
Under it: contenders count, then the verdict line in green (won) or red (knocked) with its word. Card with a 3px gold top border.

Also export `BoutStatus` = `"waiting" | "in-arena" | "won" | "knocked" | "clash"` and `BoutBadge({ status })`:
waiting = muted outline, in-arena = gold + torch pulse, won = green "WON", knocked = red "KNOCKED OUT", clash = red "CLASH".

## Parts (one Sonnet coder each, files disjoint)

1. **Foundation**: `globals.css`, `fonts.ts`, `ui.tsx`, `lib/roman.ts` + test, `components/arena.tsx`.
   OriginChip: LIVE solid green, MIRROR marble outline, SIM dashed bronze. Pill/Verdict keep their words. Card hover shadow warm, not white.
2. **Shell + landing**: `shell.tsx`, `app/page.tsx`. Header: laurel mark + "TECH BAZAAR" in Cinzel, active nav item gold underline.
   Landing hero becomes "The arena answers one question at a time." with a `Question` (the demo request, origin SIM) and the
   program of six bouts as a row of numeral tiles. Stat tiles: numbers in Cinzel.
3. **Build program**: `BuildBoard.tsx`, `build.tsx`. Each part is a bout: numeral, part name, budget, winner/seller, `BoutBadge`.
   Locked build total in a gold "laurel" footer. Never change the data parsing, only markup and classes.
4. **Buyer dashboard**: `screens.tsx`, `buyer.tsx`. `Question` at the top of /buyer built from the active goal
   (no goal = no Question card, never a fake one). Ranked bids read as contenders: winner row green edge + "WON", vetoed red + strike + "VETOED".
5. **Fetch tile + floor frame**: `AgentPip.tsx`, `app/floor/page.tsx`. Tile header gold, plan steps: CLASH/KNOCKED red, LOCKED green, RE-PLAN gold.
   /floor: `Question` above the canvas from the latest round row if there is one; the 3D container gets a stone frame (do not edit `Floor3D.tsx` or `lib/arena*`: the 3D agent owns those).

## Rules for every part

- No new npm dependencies. Tailwind classes and tokens only, no literal hex outside `globals.css`.
- Keep every data path, prop and test as is. This is a reskin plus the Question component.
- Keep LIVE/MIRROR/SIM labels and the SIM sample chips exactly where they are.
- Done = `npm run lint`, `npx tsc --noEmit`, `npm test` pass, and the page renders in the preview.
