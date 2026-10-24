// web/src/components/screens.tsx
// Page bodies. The pages in app/buyer and app/market keep their hooks and pairing logic and render these.
// Both are pure: give them view models and they draw. See README for the hook-to-view mapping.
import type { CrsView } from "@/lib/crs";
import { originMixLabel, type ApprovalView, type ReviewView, type FeedItem, type FloorEventView, type GoalView, type LearningView, type LossReport, type RankedBid, type ReceiptView, type RoundView, type SellerLine, type ShieldView, type VetoView } from "@/lib/screens";
import { AgentFeed, ApprovalCard, ReviewCard, GoalCard, HeroPrice, RankedBids, ReceiptCard, ShieldCard, StatePill, VetoCard } from "./buyer";
import { FloorEvents, LossReports, RefereeCard, RoundTimeline, SellerLearns, SellerLines } from "./market";
import { Pill, SampleOnly } from "./ui";
import { DotPattern } from "./ui/dot-pattern";


export interface BuyerScreenProps {
  crs?: (sellerId: string) => CrsView | null;
  goal: GoalView | null;
  bids: RankedBid[];
  veto: VetoView | null;
  shield: ShieldView | null;
  approval: ApprovalView | null;
  /** A live mandate waiting for this buyer; when present it replaces the sample approval card. */
  review?: ReviewView | null;
  onTyped?: (mandateHash: string, code: string) => Promise<string>;
  receipt: ReceiptView | null;
  feed: FeedItem[];
  /** From the market (my_buyer_profile); the page falls back to the buyer id. */
  buyerName: string;
  /** Id of the latest round close event; a new one flips the bids open. */
  revealKey?: string;
  connecting?: boolean;
  /** Cards fed from lib/sample.ts; each shows a SIM sample chip. */
  sample?: { bids?: boolean; veto?: boolean; shield?: boolean; approval?: boolean; receipt?: boolean };
}

export function BuyerScreen(p: BuyerScreenProps) {
  const s = p.sample ?? {};
  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="flex items-center gap-2.5 text-[18px] font-bold tracking-[-0.01em]">Buyer</div>
        <div className="flex flex-wrap items-center gap-2 text-[14px] text-muted">
          <span>{p.buyerName}</span>
          {p.goal && <StatePill state={p.goal.state} />}
        </div>
      </div>

      {p.connecting ? (
        <p className="text-muted">Connecting to the market...</p>
      ) : !p.goal ? (
        <section className="card p-[18px]">
          <p className="text-[22px] font-medium">No goal yet.</p>
          <p className="mt-1 text-muted">Tell the agent what you want (&quot;RTX 5070 Ti that fits my case, under $1,300, by Friday&quot;) and it appears here with the cap and the allowance.</p>
        </section>
      ) : (
        <>
          <div className="grid gap-3.5 lg:grid-cols-[7fr_5fr]">
            <GoalCard goal={p.goal} />
            <SampleOnly on={!!s.bids}><HeroPrice bids={p.bids} cap={p.goal.cap} /></SampleOnly>
          </div>
          <SampleOnly on={!!s.bids}><RankedBids bids={p.bids} revealKey={p.revealKey} crs={p.crs} /></SampleOnly>
          <div className="grid gap-3.5 lg:grid-cols-3">
            <SampleOnly on={!!s.veto}><VetoCard veto={p.veto} /></SampleOnly>
            <SampleOnly on={!!s.shield}><ShieldCard shield={p.shield} /></SampleOnly>
            {p.review && p.onTyped ? (
              <ReviewCard review={p.review} allowance={p.goal.allowance?.perPurchase ?? null} onTyped={(c) => p.onTyped!(p.review!.mandateHash, c)} />
            ) : (
              <SampleOnly on={!!s.approval}><ApprovalCard approval={p.approval} /></SampleOnly>
            )}
          </div>
          <div className="grid gap-3.5 lg:grid-cols-[8fr_4fr]">
            <SampleOnly on={!!s.receipt}><ReceiptCard receipt={p.receipt} /></SampleOnly>
            <AgentFeed items={p.feed} />
          </div>
        </>
      )}
    </div>
  );
}

export interface MarketScreenProps {
  crs?: (sellerId: string) => CrsView | null;
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
        {/* Very faint, static, decorative; fades out before the small round text on the right. */}
        <DotPattern width={12} height={12} className="fill-line [mask-image:linear-gradient(to_right,white,transparent_40%)]" />
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
          <SampleOnly on={!!s.lines}><SellerLines lines={p.lines} cap={p.cap} crs={p.crs} /></SampleOnly>
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
