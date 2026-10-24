"use client";
// web/src/components/buyer.tsx
// Cards for the buyer screen. Each takes a view model from lib/screens.ts; none reads SpacetimeDB directly,
// so the page can feed them from hooks today and from the sample run where a table is not public yet.
import { Fragment, useEffect, useRef, useState, type PointerEvent } from "react";
import { motion, useReducedMotion } from "motion/react";
import { type ApprovalView, type FeedItem, type GoalView, type RankedBid, type ReceiptView, type ReviewView, type ShieldView, type VetoView } from "@/lib/screens";
import { Card, Code, Label, OriginChip, Pill, SourceLink, Stat, Tag, Verdict, clock, money } from "./ui";
import { commas, underCap } from "@/lib/money";

const GOAL_TYPE: Record<GoalView["type"], string> = { budget_cap: "budget cap", part_by_date: "part by date", build_by_date: "build by date" };

export function GoalCard({ goal }: { goal: GoalView }) {
  const a = goal.allowance;
  return (
    <Card tactile>
      <div className="flex items-start justify-between gap-2">
        <Label>Goal</Label>
        <StatePill state={goal.state} />
      </div>
      <p className="mb-3 text-[22px] font-medium leading-[1.3] tracking-[-0.01em] text-balance">
        <q>{goal.text}</q>
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {goal.conditions.map((c) => <Tag key={c}>{c}</Tag>)}
        {goal.variant && <Tag>{goal.variant}</Tag>}
        <OriginChip origin={goal.origin} />
        <span className="text-[13px] text-muted">{GOAL_TYPE[goal.type]}</span>
      </div>
      <dl className="mt-3.5 grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Stat label="Cap" value={money(goal.cap)} />
        <Stat
          label="Allowance per buy"
          value={a ? money(a.perPurchase) : money(0)}
          sub={a && a.perPurchase > 0 ? `${money(a.spent)} of ${money(a.periodLimit)} this ${a.period}, step ${a.ladderStep}` : "every buy calls you first"}
        />
        <Stat label="Deadline" value={goal.deadline.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })} />
        <Stat label="Reserved" value={money(goal.reserved)} sub={goal.state === "DONE" ? "released after payment" : undefined} />
      </dl>
      {goal.skipped.map((s) => (
        <p key={s} className="mt-2.5 text-[13px] text-muted"><b className="font-semibold text-ink">Skipped the PSU.</b> {s}</p>
      ))}
    </Card>
  );
}

export function StatePill({ state }: { state: GoalView["state"] }) {
  if (state === "DONE") return <Pill tone="done">Done</Pill>;
  if (state === "HOLD_FOR_CALL") return <Pill tone="hold">Hold for call</Pill>;
  return <Pill tone="hunting">{state.toLowerCase().replaceAll("_", " ")}</Pill>;
}

/** The one hero number on the buyer screen. Empty state when no round has closed yet. */
export function HeroPrice({ bids, cap }: { bids: RankedBid[]; cap?: number | null }) {
  const win = bids.find((b) => b.won);
  const vetoed = bids.filter((b) => b.recommendation === "veto").length;
  const ineligible = bids.filter((b) => b.recommendation === "ineligible").length;
  const refused = bids.filter((b) => b.recommendation === "refused").length;
  const field = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const spot = (e: PointerEvent) => {
    const el = field.current;
    if (!el || reduce || window.innerWidth < 640) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  };
  const unspot = () => {
    field.current?.style.removeProperty("--mx");
    field.current?.style.removeProperty("--my");
  };
  return (
    <Card hero tactile className="flex flex-col justify-between">
      <div onPointerMove={spot} onPointerLeave={unspot}>
        <Label>{win ? "Best verified price" : "Hunting"}</Label>
        {win ? (
          <>
            <div ref={field} className="relative -mx-2 px-2">
              <div className="relative z-10 my-1 font-display text-[clamp(48px,6vw,76px)] leading-none tracking-[-0.01em] tabular-nums">{money(win.landed)}</div>
            </div>
            <div className="text-[15px] text-muted">
              <b className="font-semibold text-ink">{win.seller}</b> · {win.condition} <OriginChip origin={win.origin} />
            </div>
            {win.recommendation === "caution" && <div className="text-[15px] text-muted">Fit not confirmed on the page</div>}
          </>
        ) : (
          <div className="my-1 font-display text-[clamp(40px,5vw,64px)] leading-none text-muted">no deal yet</div>
        )}
      </div>
      <div className="mt-3.5 grid gap-1 border-t border-line pt-3 text-[14px]">
        <Row k="Cheaper bids vetoed with a source" v={String(vetoed)} />
        <Row k="Ineligible (condition unknown, over cap)" v={String(ineligible)} />
        <Row k="Refused by the referee (below floor)" v={String(refused)} />
        {win && underCap(cap, win.landed) !== null && <Row k="Under your cap by" v={money(underCap(cap, win.landed)!)} />}
      </div>
    </Card>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <span className="flex justify-between gap-2.5">
      <span className="text-muted">{k}</span>
      <b className="font-semibold tabular-nums">{v}</b>
    </span>
  );
}

const REC: Record<RankedBid["recommendation"], { kind: "veto" | "caution" | "buy" | "out"; text: string }> = {
  veto: { kind: "veto", text: "Vetoed" },
  caution: { kind: "caution", text: "Buy, caution" },
  buy: { kind: "buy", text: "Buy" },
  ineligible: { kind: "out", text: "Ineligible" },
  refused: { kind: "out", text: "Refused" },
  unchecked: { kind: "out", text: "No card yet" },
};

/**
 * Ranked bids. Hover tints a row, click or Enter expands its Why with the source and the market row it came from.
 * When a new round close arrives (revealKey changes), the rows flip open in rank order, 60 ms apart, and the winner pulses once.
 */
export function RankedBids({ bids, roundLabel = "Sealed round 1", revealKey }: { bids: RankedBid[]; roundLabel?: string; revealKey?: string }) {
  const reduce = useReducedMotion();
  const [open, setOpen] = useState<string | null>(null);
  const [play, setPlay] = useState(0);
  const seen = useRef(revealKey);
  useEffect(() => {
    if (revealKey && seen.current !== undefined && revealKey !== seen.current && !reduce) setPlay((n) => n + 1);
    seen.current = revealKey;
  }, [revealKey, reduce]);
  const toggle = (k: string) => setOpen((o) => (o === k ? null : k));
  return (
    <Card tactile>
      <Label>{roundLabel} · ranked by quality-adjusted landed price</Label>
      {bids.length === 0 ? (
        <p className="text-muted">Bids are sealed until the round closes. Nobody, not even you, sees them before then.</p>
      ) : (
        <div className="-mx-[18px] overflow-x-auto px-[18px] [perspective:900px]">
          <table className="w-full border-collapse text-[14px] tabular-nums">
            <thead>
              <tr>
                <Th>#</Th><Th>Seller</Th><Th>Condition</Th><Th right>Landed price</Th><Th>Advocate</Th><Th>Why</Th>
              </tr>
            </thead>
            <tbody>
              {bids.map((b, i) => {
                const k = b.rowRef ?? `${b.seller}|${b.condition}`;
                const out = b.rank === null;
                const struck = b.recommendation === "veto" ? "line-through text-muted" : "";
                const expanded = open === k;
                return (
                  <Fragment key={`${k}-${play}`}>
                    <motion.tr
                      tabIndex={0}
                      role="button"
                      aria-expanded={expanded}
                      onClick={() => toggle(k)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          toggle(k);
                        }
                      }}
                      initial={play ? { rotateX: -90, opacity: 0 } : false}
                      animate={
                        play && b.won
                          ? { rotateX: 0, opacity: 1, boxShadow: ["inset 0 0 0 0 rgba(255,255,255,0)", "inset 0 0 0 2px rgba(255,255,255,0.55)", "inset 0 0 0 0 rgba(255,255,255,0)"] }
                          : { rotateX: 0, opacity: 1 }
                      }
                      transition={{ delay: play ? i * 0.06 : 0, duration: 0.28, ease: "easeOut", boxShadow: { delay: bids.length * 0.06 + 0.3, duration: 0.9 } }}
                      className={`cursor-pointer outline-none transition-colors duration-150 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent ${b.won ? "bg-mint-soft" : `hover:bg-soft ${out ? "text-muted" : ""}`}`}
                    >
                      <Td className={`font-mono font-semibold ${b.won ? "text-mint" : "text-muted"}`}>{b.rank ?? (b.recommendation === "refused" ? "ref" : "out")}</Td>
                      <Td><span className="font-semibold text-ink">{b.seller}</span> <OriginChip origin={b.origin} />{b.won && <> <Tag>Winner</Tag></>}</Td>
                      <Td>
                        <Tag>{b.condition}</Tag>
                        {b.altLines?.map((l) => <span key={l.condition} className="ml-1.5 text-[13px] tabular-nums text-muted">{l.condition} {money(l.unitPrice)}</span>)}
                      </Td>
                      <Td right className={struck}>{b.won ? <b>{money(b.landed)}</b> : money(b.landed)}</Td>
                      <Td><Verdict kind={b.heldBack ? "caution" : REC[b.recommendation].kind}>{b.heldBack ? "Held back" : REC[b.recommendation].text}</Verdict></Td>
                      <Td className="max-w-[26ch] truncate text-[13px] text-muted">{b.why}</Td>
                    </motion.tr>
                    {expanded && (
                      <tr className={b.won ? "bg-mint-soft" : "bg-soft"}>
                        <td colSpan={6} className="border-b border-line px-2.5 pb-3 pt-1 text-[13px]">
                          <p>{b.why || "No reason recorded."}</p>
                          <p className="mt-1 text-muted">
                            {b.sourceUrl ? <>Source <SourceLink href={b.sourceUrl} /> · </> : "No source link · "}
                            {b.rowRef ? <>market row <Code>{b.rowRef}</Code></> : <>sample row, not from this market <OriginChip origin="SIM" /></>}
                          </p>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`whitespace-nowrap border-b border-line px-2.5 pb-2 pt-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-muted ${right ? "text-right" : "text-left"}`}>{children}</th>;
}
function Td({ children, right, className = "" }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={`border-b border-line p-2.5 align-top ${right ? "whitespace-nowrap text-right" : ""} ${className}`}>{children}</td>;
}

export function VetoCard({ veto }: { veto: VetoView | null }) {
  if (!veto) {
    return (
      <Card stripe="coral"><Label>Advocate veto</Label><p className="text-muted">No veto yet. When the cheapest bid is a trap, the reason and its source land here.</p></Card>
    );
  }
  return (
    <Card stripe="coral">
      <Label>Advocate veto</Label>
      <h3 className="mb-1.5 text-[17px] font-semibold tracking-[-0.01em] tabular-nums">Bid vetoed: {veto.seller}{veto.landed ? `, ${money(veto.landed)}` : ""}</h3>
      <p className="text-[14px]">{veto.claim ? <>Listed as &quot;{veto.claim}&quot;. </> : null}{veto.finding}</p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-muted">Rule</dt><dd><Code>{veto.ruleId}</Code></dd>
        <dt className="text-muted">Source</dt><dd className="min-w-0"><SourceLink href={veto.sourceUrl} /></dd>
        <dt className="text-muted">Checked</dt><dd>{clock(veto.checkedAt)} · claim check <OriginChip origin={veto.checkOrigin} /></dd>
      </dl>
    </Card>
  );
}

export function ShieldCard({ shield }: { shield: ShieldView | null }) {
  if (!shield) {
    return <Card stripe="ink"><Label>Bazaar Shield</Label><p className="text-muted">Every seller message is screened before the advocate reads it. Blocks show here with the rule that fired.</p></Card>;
  }
  const blocked = shield.verdict !== "allow";
  return (
    <Card stripe="ink">
      <Label>Bazaar Shield</Label>
      <div className={`text-[15px] font-bold ${blocked ? "text-coral" : "text-mint"}`}>
        {blocked ? "Blocked before the advocate saw it" : "Allowed"}
      </div>
      <p className="mt-1.5 text-[13px] text-muted">
        {[
          `${blocked ? "Injected listing" : "Listing"} from ${shield.seller}`,
          shield.chars !== undefined && `${commas(shield.chars)} chars`,
          shield.latencyMs !== undefined && `${shield.latencyMs.toFixed(1)} ms`,
          shield.severity && `severity ${shield.severity}`,
        ].filter(Boolean).join(" · ")}
      </p>
      {shield.evidence.length > 0 && (
        <div className="mt-2.5 overflow-hidden rounded-[10px] border border-line bg-soft px-3 py-2.5 font-mono text-[12px] leading-[1.5] [overflow-wrap:anywhere]">
          {shield.evidence.map((e, i) => (e.hit ? <mark key={i} className="rounded-[3px] bg-coral-soft px-0.5 text-coral">{e.text}</mark> : <span key={i}>{e.text}</span>))}
        </div>
      )}
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {shield.ruleIds.slice(0, 5).map((r) => <span key={r} className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-muted">{r}</span>)}
        {shield.ruleIds.length > 5 && <span className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-muted">+{shield.ruleIds.length - 5} more</span>}
      </div>
      <p className="mt-2 text-[13px] text-muted">
        {shield.control && <>Control page ({shield.control.name}, same SKU) {shield.control.verdict} in {shield.control.latencyMs.toFixed(1)} ms. </>}
        <OriginChip origin={shield.pageOrigin} /> page, <OriginChip origin={shield.verdictOrigin} /> verdict{shield.version ? ` from ${shield.version}` : ""}.
      </p>
    </Card>
  );
}

export function ApprovalCard({ approval }: { approval: ApprovalView | null }) {
  if (!approval) {
    return <Card stripe="amber"><Label>Approval call</Label><p className="text-muted">Any buy above your allowance calls you. The one-time code appears here, on this screen only.</p></Card>;
  }
  const done = approval.attempts.some((a) => a.approved);
  return (
    <Card stripe="amber">
      <Label>Approval call</Label>
      <h3 className="mb-1.5 text-[17px] font-semibold tracking-[-0.01em] tabular-nums">
        {approval.within ? `${money(approval.amount)} to ${approval.payee}, within your allowance` : `${money(approval.amount)} is above your ${money(approval.allowance)} allowance, so it called`}
      </h3>
      {approval.wordPair && (
        <>
          <div className="my-2.5 flex flex-wrap items-baseline gap-2.5">
            <span className="font-display text-[clamp(32px,4vw,44px)] leading-none tracking-[0.01em]">{approval.wordPair}</span>
            <small className="text-[12px] text-muted">one-time code, this screen only · {done ? "expired" : "expires"} {clock(approval.codeExpiresAt)}</small>
          </div>
          <p className="text-[13px] font-semibold">We never ask for anything but the code on this screen.</p>
        </>
      )}
      {approval.whyAnswer && <p className="mt-1.5 text-[14px]">You asked &quot;why not the cheaper one?&quot; It answered: {approval.whyAnswer}</p>}
      <p className="mt-1.5 text-[13px] text-muted">{CAP_RULE}</p>
      <ol className="mt-2.5 grid gap-1.5 text-[13px]">
        {approval.attempts.map((a, i) => (
          <li key={i} className="grid grid-cols-[auto_auto_1fr] items-baseline gap-2.5">
            <span className="font-mono text-[12px] text-muted">{clock(a.at)}</span>
            <span className={`font-semibold ${a.approved ? "text-mint" : "text-coral"}`}>{a.label}</span>
            <span>{a.said}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export const CAP_RULE = "Goal cap is the ceiling to hunt under. Allowance is what it may spend without a call.";

/** Live b5 review card: the word pair issued for this exact mandate. Only the phone call approves (#191, LOCKED): no typed fallback. */
export function ReviewCard({ review, allowance }: { review: ReviewView; allowance: number | null }) {
  return (
    <Card stripe="amber">
      <Label>Review and approve</Label>
      <h3 className="mb-1.5 text-[17px] font-semibold tracking-[-0.01em] tabular-nums">
        {money(review.amount)} to {review.payee} <OriginChip origin={review.origin} />
      </h3>
      <p className="text-[13px] tabular-nums text-muted">
        Mandate <Code>{review.mandateId}</Code> · {allowance === null ? "no allowance set" : `above your ${money(allowance)} allowance`}, so it calls you · expires {clock(review.expiry)}
      </p>
      <div className="my-2.5 flex flex-wrap items-baseline gap-2.5">
        <span className="font-display text-[clamp(32px,4vw,44px)] leading-none tracking-[0.01em]">{review.code}</span>
        <small className="text-[12px] text-muted">one-time code for this mandate, this screen only</small>
      </div>
      <p className="text-[13px] font-semibold">Say this code on the call. Only the call approves; nothing on this screen can.</p>
      <p className="mt-1 text-[13px] text-muted">{CAP_RULE}</p>
    </Card>
  );
}

export function ReceiptCard({ receipt }: { receipt: ReceiptView | null }) {
  if (!receipt) {
    return <Card stripe="mint"><Label>Receipt</Label><p className="text-muted">Nothing is paid until you approve. The signed mandate and charge show here.</p></Card>;
  }
  return (
    <Card stripe="mint">
      <Label>Receipt</Label>
      <div className="flex flex-wrap items-center gap-2">
        <span className="motion-safe:animate-[pop_.4s_ease-out] inline-flex h-[22px] w-[22px] items-center justify-center rounded-full bg-mint text-[13px] font-bold text-mint-soft" aria-hidden>✓</span>
        <h3 className="m-0 text-[17px] font-semibold tracking-[-0.01em]">Paid under a signed mandate</h3>
        <OriginChip origin={receipt.chargeOrigin ?? "SIM"} label={receipt.chargeStatus} />
      </div>
      <div className="mt-2 grid gap-3.5 md:grid-cols-2">
        <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-[14px] tabular-nums">
          <div>{[receipt.seller, receipt.item, receipt.condition].filter(Boolean).join(" · ")}</div><div>{money(receipt.amount)}</div>
          {receipt.shipping !== undefined && <><div className="text-muted">Shipping</div><div className="text-muted">{money(receipt.shipping)}</div></>}
          <div className="border-t border-line pt-2 text-[18px] font-bold">Charged</div><div className="border-t border-line pt-2 text-[18px] font-bold">{money(receipt.amount + (receipt.shipping ?? 0))}</div>
          <div className="text-[13px] text-muted">{receipt.paymentMethod} · {receipt.chargeId}</div><div className="text-[13px] text-muted">{clock(receipt.paidAt)}</div>
        </dl>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
          <dt className="text-muted">Mandate</dt><dd className="min-w-0 [overflow-wrap:anywhere]"><Code>{receipt.mandateId}</Code> · expires {clock(receipt.mandateExpires)} · <OriginChip origin={receipt.mandateOrigin} /></dd>
          <dt className="text-muted">Hash</dt><dd><Code>{receipt.mandateHash.slice(0, 8)}…{receipt.mandateHash.slice(-6)}</Code></dd>
          {receipt.signature && <><dt className="text-muted">Signature</dt><dd>{receipt.signature}</dd></>}
          {receipt.replayRefused !== undefined && <><dt className="text-muted">Replay</dt><dd>{receipt.replayRefused ? <><Verdict kind="veto">Refused</Verdict> same mandate sent twice; second charge rejected</> : "not tested"}</dd></>}
          <dt className="text-muted">Allowance</dt><dd>unchanged until the receiving check passes</dd>
        </dl>
      </div>
    </Card>
  );
}

const FEED_STYLE: Record<FeedItem["kind"], string> = { deal: "text-mint", bid: "text-sky", veto: "text-coral", block: "text-coral", progress: "text-muted" };

export function AgentFeed({ items, max = 40 }: { items: FeedItem[]; max?: number }) {
  return (
    <Card>
      <Label>What the agent did</Label>
      {items.length === 0 ? (
        <p className="text-muted">Nothing yet. Every step the agent takes shows up here.</p>
      ) : (
        <ol className="grid">
          {items.slice(0, max).map((f) => (
            <li key={f.key} className="grid grid-cols-[72px_1fr] items-baseline gap-2.5 border-b border-line py-2 text-[14px] last:border-b-0">
              <span className="font-mono text-[12px] text-muted">{clock(f.at)}</span>
              <span className="min-w-0 [overflow-wrap:anywhere]">
                <span className={`mb-px block text-[11px] font-bold uppercase tracking-[0.06em] ${FEED_STYLE[f.kind]}`}>{f.title}</span>
                {f.text} {f.origin && <OriginChip origin={f.origin} />}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
