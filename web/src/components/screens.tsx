// web/src/components/screens.tsx
// Page bodies. The pages in app/buyer and app/market keep their hooks and pairing logic and render these.
// Both are pure: give them view models and they draw. See README for the hook-to-view mapping.
import { buyerKpis, originMixLabel, roundTitle, type ApprovalView, type ReviewView, type FeedItem, type FloorEventView, type GoalView, type LearningView, type LossReport, type RankedBid, type ReceiptView, type RoundView, type SellerLine, type ShieldView, type VetoView } from "@/lib/screens";
import type { ReactNode } from "react";
import { AgentFeed, ApprovalCard, ReviewCard, GoalCard, HeroPrice, KpiCard, RankedBids, ReceiptCard, ShieldCard, StatePill, VetoCard } from "./buyer";
import { FloorEvents, LossReports, RefereeCard, RoundTimeline, SellerLearns, SellerLines } from "./market";
import { AllowancePanel, OwnedPartsPanel, PanelPreviews } from "./panels";
import { BuildBoard } from "./BuildBoard";
import type { BuildResult } from "@/lib/build";
import { Card, Details, SampleOnly, money } from "./ui";


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
  /** Paid receipts in myDeals. */
  receiptsCount?: number;
}

const dayOf = (d: Date) => d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function Searches({ goals }: { goals: GoalView[] }) {
  if (!goals.length) return null;
  const older = goals.slice(1);
  return (
    <div className="grid gap-5">
      <GoalCard goal={goals[0]!} />
      {older.length > 0 && (
        <div>
          <h3 className="mb-1 text-[13px] text-muted">Earlier searches</h3>
          <ul className="divide-y divide-line border-y border-line">
            {older.map((g) => (
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
      )}
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
    <div className="grid gap-6">
      {p.review && (
        <a href="#needs-you" className="card card-active flex flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-5">
          <span className="flex items-center gap-2.5 text-[15px] font-semibold"><span className="dot text-live" aria-hidden /> Your approval is needed. Say the code on the call.</span>
          <span className="text-[14px] font-medium text-pulse">Show the code <span aria-hidden>↓</span></span>
        </a>
      )}

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((k) => <KpiCard key={k.id} kpi={k} />)}
      </div>

      {p.review ? (
        <Section id="needs-you" title="Needs you">
          <ReviewCard review={p.review} allowance={p.allowance?.perPurchase ?? null} />
        </Section>
      ) : (
        <span id="needs-you" className="scroll-mt-24" />
      )}

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
  );
}


export interface MarketScreenProps {
  round: RoundView | null;
  cap: number | null;
  lines: SellerLine[];
  lossReports: LossReport[];
  lossNote?: string;
  learning: LearningView | null;
  events: FloorEventView[];
  originCounts: { LIVE: number; MIRROR: number; SIM: number };
  connecting?: boolean;
  sample?: { round?: boolean; lines?: boolean; lossReports?: boolean; learning?: boolean };
}

export function MarketScreen(p: MarketScreenProps) {
  const c = p.originCounts;
  const mixLabel = originMixLabel(c);
  const s = p.sample ?? {};
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
      ) : !p.round ? (
        <section className="card p-[18px]">
          <p className="text-[22px] font-medium">No rounds yet.</p>
          <p className="mt-1 text-muted">When a buyer posts a request, a sealed round opens here and bids stay sealed until it closes.</p>
        </section>
      ) : (
        <>
          <SampleOnly on={!!s.lines}><RefereeCard round={p.round} lines={p.lines} /></SampleOnly>
          <SampleOnly on={!!s.lines}><SellerLines lines={p.lines} cap={p.cap} /></SampleOnly>
          <p className="text-[13px] leading-[18px] text-muted">Every bid carries its origin: {c.LIVE} LIVE · {c.MIRROR} MIRROR · {c.SIM} SIM.</p>
          <Details summary="Round history: the timeline, why sellers lost, what they learned, every event" className="mt-0">
            <div className="grid gap-6">
              <SampleOnly on={!!s.round}><RoundTimeline round={p.round} /></SampleOnly>
              <div className="grid items-start gap-6 lg:grid-cols-2">
                <SampleOnly on={!!s.lossReports}><LossReports reports={p.lossReports} note={p.lossNote} /></SampleOnly>
                <SampleOnly on={!!s.learning}><SellerLearns learning={p.learning} /></SampleOnly>
              </div>
              <FloorEvents events={p.events} />
            </div>
          </Details>
        </>
      )}
    </div>
  );
}
