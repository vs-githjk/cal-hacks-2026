// web/src/components/screens.tsx
// Page bodies. The pages in app/buyer and app/market keep their hooks and pairing logic and render these.
// Both are pure: give them view models and they draw. See README for the hook-to-view mapping.
import { originMixLabel, roundTitle, type ApprovalView, type ReviewView, type FeedItem, type FloorEventView, type GoalView, type LearningView, type LossReport, type RankedBid, type ReceiptView, type RoundView, type SellerLine, type ShieldView, type VetoView } from "@/lib/screens";
import type { ReactNode } from "react";
import { ASI_ONE_URL } from "@/lib/agentFeed";
import { AgentFeed, ApprovalCard, ReviewCard, GoalCard, HeroPrice, RankedBids, ReceiptCard, ShieldCard, StatePill, VetoCard } from "./buyer";
import { FloorEvents, LossReports, RefereeCard, RoundTimeline, SellerLearns, SellerLines } from "./market";
import { AllowancePanel, OwnedPartsPanel, PanelPreviews } from "./panels";
import { BuildBoard } from "./BuildBoard";
import { SAMPLE_BUILD, type BuildResult } from "@/lib/build";
import { Card, Details, Label, SampleOnly, Unavailable, money } from "./ui";


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
        <Label>Searches</Label>
        <p className="text-[22px] font-medium">No search yet.</p>
        <p className="mt-1 text-muted">Post a goal above, or in <a href={ASI_ONE_URL} target="_blank" rel="noreferrer" className="font-medium text-pulse">ASI:One</a>.</p>
        <Details summary="Example"><p><q>A 1 TB NVMe drive under $90 by Friday.</q> It appears here with the cap and the allowance.</p></Details>
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

/** A journey step heading on the buyer dashboard: a number, a plain title and one muted line. */
function Step({ n, title, hint, id }: { n: number; title: string; hint?: string; id?: string }) {
  return (
    <div id={id} className="flex scroll-mt-24 items-baseline gap-3 pt-4">
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-ink font-mono text-[11px] text-canvas">{n}</span>
      <div className="min-w-0">
        <h2 className="text-[20px] font-semibold leading-6 tracking-[-0.015em]">{title}</h2>
        {hint && <p className="mt-0.5 text-[13px] leading-[18px] text-muted">{hint}</p>}
      </div>
    </div>
  );
}

export function BuyerScreen(p: BuyerScreenProps) {
  const s = p.sample ?? {};
  const goal = p.goals[0] ?? null;
  if (p.connecting) return <PanelPreviews reason="Connecting to the market. Each panel fills in when it answers." />;
  return (
    <div className="grid gap-5">
      {p.review && (
        <a href="#needs-you" className="card card-active flex flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-5">
          <span className="flex items-center gap-2.5 text-[15px] font-semibold"><span className="dot text-live" aria-hidden /> Your approval is needed. Say the code on the call.</span>
          <span className="text-[14px] font-medium text-pulse">Show the code <span aria-hidden>↓</span></span>
        </a>
      )}

      <Step n={1} title="What you asked for" hint={goal ? undefined : "Post a goal and your agent starts hunting."} />
      {goal ? <Searches goals={p.goals} /> : p.composer}

      {goal && (
        <>
          <Step n={2} title="What is happening now" hint="The latest round in the market. Bids stay sealed until it closes." />
          <SampleOnly on={!!s.bids}><HeroPrice bids={p.bids} cap={null} /></SampleOnly>
          <SampleOnly on={!!s.bids}><RankedBids bids={p.bids} revealKey={p.revealKey} /></SampleOnly>
          <SampleOnly on={!p.build}><BuildBoard build={p.build ?? SAMPLE_BUILD} origin={p.build?.origin ?? "SIM"} /></SampleOnly>
        </>
      )}

      <Step n={goal ? 3 : 2} id="needs-you" title="What needs you" hint="Above your allowance, we call you. The one-time code shows here and nowhere else." />
      {p.review ? (
        <ReviewCard review={p.review} allowance={p.allowance?.perPurchase ?? null} />
      ) : (
        <Card>
          <p className="flex items-center gap-2.5 text-[17px] font-semibold"><span className="h-2 w-2 rounded-full bg-mint-mark" aria-hidden /> Nothing needs you right now.</p>
          <p className="mt-1 text-[13px] text-muted">When a deal is above your allowance, the call starts and your code appears here.</p>
        </Card>
      )}

      {goal && (
        <>
          <Step n={4} title="What was decided, and why" hint="Every veto and block comes with its reason and source." />
          <div className={`grid items-start gap-5 ${p.review ? "lg:grid-cols-2" : "lg:grid-cols-3"}`}>
            <SampleOnly on={!!s.veto}><VetoCard veto={p.veto} /></SampleOnly>
            <SampleOnly on={!!s.shield}><ShieldCard shield={p.shield} /></SampleOnly>
            {!p.review && <SampleOnly on={!!s.approval}><ApprovalCard approval={p.approval} /></SampleOnly>}
          </div>

          <Step n={5} title="What you bought" hint="One receipt per part, in Stripe test mode." />
          <div className="grid items-start gap-5 lg:grid-cols-[7fr_5fr]">
            <SampleOnly on={!!s.receipt}><ReceiptCard receipt={p.receipt} /></SampleOnly>
            {p.purchases ?? <Unavailable title="Purchases">Not connected to this screen yet.</Unavailable>}
          </div>
        </>
      )}

      <Details summary="Your allowance, your rig and the agent log" className="mt-2">
        <div className="grid gap-5 md:grid-cols-2">
          <AllowancePanel allowance={p.allowance} cap={goal?.cap ?? null} />
          <OwnedPartsPanel />
        </div>
        <AgentFeed items={p.feed} />
      </Details>
      {goal && <Details summary="Start another goal" className="mt-0">{p.composer}</Details>}
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
