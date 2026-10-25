"use client";
// web/src/components/buyer.tsx
// Cards for the buyer screen. Each takes a view model from lib/screens.ts; none reads SpacetimeDB directly,
// so the page can feed them from hooks today and from the sample run where a table is not public yet.
import { Fragment, createContext, useContext, useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { type ApprovalView, type BuyerKpi, type FeedItem, type KpiDot, type GoalView, type RankedBid, type ReceiptView, type ReviewView, type ShieldView, type VetoView, isWholeBuild, stateLabel, winningBid } from "@/lib/screens";
import { Card, Code, Details, Label, OriginChip, SourceLink, Tag, Verdict, clock, money } from "./ui";
import { commas, underCap } from "@/lib/money";
import { SHIELD } from "@/lib/brand";

/** When every row on the page is SIM the shell already says so; then only a row that is not SIM gets its own chip. */
export const QuietOrigin = createContext(false);
function Chip({ origin, label }: { origin: string; label?: string }) {
  const quiet = useContext(QuietOrigin);
  if (quiet && origin === "SIM") return null;
  return <OriginChip origin={origin} label={label} />;
}



const DOT_CLASS = { live: "bg-live", mint: "bg-mint-mark", muted: "bg-muted" } as const;

/** A status as a small dot and a plain word, never a filled pill. */
export function StatusDot({ dot, children }: { dot: KpiDot; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] text-muted">
      <span className={`size-2 shrink-0 rounded-full ${DOT_CLASS[dot]}`} aria-hidden />
      {children}
    </span>
  );
}

export function StatePill({ state }: { state: GoalView["state"] }) {
  const dot: KpiDot = state === "DONE" ? "mint" : state === "EXPIRED" || state === "FAILED" || state === "PAUSED" ? "muted" : "live";
  return <StatusDot dot={dot}>{stateLabel(state)}</StatusDot>;
}

/** One KPI: a muted label, one bold value, one muted line and an optional status dot. The whole card links to its section. */
export function KpiCard({ kpi }: { kpi: BuyerKpi }) {
  return (
    <a href={kpi.href} className="card flex min-w-0 flex-col gap-1 p-3 sm:gap-1.5 sm:p-4 transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-pulse md:p-5">
      <span className="text-[13px] text-muted">{kpi.label}</span>
      <span className="truncate text-[20px]/[26px] font-semibold tabular-nums tracking-[-0.01em] text-ink sm:text-[22px]/[28px]">{kpi.value}</span>
      <span className="text-[13px] leading-[18px] text-muted">{kpi.line}</span>
      {kpi.dot && kpi.word && <StatusDot dot={kpi.dot}>{kpi.word}</StatusDot>}
    </a>
  );
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
    <Card hero className="flex flex-col justify-between">
      <div onPointerMove={spot} onPointerLeave={unspot}>
        <Label>{win ? "Best price" : "Hunting"}</Label>
        {win ? (
          <>
            <div ref={field} className="relative -mx-2 px-2">
              <div className="relative z-10 my-1 text-[clamp(44px,5vw,56px)] font-medium leading-[1.08] tracking-[-0.025em] tabular-nums">{money(win.landed)}</div>
            </div>
            <div className="text-[15px] text-muted">
              <b className="font-semibold text-ink">{win.seller}</b> · {win.condition} <Chip origin={win.origin} />
            </div>
            {win.recommendation === "caution" && <div className="text-[15px] text-muted">Fit not confirmed on the page</div>}
          </>
        ) : (
          <div className="my-1 text-[clamp(36px,4vw,48px)] font-medium leading-none tracking-[-0.02em] text-muted">no deal yet</div>
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
    <Card>
      <Label>{roundLabel}</Label>
      <Details summary="How bids are ranked" className="mb-3 mt-0"><p>Ranked by quality-adjusted landed price: the referee applies one fixed rule, ties break in a fixed order, and the seller fee never enters the ranking.</p></Details>
      {bids.length === 0 ? (
        <p className="text-muted">Sealed until the round closes.</p>
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
                const edge = won ? "border-l-[3px] border-l-mint" : vetoed ? "border-l-[3px] border-l-coral" : "";
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
                          ? { rotateX: 0, opacity: 1, boxShadow: ["inset 0 0 0 0 rgba(30,78,216,0)", "inset 0 0 0 2px rgba(30,78,216,0.5)", "inset 0 0 0 0 rgba(30,78,216,0)"] }
                          : { rotateX: 0, opacity: 1 }
                      }
                      transition={{ delay: play ? i * 0.06 : 0, duration: 0.28, ease: "easeOut", boxShadow: { delay: bids.length * 0.06 + 0.3, duration: 0.9 } }}
                      className={`cursor-pointer outline-none transition-colors duration-150 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-pulse ${won ? "bg-mint-soft" : `hover:bg-surface-2 ${out ? "text-muted" : ""}`}`}
                    >
                      <Td className={`font-mono font-semibold ${edge} ${won ? "text-mint" : "text-muted"}`}>{b.rank ?? (b.recommendation === "refused" ? "ref" : "out")}</Td>
                      <Td><span className="font-semibold text-ink">{b.seller}</span> <Chip origin={b.origin} />{won && <> <Tag>Winner</Tag></>}</Td>
                      <Td>
                        <Tag>{b.condition}</Tag>
                        {b.altLines?.map((l) => <span key={l.condition} className="ml-1.5 text-[13px] tabular-nums text-muted">{l.condition} {money(l.unitPrice)}</span>)}
                      </Td>
                      <Td right className={struck}>{won ? <b>{money(b.landed)}</b> : b.landed > 0 ? money(b.landed) : "·"}</Td>
                      <Td><Verdict kind={b.heldBack ? "caution" : REC[b.recommendation].kind}>{b.heldBack ? "Held back" : REC[b.recommendation].text}</Verdict></Td>
                      <Td className="max-w-[26ch] truncate text-[13px] text-muted">{b.why}</Td>
                    </motion.tr>
                    {expanded && (
                      <tr className={won ? "bg-mint-soft" : "bg-surface-2"}>
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
  return <th className={`whitespace-nowrap border-b border-line px-2.5 pb-2 pt-1.5 text-[12px]/[16px] font-medium text-muted ${right ? "text-right" : "text-left"}`}>{children}</th>;
}
function Td({ children, right, className = "" }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={`border-b border-line p-2.5 align-top ${right ? "whitespace-nowrap text-right" : ""} ${className}`}>{children}</td>;
}

export function VetoCard({ veto }: { veto: VetoView | null }) {
  if (!veto) {
    return (
      <Card stripe="coral"><Label>Veto</Label><p className="text-muted">No veto yet. Traps land here with their source.</p></Card>
    );
  }
  return (
    <Card stripe="coral">
      <Label>Veto</Label>
      <h3 className="mb-1.5 text-[17px]/[22px] font-semibold tabular-nums">Bid vetoed: {veto.seller}{veto.landed ? `, ${money(veto.landed)}` : ""}</h3>
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
    return <Card stripe="ink"><Label>{SHIELD}</Label><p className="text-muted">Every listing is screened first. Blocks land here.</p></Card>;
  }
  const blocked = shield.verdict !== "allow";
  return (
    <Card stripe="ink">
      <Label>{SHIELD}</Label>
      <div className={`text-[15px] font-semibold ${blocked ? "text-coral" : "text-mint"}`}>
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
        <div className="mt-2.5 overflow-hidden rounded-xl bg-surface-2 px-3 py-2.5 font-mono text-[12px] leading-[1.5] [overflow-wrap:anywhere]">
          {shield.evidence.map((e, i) => (e.hit ? <mark key={i} className="rounded-[3px] bg-coral-soft px-0.5 text-coral">{e.text}</mark> : <span key={i}>{e.text}</span>))}
        </div>
      )}
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {shield.ruleIds.slice(0, 5).map((r) => <span key={r} className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-muted">{r}</span>)}
        {shield.ruleIds.length > 5 && <span className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-muted">+{shield.ruleIds.length - 5} more</span>}
      </div>
      <p className="mt-2 text-[13px] text-muted">
        {shield.control && <>Control page ({shield.control.name}, same SKU) {shield.control.verdict} in {shield.control.latencyMs.toFixed(1)} ms. </>}
        <Chip origin={shield.pageOrigin} /> page, <Chip origin={shield.verdictOrigin} /> verdict{shield.version ? ` from ${shield.version}` : ""}.
      </p>
    </Card>
  );
}

export function ApprovalCard({ approval }: { approval: ApprovalView | null }) {
  if (!approval) {
    return <Card stripe="amber"><Label>Approval call</Label><p className="text-muted">Above your allowance, we call you. The code shows here.</p></Card>;
  }
  const done = approval.attempts.some((a) => a.approved);
  return (
    <Card stripe="amber">
      <Label>Approval call</Label>
      <h3 className="mb-1.5 text-[17px]/[22px] font-semibold tabular-nums">
        {approval.within ? `${money(approval.amount)}, within your allowance` : `${money(approval.amount)}, above your ${money(approval.allowance)} allowance`}
      </h3>
      {approval.wordPair && (
        <>
          <div className="my-3 rounded-xl bg-surface-2 px-4 py-4 text-center">
            <div className="mb-1 text-[12px] font-medium text-muted">Say this, then &quot;approve&quot;</div>
            <div className="font-mono text-[32px]/[36px] font-medium tracking-[0.04em] md:text-[40px]/[44px]">{approval.wordPair}</div>
          </div>
          <p className="text-[13px] text-muted">One use. {done ? "Expired" : "Expires"} {clock(approval.codeExpiresAt)}.</p>
        </>
      )}
      <Details summary="Details">
        <p>To {approval.payee}. We never ask for anything but the code on this screen.</p>
        {approval.whyAnswer && <p>You asked &quot;why not the cheaper one?&quot; It answered: {approval.whyAnswer}</p>}
        <p>{CAP_RULE}</p>
        {approval.attempts.length > 0 && (
          <ol className="grid gap-1.5">
            {approval.attempts.map((a, i) => (
              <li key={i} className="grid grid-cols-[auto_auto_1fr] items-baseline gap-2.5">
                <span className="font-mono text-[12px] text-muted">{clock(a.at)}</span>
                <span className={`font-semibold ${a.approved ? "text-mint" : "text-coral"}`}>{a.label}</span>
                <span>{a.said}</span>
              </li>
            ))}
          </ol>
        )}
      </Details>
    </Card>
  );
}

export const CAP_RULE = "Goal cap is the ceiling to hunt under. Allowance is what it may spend without a call.";

/** Live b5 review card: the word pair issued for this exact mandate. Only the phone call approves (#191, LOCKED): no typed fallback. */
export function ReviewCard({ review, allowance }: { review: ReviewView; allowance: number | null }) {
  return (
    <Card stripe="amber">
      <Label>Approve by phone</Label>
      <h3 className="mb-1.5 text-[17px]/[22px] font-semibold tabular-nums">
        {money(review.amount)} to {review.payee} <OriginChip origin={review.origin} />
      </h3>
      <p className="text-[13px] tabular-nums text-muted">{allowance === null ? "No allowance set" : `Above your ${money(allowance)} allowance`}. We are calling you.</p>
      <div className="my-3 rounded-xl bg-surface-2 px-4 py-4 text-center">
        <div className="mb-1 text-[12px] font-medium text-muted">Say this, then &quot;approve&quot;</div>
        <div className="font-mono text-[32px]/[36px] font-medium tracking-[0.04em] md:text-[40px]/[44px]">{review.code}</div>
      </div>
      <p className="text-[13px] font-semibold">Only the call approves. Nothing on this screen can.</p>
      <Details summary="Details">
        <p>{isWholeBuild(review) ? "One call approves the whole build." : "One call approves this one deal."} One-time code, this screen only. Expires {clock(review.expiry)}.</p>
        <p>{CAP_RULE}</p>
      </Details>
    </Card>
  );
}

export function ReceiptCard({ receipt }: { receipt: ReceiptView | null }) {
  if (!receipt) {
    return <Card stripe="mint"><Label>Receipt</Label><p className="text-muted">Nothing paid yet. Receipts land here.</p></Card>;
  }
  return (
    <Card stripe="mint">
      <Label>Receipt</Label>
      <div className="flex flex-wrap items-center gap-2">
        <span className="motion-safe:animate-[pop_.4s_ease-out] inline-flex size-6 items-center justify-center rounded-full bg-mint-soft text-[13px] font-semibold text-mint" aria-hidden>✓</span>
        <h3 className="m-0 text-[17px] font-semibold tracking-[-0.01em]">Paid</h3>
        <OriginChip origin={receipt.chargeOrigin ?? "SIM"} label={receipt.chargeStatus} />
        <Tag>Test mode</Tag>
      </div>
      <p className="mt-2 font-mono text-[40px]/[44px] font-medium tracking-[-0.02em] tabular-nums">{money(receipt.amount + (receipt.shipping ?? 0))}</p>
      <p className="mt-1 text-[15px] text-ink-2">{[receipt.item, receipt.seller, receipt.condition].filter(Boolean).join(" · ")}</p>
      <Details summary="Proof">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-muted">Item</dt><dd className="tabular-nums">{money(receipt.amount)}{receipt.shipping !== undefined ? ` + ${money(receipt.shipping)} shipping` : ""}</dd>
          <dt className="text-muted">Charge</dt><dd className="min-w-0 [overflow-wrap:anywhere]">{receipt.paymentMethod} · <Code>{receipt.chargeId}</Code> · {clock(receipt.paidAt)}</dd>
          <dt className="text-muted">Approval record</dt><dd className="min-w-0 [overflow-wrap:anywhere]"><Code>{receipt.mandateId}</Code> · expires {clock(receipt.mandateExpires)} · <OriginChip origin={receipt.mandateOrigin} /></dd>
          <dt className="text-muted">Hash</dt><dd><Code>{receipt.mandateHash.slice(0, 8)}…{receipt.mandateHash.slice(-6)}</Code></dd>
          {receipt.signature && <><dt className="text-muted">Signature</dt><dd>{receipt.signature}</dd></>}
          {receipt.replayRefused !== undefined && <><dt className="text-muted">Replay</dt><dd>{receipt.replayRefused ? <><Verdict kind="veto">Refused</Verdict> the same approval sent twice; second charge rejected</> : "not tested"}</dd></>}
          <dt className="text-muted">Allowance</dt><dd>unchanged until the receiving check passes</dd>
        </dl>
      </Details>
    </Card>
  );
}

const FEED_STYLE: Record<FeedItem["kind"], string> = { deal: "text-mint", bid: "text-slate", veto: "text-coral", block: "text-coral", progress: "text-muted" };

export function AgentFeed({ items, max = 40 }: { items: FeedItem[]; max?: number }) {
  return (
    <Card>
      <Label>What the agent did</Label>
      {items.length === 0 ? (
        <p className="text-muted">Nothing yet.</p>
      ) : (
        <ol className="grid">
          {items.slice(0, max).map((f) => (
            <li key={f.key} className="grid grid-cols-[72px_1fr] items-baseline gap-2.5 border-b border-line py-2 text-[14px] last:border-b-0">
              <span className="font-mono text-[12px] text-muted">{clock(f.at)}</span>
              <span className="min-w-0 [overflow-wrap:anywhere]">
                <span className={`mb-px block text-[12px]/[16px] font-medium ${FEED_STYLE[f.kind]}`}>{f.title.charAt(0) + f.title.slice(1).toLowerCase()}</span>
                {f.text} {f.origin && <Chip origin={f.origin} />}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
