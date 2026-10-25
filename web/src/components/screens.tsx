// web/src/components/screens.tsx
// Page bodies. The pages in app/buyer and app/market keep their hooks and pairing logic and render these.
// Both are pure: give them view models and they draw. See README for the hook-to-view mapping.
import { originMixLabel, type ApprovalView, type ReviewView, type FeedItem, type FloorEventView, type GoalView, type LearningView, type LossReport, type RankedBid, type ReceiptView, type RoundView, type SellerLine, type ShieldView, type VetoView } from "@/lib/screens";
import type { ReactNode } from "react";
import { ASI_ONE_URL } from "@/lib/agentFeed";
import { AgentFeed, ApprovalCard, ReviewCard, GoalCard, HeroPrice, RankedBids, ReceiptCard, ShieldCard, StatePill, VetoCard } from "./buyer";
import { FloorEvents, LossReports, RefereeCard, RoundTimeline, SellerLearns, SellerLines } from "./market";
import { AllowancePanel, OwnedPartsPanel, PanelPreviews } from "./panels";
import { BuildBoard } from "./BuildBoard";
import { SAMPLE_BUILD, type BuildResult } from "@/lib/build";
import { Card, Label, Pill, SampleOnly, Unavailable, money } from "./ui";


export interface BuyerScreenProps {
  /** The planner's build (parts, sellers, steps); the SIM sample run is shown, labelled, until build rounds are live. */
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
  /** Cards fed from lib/sample.ts; each shows a SIM sample chip. */
  sample?: { bids?: boolean; veto?: boolean; shield?: boolean; approval?: boolean; receipt?: boolean };
}

const dayOf = (d: Date) => d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function Searches({ goals }: { goals: GoalView[] }) {
  if (!goals.length) {
    return (
      <Card>
        <Label>Active searches</Label>
        <p className="text-[22px] font-medium">No search yet.</p>
        <p className="mt-1 text-muted">
          Tell the buyer agent what you want in <a href={ASI_ONE_URL} target="_blank" rel="noreferrer" className="border-b border-current text-sky">ASI:One</a>, for example <q>a 1 TB NVMe drive under $90 by Friday</q>. It appears here with the cap and the allowance.
        </p>
      </Card>
    );
  }
  return (
    <div className="grid gap-3.5">
      <GoalCard goal={goals[0]!} />
      {goals.slice(1).map((g) => (
        <Card key={g.id}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="min-w-0 text-[15px] font-medium text-balance"><q>{g.text}</q></p>
            <StatePill state={g.state} />
          </div>
          <p className="mt-1 text-[13px] tabular-nums text-muted">Cap {money(g.cap)} · due {dayOf(g.deadline)}</p>
        </Card>
      ))}
    </div>
  );
}

export function BuyerScreen(p: BuyerScreenProps) {
  const s = p.sample ?? {};
  const goal = p.goals[0] ?? null;
  return (
    <div className="grid gap-3.5">
      {p.connecting ? (
        <PanelPreviews reason="Connecting to the market. Each panel fills in when it answers." />
      ) : (
        <>
          {p.composer}
          {p.review ? (
            <ReviewCard review={p.review} allowance={p.allowance?.perPurchase ?? null} />
          ) : (
            <Card>
              <Label>Needs your attention</Label>
              <p className="text-[18px] font-medium">Nothing is waiting for you.</p>
            </Card>
          )}
          <Searches goals={p.goals} />
          <SampleOnly on={!p.build}><BuildBoard build={p.build ?? SAMPLE_BUILD} origin={p.build?.origin ?? "SIM"} /></SampleOnly>
          <div className="grid gap-3.5 md:grid-cols-3">
            {p.purchases ?? <Unavailable title="Recent purchases">Recorded purchases are not connected to this screen yet.</Unavailable>}
            <AllowancePanel allowance={p.allowance} cap={goal?.cap ?? null} />
            <OwnedPartsPanel />
          </div>
          {goal && (
            <>
              <p className="rounded-[10px] border border-dashed border-line px-3 py-2.5 text-[13px] text-muted">
                The cards below show the latest public round. They are not yet matched to a specific search, because a round carries a need id and not a goal id. Sample cards are labelled SIM.
              </p>
              <SampleOnly on={!!s.bids}><HeroPrice bids={p.bids} cap={null} /></SampleOnly>
              <SampleOnly on={!!s.bids}><RankedBids bids={p.bids} revealKey={p.revealKey} /></SampleOnly>
              <div className={`grid gap-3.5 ${p.review ? "lg:grid-cols-2" : "lg:grid-cols-3"}`}>
                <SampleOnly on={!!s.veto}><VetoCard veto={p.veto} /></SampleOnly>
                <SampleOnly on={!!s.shield}><ShieldCard shield={p.shield} /></SampleOnly>
                {!p.review && <SampleOnly on={!!s.approval}><ApprovalCard approval={p.approval} /></SampleOnly>}
              </div>
              <div className="grid gap-3.5 lg:grid-cols-[8fr_4fr]">
                <SampleOnly on={!!s.receipt}><ReceiptCard receipt={p.receipt} /></SampleOnly>
                <AgentFeed items={p.feed} />
              </div>
            </>
          )}
        </>
      )}
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
    <div className="grid gap-3.5">
      <div className="relative flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="relative text-[18px] font-bold tracking-[-0.01em]">Market <span className="font-medium text-muted">the referee&apos;s floor</span></div>
        <div className="relative flex flex-wrap items-center gap-2 text-[14px] text-muted">
          {p.round && <span>{p.round.id} · {p.round.needId}</span>}
          {p.round && (p.round.state === "closed" ? <Pill tone="done">Closed</Pill> : <Pill tone="hunting">Open</Pill>)}
          {mixLabel && <span className="font-mono text-[12px]">{mixLabel}</span>}
        </div>
      </div>
      <p className="rounded-[10px] border border-dashed border-line px-3 py-2.5 text-[13px] text-muted">
        Every bid carries its origin. {c.LIVE} LIVE · {c.MIRROR} MIRROR · {c.SIM} SIM.
      </p>
      {p.connecting ? (
        <p className="text-muted">Connecting...</p>
      ) : !p.round ? (
        <section className="card p-[18px]">
          <p className="text-[22px] font-medium">No rounds yet.</p>
          <p className="mt-1 text-muted">When a buyer posts a need, a sealed round opens here with its 12 second window.</p>
        </section>
      ) : (
        <>
          <div className="grid gap-3.5 lg:grid-cols-[8fr_4fr]">
            <SampleOnly on={!!s.round}><RoundTimeline round={p.round} /></SampleOnly>
            <SampleOnly on={!!s.lines}><RefereeCard round={p.round} lines={p.lines} /></SampleOnly>
          </div>
          <SampleOnly on={!!s.lines}><SellerLines lines={p.lines} cap={p.cap} /></SampleOnly>
          <div className="grid gap-3.5 lg:grid-cols-2">
            <SampleOnly on={!!s.lossReports}><LossReports reports={p.lossReports} note={p.lossNote} /></SampleOnly>
            <div className="grid content-start gap-3.5">
              <SampleOnly on={!!s.learning}><SellerLearns learning={p.learning} /></SampleOnly>
              <FloorEvents events={p.events} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
