// web/src/components/screens.tsx
// Page bodies. The pages in app/buyer and app/market keep their hooks and pairing logic and render these.
// Both are pure: give them view models and they draw. See README for the hook-to-view mapping.
import { buyerKpis, originMixLabel, roundTitle, type MarketKpis, type RoundHistoryItem, type ApprovalView, type ReviewView, type FeedItem, type FloorEventView, type GoalView, type RankedBid, type ReceiptView, type RoundView, type SellerLine, type ShieldView, type VetoView } from "@/lib/screens";
import type { ReactNode } from "react";
import { AgentFeed, ApprovalCard, ReviewCard, HeroPrice, KpiCard, QuietOrigin, RankedBids, ReceiptCard, ShieldCard, StatePill, VetoCard } from "./buyer";
import { FloorEvents, RefereeCard, RoundTimeline, SellerLines } from "./market";
import { AllowancePanel, OwnedPartsPanel, PanelPreviews } from "./panels";
import { BuildBoard } from "./BuildBoard";
import type { BuildResult } from "@/lib/build";
import { Card, Details, money } from "./ui";


export interface BuyerScreenProps {
  /** The planner's live build (parts, sellers, steps); the board shows only when a real one exists. */
  build?: BuildResult;
  /** This buyer's searches, open ones first; the first is the active one. */
  goals: GoalView[];
  /** The buyer's spending rule; shown even before the first goal. */
  allowance: GoalView["allowance"];
  /** The product request, first on the page (app/buyer fills it with the GoalComposer). */
  composer?: ReactNode;
  /** The recent purchases card (app/buyer fills it from recorded memory); unavailable when absent. */
  purchases?: ReactNode;
  bids: RankedBid[];
  veto: VetoView | null;
  shield: ShieldView | null;
  approval: ApprovalView | null;
  /** A live mandate waiting for this buyer; when present it replaces the sample approval card. */
  review?: ReviewView | null;
  receipt: ReceiptView | null;
  feed: FeedItem[];
  /** Id of the latest round close event; a new one flips the bids open. */
  revealKey?: string;
  connecting?: boolean;
  /** True while the latest round has not closed: the best-offer card then shows no price. */
  roundOpen?: boolean;
  /** True when every row is SIM: per-row SIM chips are left out (only a LIVE or MIRROR row shows its chip). */
  quietOrigin?: boolean;
  /** Paid receipts in myDeals. */
  receiptsCount?: number;
}

const dayOf = (d: Date) => d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function Searches({ goals }: { goals: GoalView[] }) {
  if (!goals.length) return null;
  return (
    <div>
      <h3 className="mb-1 text-[15px] font-semibold">Your searches</h3>
      <ul className="divide-y divide-line border-y border-line">
        {goals.map((g) => (
              <li key={g.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5">
                <span className="min-w-0 truncate text-[15px] font-medium"><q>{g.text}</q></span>
                <span className="flex items-center gap-3 text-[13px] tabular-nums text-muted">
                  <span>Cap {money(g.cap)}, due {dayOf(g.deadline)}</span>
                  <StatePill state={g.state} />
                </span>
              </li>
        ))}
      </ul>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="grid scroll-mt-24 gap-5">
      <h2 className="text-[17px] font-semibold tracking-[-0.01em]">{title}</h2>
      {children}
    </section>
  );
}

export function BuyerScreen(p: BuyerScreenProps) {
  const goal = p.goals[0] ?? null;
  if (p.connecting) return <PanelPreviews reason="Connecting to the market. Each panel fills in when it answers." />;
  const kpis = buyerKpis(p.goals, p.bids, p.review ?? null, p.allowance, p.receiptsCount ?? 0, !!p.roundOpen);
  const decided = [p.veto, p.shield, p.approval && !p.review ? p.approval : null, p.receipt].filter(Boolean).length;
  return (
    <QuietOrigin.Provider value={!!p.quietOrigin}>
    <div className="grid gap-6">
      {p.review && (
        <a href="#needs-you" className="card card-active flex flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-5">
          <span className="flex items-center gap-2.5 text-[15px] font-semibold"><span className="dot text-live" aria-hidden /> Your approval is needed. Say the code on the call.</span>
          <span className="text-[14px] font-medium text-pulse">Show the code <span aria-hidden>↓</span></span>
        </a>
      )}

      <div className="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4">
        {kpis.map((k) => <KpiCard key={k.id} kpi={k} />)}
      </div>

      {p.review ? (
        <Section id="needs-you" title="Needs you">
          <ReviewCard review={p.review} allowance={p.allowance?.perPurchase ?? null} />
        </Section>
      ) : (
        <span id="needs-you" className="scroll-mt-24" />
      )}

      {goal ? (
        <>
      <Section id="bids" title="Live bids">
        {p.bids.length > 0 ? (
          <>
            <HeroPrice bids={p.bids} cap={goal?.cap ?? null} />
            <RankedBids bids={p.bids} revealKey={p.revealKey} />
          </>
        ) : (
          <Card>
            <p className="text-[17px] font-semibold">No bids yet for this search.</p>
            <p className="mt-1 text-[13px] text-muted">Bids appear here when sellers answer, and stay sealed until the round closes.</p>
          </Card>
        )}
        {p.build && <BuildBoard build={p.build} origin={p.build.origin ?? "SIM"} />}
      </Section>

      <Section id="decisions" title="What happened and why">
        {decided === 0 ? (
          <Card>
            <p className="text-[17px] font-semibold">Nothing decided yet.</p>
            <p className="mt-1 text-[13px] text-muted">Vetoes, Smell Test blocks and receipts appear here with their reason and source.</p>
          </Card>
        ) : (
          <div className="grid items-start gap-5 lg:grid-cols-2">
            {p.veto && <VetoCard veto={p.veto} />}
            {p.shield && <ShieldCard shield={p.shield} />}
            {p.approval && !p.review && <ApprovalCard approval={p.approval} />}
            {p.receipt && <ReceiptCard receipt={p.receipt} />}
          </div>
        )}
        <AgentFeed items={p.feed} />
      </Section>
      <Section id="new-search" title="New search">
        {p.composer}
        <Searches goals={p.goals} />
      </Section>
        </>
      ) : (
      <Section id="new-search" title="New search">
        {p.composer}
        <Searches goals={p.goals} />
      </Section>
      )}

      <div id="allowance" className="scroll-mt-24">
        <Details summary="Your allowance, your rig and the agent log" className="mt-2">
          <div className="grid gap-5 md:grid-cols-2">
            <AllowancePanel allowance={p.allowance} cap={goal?.cap ?? null} />
            <OwnedPartsPanel />
          </div>
          {p.purchases}
        </Details>
      </div>
    </div>
    </QuietOrigin.Provider>
  );
}


export interface MarketScreenProps {
  round: RoundView | null;
  cap: number | null;
  lines: SellerLine[];
  kpis: MarketKpis;
  history: RoundHistoryItem[];
  events: FloorEventView[];
  originCounts: { LIVE: number; MIRROR: number; SIM: number };
  connecting?: boolean;
}

function Kpi({ label, value, line, dot }: { label: string; value: string; line: string; dot?: { on: boolean; word: string } }) {
  return (
    <section className="card min-w-0 p-4">
      <p className="text-[13px] leading-[18px] text-muted">{label}</p>
      <p className="mt-1 truncate font-mono text-[24px]/[30px] font-medium tabular-nums">{value}</p>
      <p className="mt-0.5 flex items-center gap-1.5 text-[13px] leading-[18px] text-muted">
        {dot && <span className={`h-2 w-2 shrink-0 rounded-full ${dot.on ? "bg-live" : "bg-mint-mark"}`} aria-hidden />}
        <span className="truncate">{dot ? `${dot.word} · ${line}` : line}</span>
      </p>
    </section>
  );
}

export function MarketScreen(p: MarketScreenProps) {
  const c = p.originCounts;
  const mixLabel = originMixLabel(c);
  const k = p.kpis;
  return (
    <div className="mx-auto grid w-full max-w-[1120px] grid-cols-[minmax(0,1fr)] gap-6 pt-2 md:px-4 md:pt-6">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div>
          <p className="text-[13px] leading-[18px] text-muted">The referee&apos;s floor</p>
          <h1 className="mt-2 text-[28px] font-medium leading-[34px] tracking-[-0.015em]">Market</h1>
        </div>
        {p.round && (
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px] text-ink-2">
            <span className={`h-2 w-2 rounded-full ${p.round.state === "closed" ? "bg-mint-mark" : "bg-live"}`} aria-hidden />
            <span className="font-medium text-ink">{roundTitle(p.round.id) ?? "Latest round"}</span>
            <span>· {p.round.state === "closed" ? "closed" : "open, bids sealed"}</span>
            {mixLabel && <span className="text-muted">· {mixLabel}</span>}
          </p>
        )}
      </div>
      {p.connecting ? (
        <p className="text-muted">Connecting...</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Rounds run" value={String(k.roundsRun)} line={`${k.openNow} open now`} />
            <Kpi
              label="Bids this round"
              value={String(k.bidsLatest)}
              line={k.latestOpen ? "prices stay sealed" : "latest round"}
              dot={k.roundsRun === 0 ? undefined : { on: k.latestOpen, word: k.latestOpen ? "Open" : "Closed" }}
            />
            <Kpi label="Sellers who bid" value={k.sellersLatest === null ? (k.roundsRun === 0 ? "0" : "Sealed") : String(k.sellersLatest)} line={k.latestOpen ? "shown when the round closes" : "in the latest round"} />
            <Kpi label="Last winner" value={k.lastWinner ? k.lastWinner.seller : "No winner yet"} line={k.lastWinner ? `${money(k.lastWinner.landed)} landed` : "shown when a round closes"} />
          </div>
          {!p.round ? (
            <section className="card p-[18px]">
              <p className="text-[22px] font-medium">No rounds yet.</p>
              <p className="mt-1 text-muted">When a buyer posts a request, a sealed round opens here and bids stay sealed until it closes.</p>
            </section>
          ) : (
            <>
              <RefereeCard round={p.round} lines={p.lines} />
              <SellerLines lines={p.lines} cap={p.cap} />
              <p className="text-[13px] leading-[18px] text-muted">Every bid carries its origin: {c.LIVE} LIVE · {c.MIRROR} MIRROR · {c.SIM} SIM.</p>
            </>
          )}
          {p.history.length > 0 && (
            <section className="card min-w-0 p-4 md:p-6">
              <h2 className="text-[15px] font-medium">Recent rounds</h2>
              <ul className="mt-2">
                {p.history.map((h) => (
                  <li key={h.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line py-2.5 text-[14px] last:border-b-0">
                    <span className="min-w-0 flex-1 font-medium text-ink [overflow-wrap:anywhere]">{roundTitle(h.id) ?? h.id}</span>
                    <span className="flex items-center gap-1.5 text-muted">
                      <span className={`h-2 w-2 rounded-full ${h.state === "closed" ? "bg-mint-mark" : "bg-live"}`} aria-hidden />
                      {h.state === "closed" ? "closed" : "open"}
                    </span>
                    <span className="tabular-nums text-ink-2">{h.state === "open" ? "bids sealed" : h.winner ? `${h.winner.seller}, ${money(h.winner.landed)}` : "no winner"}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {p.round ? (
            <Details summary="Round timeline and every floor event" className="mt-0">
              <div className="grid gap-6">
                <RoundTimeline round={p.round} />
                <FloorEvents events={p.events} />
              </div>
            </Details>
          ) : (
            p.events.length > 0 && <Details summary="Floor events" className="mt-0"><FloorEvents events={p.events} /></Details>
          )}
        </>
      )}
    </div>
  );
}
