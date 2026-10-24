// web/src/components/screens.tsx
// Page bodies. The pages in app/buyer and app/market keep their hooks and pairing logic and render these.
// Both are pure: give them view models and they draw. See README for the hook-to-view mapping.
import type { ApprovalView, FeedItem, FloorEventView, GoalView, LearningView, LossReport, RankedBid, ReceiptView, RoundView, SellerLine, ShieldView, VetoView } from "@/lib/screens";
import { AgentFeed, ApprovalCard, GoalCard, HeroPrice, RankedBids, ReceiptCard, ShieldCard, StatePill, VetoCard } from "./buyer";
import { FloorEvents, LossReports, RefereeCard, RoundTimeline, SellerLearns, SellerLines } from "./market";
import { OriginChip, Pill } from "./ui";

export const BUYER_NAME = "Vidyut"; // the buyer is fixed to Vidyut. Real sign-in replaces this.

export interface BuyerScreenProps {
  goal: GoalView | null;
  bids: RankedBid[];
  veto: VetoView | null;
  shield: ShieldView | null;
  approval: ApprovalView | null;
  receipt: ReceiptView | null;
  feed: FeedItem[];
  connecting?: boolean;
}

export function BuyerScreen(p: BuyerScreenProps) {
  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="flex items-center gap-2.5 text-[18px] font-bold tracking-[-0.01em]">Buyer</div>
        <div className="flex flex-wrap items-center gap-2 text-[14px] text-muted">
          <span>{BUYER_NAME}</span>
          {p.goal && <StatePill state={p.goal.state} />}
        </div>
      </div>

      {p.connecting ? (
        <p className="text-muted">Connecting to the market...</p>
      ) : !p.goal ? (
        <section className="card p-[18px]">
          <p className="text-[22px] font-medium">No goal yet.</p>
          <p className="mt-1 text-muted">Tell the agent what you want ("RTX 5070 Ti that fits my case, under $1,300, by Friday") and it appears here with the cap and the allowance.</p>
        </section>
      ) : (
        <>
          <div className="grid gap-3.5 lg:grid-cols-[7fr_5fr]">
            <GoalCard goal={p.goal} />
            <HeroPrice bids={p.bids} cap={p.goal.cap} />
          </div>
          <RankedBids bids={p.bids} />
          <div className="grid gap-3.5 lg:grid-cols-3">
            <VetoCard veto={p.veto} />
            <ShieldCard shield={p.shield} />
            <ApprovalCard approval={p.approval} />
          </div>
          <div className="grid gap-3.5 lg:grid-cols-[8fr_4fr]">
            <ReceiptCard receipt={p.receipt} />
            <AgentFeed items={p.feed} />
          </div>
        </>
      )}
    </div>
  );
}

export interface MarketScreenProps {
  round: RoundView | null;
  cap: number;
  lines: SellerLine[];
  lossReports: LossReport[];
  lossNote?: string;
  learning: LearningView | null;
  events: FloorEventView[];
  originCounts: { LIVE: number; MIRROR: number; SIM: number };
  connecting?: boolean;
}

export function MarketScreen(p: MarketScreenProps) {
  const c = p.originCounts;
  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="text-[18px] font-bold tracking-[-0.01em]">Market <span className="font-medium text-muted">the referee's floor</span></div>
        <div className="flex flex-wrap items-center gap-2 text-[14px] text-muted">
          {p.round && <span>{p.round.id} · {p.round.needId}</span>}
          {p.round && (p.round.state === "closed" ? <Pill tone="done">Closed</Pill> : <Pill tone="hunting">Open</Pill>)}
          {p.round && <OriginChip origin={p.round.origin} />}
        </div>
      </div>
      <p className="rounded-[10px] border border-dashed border-line px-3 py-2.5 text-[13px] text-muted">
        This is one real order, {BUYER_NAME}'s. One or two bids here are real, the rest are labelled simulated. {c.LIVE} LIVE · {c.MIRROR} MIRROR · {c.SIM} SIM.
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
            <RoundTimeline round={p.round} />
            <RefereeCard round={p.round} lines={p.lines} />
          </div>
          <SellerLines lines={p.lines} cap={p.cap} />
          <div className="grid gap-3.5 lg:grid-cols-2">
            <LossReports reports={p.lossReports} note={p.lossNote} />
            <div className="grid content-start gap-3.5">
              <SellerLearns learning={p.learning} />
              <FloorEvents events={p.events} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
