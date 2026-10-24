# Tech Bazaar screens, direction A "Ledger"

Design-only. Nothing here is on main or in the live build; label every screen `design-only` until Lane B or Lane D wires it and you see it at localhost:3100.

Artifact (two directions, real sample-run data): https://claude.ai/artifact/RSXzRk2GRUrmhJiqSZVmhf (private; share from the page's menu).
Hash links: `#ledger` (A), `#arena` (B). Each direction has a theme toggle and a 390 px phone toggle.

## Brief
Buyer screen = Vidyut's goal, ranked bids with quality-adjusted landed price, the advocate's veto with source, the Shield block, the approval with the word-pair code, the receipt. Market screen = the referee's floor: sealed round timeline, bids per seller line (new vs open-box as alternatives), events feed, loss reports. Readable from 3 m; works at 1280 and on a phone. Every price and seller carries LIVE / MIRROR / SIM.

## Recommendation: A "Ledger"
Calm white canvas, the app's existing indigo accent, one serif hero number per screen, thin rules, semantic tints only where they mean something (mint good, coral veto or block, amber caution or call, slate out). Three type sizes carry the hierarchy, which is what reads on a projector. B "Arena" (dark, amber, mono scoreboard, five-beat stepper) is the louder option; the stepper is worth stealing for the demo video, and dark canvases wash out on a cheap projector, so A is the safer judge-facing choice. Both directions are in the artifact.

## Files and what they replace

| File here | Goes to | Replaces |
|---|---|---|
| `code/tokens.css` | `web/src/app/globals.css` | the `:root`, dark and `@theme inline` blocks (keeps `.panel` so untouched pages still render) |
| `code/fonts.ts` | `web/src/app/fonts.ts` (new) | nothing; add `fontVars` to `<html className>` in `layout.tsx` |
| `code/shell.tsx` | `web/src/components/shell.tsx` (new) | the `<header>` in `layout.tsx` (`AppHeader`) and `components/RunModeFooter.tsx` (`RunModeFooter`, same props, honest per-service dots) |
| `code/components/ui.tsx` | `web/src/components/ui.tsx` (new) | `OriginBadge` (now `OriginChip`, same contract: unknown origin renders as SIM) plus Card, Label, Pill, Stat, Tag, Verdict, Code, SourceLink, `money`, `clock` |
| `code/components/buyer.tsx` | `web/src/components/buyer.tsx` (new) | the inline JSX in `app/buyer/page.tsx` (`BuyerScreen` body) |
| `code/components/market.tsx` | `web/src/components/market.tsx` (new) | the inline JSX in `app/market/page.tsx` |
| `code/components/screens.tsx` | `web/src/components/screens.tsx` (new) | page bodies: `BuyerScreen`, `MarketScreen`; `BUYER_NAME = "Vidyut"` |
| `code/data/types.ts` | `web/src/lib/screens.ts` (new) | view models the components take |
| `code/data/sample.ts` | `web/src/lib/sample.ts` (new) | Vidyut's run, every number from `demo/out/sample-run.json` |
| `screens/*.png` | reference | 1280 and 390 renders of the artifact (design-only) |

`code/_check/` and `code/tsconfig.check.json` are the type-check harness only; do not copy them.

## How to mount

`app/buyer/page.tsx` keeps `PairScreen` and the role check. Change `DEMO_BUYER` to `"vidyut"` (the market seed must post the goal for that buyer id) and replace the `BuyerScreen` function with:

```tsx
import { BuyerScreen } from "@/components/screens";
import * as sample from "@/lib/sample";

function BuyerPage() {
  const [goals, goalsReady] = useTable(tables.myGoals);
  const [goalItems] = useTable(tables.myGoalItems);
  const [allowances] = useTable(tables.myAllowance);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [notes] = useTable(tables.myNotifications);
  // map rows to views (goalFromRows, feedFromRows live in lib/screens.ts; sketch below)
  return (
    <BuyerScreen
      connecting={!goalsReady || !eventsReady}
      goal={goalFromRows(goals, goalItems, allowances[0])}
      bids={sample.rankedBids}        // until roundResult carries adjusted + recommendation (ask Lane B)
      veto={sample.veto}              // bidCheck is not in the public bindings yet
      shield={sample.shield}          // same
      approval={sample.approval}      // mandate + approval rows are not public yet; wordPair comes from the mandate's code issue
      receipt={sample.receipt}        // payment row
      feed={feedFromRows(events, notes)}
    />
  );
}
```

Row to view mapping, from the schema in `market/spacetimedb/src/schema.ts`:

- `GoalView` <- `goal` (type, cap, deadline, state, reservedAmount, origin) + `goalItem` (condition, variant, skippedOwnedPartId -> `skipped[]`) + `allowance` (perPurchaseLimit, periodLimit, period, spentThisPeriod, ladderStep). `text` is the buyer's own words; sample-run has it in `artifacts.goal.notes`; the `goal` table has no such column, so either add `notes` or compose "1 x rtx 5070 ti, new or open-box, under $1,300 by Fri Oct 30".
- `RankedBid[]` <- `roundResult` (rank, persona or sellerId, landed, reasons, lines, origin). Missing today: `adjusted` (quality-adjusted score) and the advocate recommendation; `reasons[]` carries the ineligible text. Until Lane B adds them, show `landed` in both columns and derive `recommendation` from `bidCheck`.
- `VetoView`, `ShieldView` <- `bidCheck` (kind shield | claim, result, detail, evidenceUrl, origin, at). Not in `module_bindings/` yet.
- `ApprovalView` <- `mandate` (amount, payee, withinAllowance, expiry) + `approval` (method, approvedBy, at). The word-pair code is issued by Lane D's call flow (`approval_record.code_hash` in sample-run; the plain code is redacted there). `attempts[]` <- `beats.4.attempts`.
- `ReceiptView` <- `payment` (paymentRef, amount, at) + `mandate` (hash, id, expiry, origin). `replayRefused` <- `checks.beat4_signature_valid_and_replay_fails`.
- `FeedItem[]` <- `floorEvent` + `notification`, with the current `classify()` in `app/buyer/page.tsx` mapped to `kind` (deal | bid | veto | block | progress).

`app/market/page.tsx`:

- `RoundView` <- `round` (openedAt, deadline, extensions, state, sealedCount, origin). `arrivals[]` needs each bid's `sealedAt` relative to `openedAt`; `bid.sealedAt` exists but the table is private. Ask Lane B for a public projection (seller label, sealedAt ms, origin, floorCheckPassed) or read `beats.2.arrivals` from the run file. `seenBeforeClose` <- `beats.2.visibility`.
- `SellerLine[]` <- `roundResult.lines[]` (one row per BidLine: offeredCondition, unitPrice) joined with `roundResult.rank` and `reasons`; the alternative line (`alt`) is any line that is not the cheapest allowed. `referee: refused` rows come from `rejectedAttempt` (kind, reason).
- `LossReport[]`, `LearningView` <- `beats.5.round1_loss_reports`, `beats.5.strategy`, `beats.5.learner` (no market table yet; Lane A owns loss reports).
- `FloorEventView[]` <- `floorEvent` (kind, label, origin, refTable/refId -> `ref`).
- `originCounts` <- count `roundResult.origin`.

## Honesty rules built into the components
- `OriginChip` renders anything unknown as SIM.
- `RunModeFooter` shows a mint dot only for services whose adapter is real; edit `OTHER_SERVICES` as lanes land.
- `ReceiptCard` shows the charge status string verbatim ("SIM stub, no money moved" in this run).
- `SellerLearns` prints `whatToChangeOrigin` ("SIM template" in this run) under the quote.
- The sample word pair "velvet falcon" is a stand-in: sample-run.json redacts the real code (`beats.4.code_redacted: true`). Replace it with the issued code or the demo will show a pair that never matches.

## States designed
Every card has an empty state (no goal, no round, no veto, no block, no call, no payment, no events). Loading is the existing "Connecting to the market..." line. Error states for pairing stay in `PairScreen`. The success moment is one short scale-in on the receipt check (`motion-safe:` only; add `@keyframes pop` to globals.css if Tailwind does not find it: `from { transform: scale(.6); opacity: 0 } to { transform: scale(1); opacity: 1 }`).

## Checks done
- Artifact rendered with Playwright at 1280 (A light, A dark, B dark) and 390 (A): `document.documentElement.scrollWidth` equalled the viewport in all four, so no horizontal scroll. Timeline labels spread over three rows after the first render showed collisions.
- `code/` type-checks with `tsc --strict` against React 18 types and stubs for `next/*` and `spacetimedb/react` (`code/_check/stubs.d.ts`). Not checked: a real `next build` with Tailwind v4 (no node_modules in `lane-d-bridge/web`), React 19 specifics, and the live SpacetimeDB rows.
- Not checked: 1920x1080 at 25 percent, contrast ratios by formula (the palette reuses BetterBill-style ink-on-white values; verify `--muted` on `--soft` before freeze), screen readers.

## Licenses
Geist, Geist Mono, Instrument Serif: SIL Open Font License 1.1 via Google Fonts (loaded through `next/font/google`, no runtime request). No other third-party pieces; no shadcn or registry installs needed.
