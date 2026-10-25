"use client";
// web/src/components/buyer.tsx
// Cards for the buyer screen. Each takes a view model from lib/screens.ts; none reads SpacetimeDB directly,
// so the page can feed them from hooks today and from the sample run where a table is not public yet.
import { Fragment, useEffect, useRef, useState, type PointerEvent } from "react";
import { motion, useReducedMotion } from "motion/react";
import { type ApprovalView, type FeedItem, type GoalView, type RankedBid, type ReceiptView, type ReviewView, type ShieldView, type VetoView, isWholeBuild, winningBid } from "@/lib/screens";
import { Card, Code, Label, OriginChip, Pill, SourceLink, Stat, StatusPill, Tag, Verdict, clock, money } from "./ui";
import { commas, underCap } from "@/lib/money";
import { SHIELD, SHIELD_LINE } from "@/lib/brand";

const GOAL_TYPE: Record<GoalView["type"], string> = { budget_cap: "budget cap", part_by_date: "part by date", build_by_date: "build by date" };

export function GoalCard({ goal }: { goal: GoalView }) {
  const a = goal.allowance;
  return (
    <Card tactile>
      <div className="flex items-start justify-between gap-2">
        <Label>Goal</Label>
        <StatePill state={goal.state} />
      </div>
      <p className="mb-4 text-[22px] font-medium leading-7 tracking-[-0.015em] text-balance md:text-[28px] md:leading-[34px]">
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
        <p key={s.part} className="mt-2.5 text-[13px] text-muted"><b className="font-semibold text-ink">Skipped the {s.part}.</b> {s.text}</p>
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
  const win = winningBid(bids);
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
    <Card hero className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(280px,360px)] md:items-end md:gap-8">
      <div onPointerMove={spot} onPointerLeave={unspot}>
        <Label>{win ? "Best verified price" : "Hunting"}</Label>
        {win ? (
          <>
            <div ref={field} className="relative -mx-2 px-2">
              <div className="relative z-10 my-1 text-[44px] font-medium leading-[48px] tracking-[-0.02em] tabular-nums md:text-[56px] md:leading-[60px]">{money(win.landed)}</div>
            </div>
            <div className="text-[15px] text-muted">
              <b className="font-semibold text-ink">{win.seller}</b> · {win.condition} <OriginChip origin={win.origin} />
            </div>
            {win.recommendation === "caution" && <div className="text-[15px] text-muted">Fit not confirmed on the page</div>}
          </>
        ) : (
          <div className="my-1 text-[40px] font-medium leading-[44px] tracking-[-0.02em] text-muted md:text-[48px] md:leading-[52px]">No deal yet</div>
        )}
      </div>
      <div className="grid gap-1.5 border-t border-line pt-4 text-[14px] md:border-l md:border-t-0 md:pl-6 md:pt-0">
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
      <b className="font-mono font-medium tabular-nums">{v}</b>
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
                const won = !!b.won;
                const vetoed = b.recommendation === "veto";
                const edge = won ? "border-l-[3px] border-l-mint-mark" : vetoed ? "border-l-[3px] border-l-coral-mark" : "";
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
                        play && won
                          ? { rotateX: 0, opacity: 1, boxShadow: ["inset 0 0 0 0 rgba(15,157,118,0)", "inset 0 0 0 2px rgba(15,157,118,0.6)", "inset 0 0 0 0 rgba(15,157,118,0)"] }
                          : { rotateX: 0, opacity: 1 }
                      }
                      transition={{ delay: play ? i * 0.06 : 0, duration: 0.28, ease: "easeOut", boxShadow: { delay: bids.length * 0.06 + 0.3, duration: 0.9 } }}
                      className={`cursor-pointer outline-none transition-colors duration-150 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-pulse ${won ? "bg-mint-soft/60" : `hover:bg-surface-2 ${out ? "text-muted" : ""}`}`}
                    >
                      <Td className={`font-mono font-semibold ${edge} ${won ? "text-mint" : "text-muted"}`}>{b.rank ?? (b.recommendation === "refused" ? "ref" : "out")}</Td>
                      <Td><span className="font-semibold text-ink">{b.seller}</span> <OriginChip origin={b.origin} />{won && <> <Tag>Winner</Tag></>}</Td>
                      <Td>
                        <Tag>{b.condition}</Tag>
                        {b.altLines?.map((l) => <span key={l.condition} className="ml-1.5 text-[13px] tabular-nums text-muted">{l.condition} {money(l.unitPrice)}</span>)}
                      </Td>
                      <Td right className={struck}>{won ? <b>{money(b.landed)}</b> : money(b.landed)}</Td>
                      <Td><Verdict kind={b.heldBack ? "caution" : REC[b.recommendation].kind}>{b.heldBack ? "Held back" : REC[b.recommendation].text}</Verdict></Td>
                      <Td className="max-w-[26ch] truncate text-[13px] text-muted">{b.why}</Td>
                    </motion.tr>
                    {expanded && (
                      <tr className={won ? "bg-mint-soft" : "bg-soft"}>
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
  return <th className={`whitespace-nowrap border-b border-line px-2.5 pb-2 pt-1.5 text-[12px] font-medium uppercase tracking-[0.04em] text-muted ${right ? "text-right" : "text-left"}`}>{children}</th>;
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
    return <Card stripe="ink"><Label>{SHIELD}</Label><p className="text-[15px] font-medium">{SHIELD_LINE}</p><p className="mt-1 text-[13px] text-muted">Every seller message is screened before the advocate reads it. Blocks show here with the rule that fired.</p></Card>;
  }
  const blocked = shield.verdict !== "allow";
  return (
    <Card stripe="ink">
      <Label>{SHIELD}</Label>
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill tone={blocked ? "bad" : "good"}>{blocked ? `Failed the ${SHIELD}` : `Passed the ${SHIELD}`}</StatusPill>
        <span className="text-[15px] font-medium">{blocked ? "Blocked before the advocate saw it" : "Allowed"}</span>
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
        <div className="mt-3 overflow-hidden rounded-xl bg-surface-2 px-3.5 py-3 font-mono text-[12px] leading-[1.5] [overflow-wrap:anywhere]">
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

/** The spoken code in a well, the way the approval call shows it (design system v2 ApprovalCall). */
function CodeWell({ code, caption }: { code: string; caption: string }) {
  return (
    <div className="my-4 rounded-xl bg-surface-2 px-4 py-4 text-center">
      <div className="mb-1.5 text-[12px] font-medium uppercase tracking-[0.06em] text-muted">{caption}</div>
      <div className="font-mono text-[26px] font-medium leading-8 tracking-[0.04em] md:text-[28px]">{code}</div>
    </div>
  );
}

export function ApprovalCard({ approval }: { approval: ApprovalView | null }) {
  if (!approval) {
    return (
      <Card stripe="amber">
        <Label>Approval call</Label>
        <p className="text-[15px] font-medium">Nothing to approve.</p>
        <p className="mt-1 text-[13px] text-muted">Any buy above your allowance calls you. The one-time code appears here, on this screen only.</p>
      </Card>
    );
  }
  const done = approval.attempts.some((a) => a.approved);
  return (
    <Card stripe="amber" active={!done && !approval.within}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Approval call</Label>
        {approval.within ? <StatusPill tone="good">Within allowance, no call</StatusPill> : done ? <StatusPill tone="good">Approved by phone</StatusPill> : <StatusPill tone="live" pulse>Calling you</StatusPill>}
      </div>
      <p className="text-[22px] font-medium leading-7 tracking-[-0.015em] tabular-nums text-balance">
        {approval.within ? `${money(approval.amount)} to ${approval.payee}, within your allowance` : `${money(approval.amount)} is above your ${money(approval.allowance)} allowance`}
      </p>
      {approval.wordPair && (
        <>
          <CodeWell code={approval.wordPair} caption={'Say this word pair, then "approve"'} />
          <p className="text-[13px] font-medium">We never ask for anything but the code on this screen.</p>
          <p className="mt-0.5 text-[13px] text-muted">One-time code, this screen only · {done ? "expired" : "expires"} {clock(approval.codeExpiresAt)}</p>
        </>
      )}
      {approval.whyAnswer && <p className="mt-3 text-[14px] text-ink-2">You asked &quot;why not the cheaper one?&quot; It answered: {approval.whyAnswer}</p>}
      <p className="mt-2 text-[13px] text-muted">{CAP_RULE}</p>
      {approval.attempts.length > 0 && (
        <ol className="mt-3 grid gap-2">
          {approval.attempts.map((a, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2.5 rounded-xl border border-line px-3 py-2.5 text-[13px]">
              <span className="font-mono text-[12px] text-muted">{clock(a.at)}</span>
              <StatusPill tone={a.approved ? "good" : "bad"}>{a.label}</StatusPill>
              <span className="min-w-0">{a.said}</span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export const CAP_RULE = "Goal cap is the ceiling to hunt under. Allowance is what it may spend without a call.";

/** Live b5 review card (the v2 ApprovalCall): the word pair issued for this exact mandate. Only the phone call approves (#191, LOCKED): no typed fallback. */
export function ReviewCard({ review, allowance }: { review: ReviewView; allowance: number | null }) {
  return (
    <Card active>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusPill tone="live" pulse>Calling you</StatusPill>
        <span className="font-mono text-[12px] text-muted">expires {clock(review.expiry)}</span>
      </div>
      <p className="mt-4 text-[26px] font-medium leading-8 tracking-[-0.02em] tabular-nums text-balance md:text-[32px] md:leading-9">
        {money(review.amount)} {allowance === null ? "needs your approval" : `is above your ${money(allowance)} allowance`}
      </p>
      <p className="mt-2 text-[15px] leading-5 text-ink-2">
        To {review.payee} <OriginChip origin={review.origin} /> · {isWholeBuild(review) ? "one call approves the whole build" : <>mandate <Code>{review.mandateId}</Code></>}
      </p>
      <CodeWell code={review.code} caption={'Say this code on the call, then "approve"'} />
      <p className="text-[13px] font-medium">Only the call approves; nothing on this screen can. We never ask for anything but this code.</p>
      <p className="mt-1 text-[13px] text-muted">Single use, bound to {isWholeBuild(review) ? "this call" : "this one mandate"}. Silence, a hang-up or a mismatch denies. {CAP_RULE}</p>
    </Card>
  );
}

export function ReceiptCard({ receipt }: { receipt: ReceiptView | null }) {
  if (!receipt) {
    return (
      <Card stripe="mint">
        <Label>Receipt</Label>
        <p className="text-[15px] font-medium">No purchases yet.</p>
        <p className="mt-1 text-[13px] text-muted">Nothing is paid until you approve. The signed mandate and the charge land here.</p>
      </Card>
    );
  }
  const total = receipt.amount + (receipt.shipping ?? 0);
  return (
    <Card stripe="mint">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Receipt{receipt.item ? ` · ${receipt.item}` : ""}</Label>
        <span className="flex items-center gap-1.5">
          <StatusPill tone="good">{receipt.chargeStatus || "Paid"}</StatusPill>
          <OriginChip origin={receipt.chargeOrigin ?? "SIM"} />
        </span>
      </div>
      <div className="flex items-center gap-3">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-mint-soft text-[14px] text-mint motion-safe:animate-[pop_420ms_var(--ease-out)_both]" aria-hidden>✓</span>
        <span className="text-[40px] font-medium leading-[44px] tracking-[-0.02em] tabular-nums md:text-[48px] md:leading-[52px]">{money(total)}</span>
      </div>
      <p className="mt-1.5 text-[15px] text-ink-2">{[receipt.seller, receipt.item, receipt.condition].filter(Boolean).join(" · ")}</p>
      <dl className="mt-3 text-[14px]">
        <Line k="Item" v={money(receipt.amount)} />
        {receipt.shipping !== undefined && <Line k="Shipping" v={money(receipt.shipping)} />}
        <Line k="Charge" v={<>{receipt.chargeId} · {receipt.paymentMethod} · {clock(receipt.paidAt)}</>} />
        <Line k="Mandate" v={<>{receipt.mandateId} · expires {clock(receipt.mandateExpires)} <OriginChip origin={receipt.mandateOrigin} /></>} />
        <Line k="Hash" v={`${receipt.mandateHash.slice(0, 8)}…${receipt.mandateHash.slice(-6)}`} />
        {receipt.signature && <Line k="Signature" v={receipt.signature} />}
        {receipt.replayRefused !== undefined && <Line k="Replay" v={receipt.replayRefused ? "same mandate sent twice; second charge refused" : "not tested"} />}
        <Line k="Allowance" v="unchanged until the receiving check passes" />
      </dl>
      <p className="mt-3 rounded-xl bg-surface-2 px-3.5 py-3 text-[13px] text-ink-2">Stripe test mode. No real money moved. A replayed or altered mandate fails, and a retry cannot charge twice.</p>
    </Card>
  );
}

function Line({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-line py-2.5 first:border-t-0">
      <dt className="shrink-0 text-muted">{k}</dt>
      <dd className="min-w-0 text-right font-mono text-[13px] tabular-nums [overflow-wrap:anywhere]">{v}</dd>
    </div>
  );
}

const FEED_STYLE: Record<FeedItem["kind"], string> = { deal: "text-mint", bid: "text-pulse", veto: "text-coral", block: "text-coral", progress: "text-muted" };

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
                <span className={`mb-0.5 block text-[11px] font-medium uppercase tracking-[0.06em] ${FEED_STYLE[f.kind]}`}>{f.title}</span>
                {f.text} {f.origin && <OriginChip origin={f.origin} />}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
