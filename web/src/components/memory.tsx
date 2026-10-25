"use client";
// Recorded history for the paired buyer: Purchases, Decisions and the dashboard's recent purchases all read one
// validated /v1/memory response (lib/memory.ts). Nothing here ranks, infers or joins rows; a missing field shows as unavailable.

import Link from "next/link";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { approvalLabel, entryDate, fetchMemory, memoryFeed, memoryForBuyer, paymentModeLabel, selectMemory, sourceUrl, type MemoryEntry, type MemoryResponse } from "@/lib/memory";
import { useBuyerId } from "./BuyerGate";
import { Card, Code, Label, OriginChip, SourceLink, Tag, Verdict, clock, money } from "./ui";

type MemoryState = { status: "loading" } | { status: "offline" } | { status: "error"; message: string } | { status: "ready"; data: MemoryResponse };
const MemoryContext = createContext<{ state: MemoryState; reload: () => void } | null>(null);

/** One read for every buyer screen. It lives below BuyerGate, so a buyer switch unmounts it and aborts the pending request. */
export function MemoryProvider({ children }: { children: ReactNode }) {
  const buyerId = useBuyerId();   // sent as ?buyer= so a token-gated feed (AGENT_FEED_TOKEN) can scope the rows (#449 PL-17)
  const [state, setState] = useState<MemoryState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const ctl = new AbortController();
    const feed = memoryFeed(window.location.hostname);
    if (!feed) {
      // The hosted site: the operator feed runs on the operator's machine, so never fetch a loopback address from a visitor's browser.
      // The hostname is only known in the browser after hydration, so this one state change has to happen here.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState({ status: "offline" });
      return;
    }
    fetchMemory(ctl.signal, feed, buyerId).then(
      (data) => setState({ status: "ready", data }),
      (e: unknown) => {
        if (!ctl.signal.aborted) setState({ status: "error", message: e instanceof Error ? e.message : "memory feed failed" });
      },
    );
    return () => ctl.abort();
  }, [attempt, buyerId]);
  const reload = () => {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  };
  return <MemoryContext.Provider value={{ state, reload }}>{children}</MemoryContext.Provider>;
}

type Purchase = Extract<MemoryEntry, { kind: "purchase" }>;
const isPurchase = (e: MemoryEntry): e is Purchase => e.kind === "purchase";

/** This buyer's rows (display filter, not authorization) and the feed state. */
function useBuyerMemory() {
  const ctx = useContext(MemoryContext);
  if (!ctx) throw new Error("useBuyerMemory must be used inside MemoryProvider");
  const buyerId = useBuyerId();
  const data = ctx.state.status === "ready" ? ctx.state.data : null;
  const entries = useMemo(() => (data ? memoryForBuyer(data.entries, buyerId) : []), [data, buyerId]);
  return { ...ctx, data, entries };
}

const amountLabel = (p: Purchase["detail"]) => (p.currency === "USD" ? money(p.amount_before_tax) : `${money(p.amount_before_tax).slice(1)} ${p.currency}`);
const when = (e: MemoryEntry) => {
  const d = entryDate(e);
  return d ? `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${clock(d)}` : "Time not recorded";
};
const text = (s: string) => s || "Unavailable";
/** The reason on its own line only when the supplied summary does not already say it. */
const Reason = ({ e, reason }: { e: MemoryEntry; reason: string }) => (reason && !e.summary.includes(reason) ? <p className="mt-1 text-[13px]/[18px] text-ink-2"><span className="text-muted">Reason:</span> {reason}</p> : null);

function RetryButton({ reload }: { reload: () => void }) {
  return (
    <button onClick={reload} className="btn mt-2 min-h-11 rounded-xl bg-surface px-5 shadow-ring text-[14px] font-medium hover:bg-surface-2">
      Try again
    </button>
  );
}

/** Loading, failure and feed health: everything the history screens say about where the rows came from. */
function MemoryStatus({ m, empty }: { m: ReturnType<typeof useBuyerMemory>; empty: string }) {
  if (m.state.status === "loading") return <p className="text-muted">Loading recorded history...</p>;
  if (m.state.status === "offline") {
    return (
      <Card>
        <p className="flex items-center gap-2.5 text-[17px] font-semibold"><span className="h-2 w-2 rounded-full bg-slate" aria-hidden /> Your history is not live on this site yet.</p>
        <p className="mt-1 text-[13px] text-muted">Purchases and decisions are recorded on the operator&apos;s machine. Nothing is shown rather than a guess.</p>
      </Card>
    );
  }
  if (m.state.status === "error") {
    return (
      <Card>
        <p className="flex items-center gap-2.5 text-[17px] font-semibold"><span className="h-2 w-2 rounded-full bg-slate" aria-hidden /> Your history is not available right now.</p>
        <p className="mt-1 text-[13px] text-muted">Nothing is shown rather than a guess. Try again in a moment.</p>
        <RetryButton reload={m.reload} />
      </Card>
    );
  }
  const d = m.state.data;
  const broken = d.sources.filter((s) => s.state === "error");
  return (
    <div className="grid gap-2 text-[13px] text-muted">
      {m.entries.length === 0 && <p className="text-[15px] text-ink">{empty}{d.note ? ` ${d.note}.` : ""}</p>}
      {d.rejected > 0 && <p>{d.rejected} {d.rejected === 1 ? "row" : "rows"} from the feed did not match the contract and {d.rejected === 1 ? "is" : "are"} not shown.</p>}
      {broken.length > 0 && <p>A source could not be read: {broken.map((s) => s.ref).join(", ")}.</p>}
      <details>
        <summary className="inline-flex min-h-11 cursor-pointer items-center font-medium text-ink-2">Sources ({d.sources.length})</summary>
        <ul className="grid gap-1 font-mono text-[12px]">
          {d.sources.map((s) => (
            <li key={`${s.kind}:${s.ref}`}>{s.ref} · {s.kind} · {s.state} · {s.rows} {s.rows === 1 ? "row" : "rows"}{s.sample ? " · sample" : ""}</li>
          ))}
        </ul>
      </details>
      <p>Rows are filtered to you on this screen.</p>
    </div>
  );
}

function Search({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Filter recorded history by text"
      placeholder="Filter by seller, payee, rule or reason"
      className="min-h-11 w-full rounded-xl bg-surface px-4 text-[15px] shadow-ring placeholder:text-muted sm:max-w-sm"
    />
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-baseline justify-between gap-4 border-t border-line py-2.5 first:border-t-0">
      <dt className="shrink-0 text-[14px]/[20px] text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-right font-mono text-[13px]/[20px] tabular-nums">{children}</dd>
    </div>
  );
}

function PurchaseCard({ e }: { e: Purchase }) {
  const d = e.detail;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[12px]/[16px] font-medium uppercase tracking-[0.04em] text-muted">Receipt, before tax</span>
        <div className="flex flex-wrap items-center gap-2">
          <OriginChip origin={e.origin} />
          <OriginChip origin={d.listing_origin} label={`listing ${d.listing_origin}`} />
        </div>
      </div>
      <p className="mt-3 text-[44px]/[48px] font-medium tracking-[-0.02em] tabular-nums md:text-[48px]/[52px]">{amountLabel(d)}</p>
      <p className="mt-1 text-[15px]/[20px] text-ink-2 text-balance">{e.summary}</p>
      <dl className="mt-4">
        <Fact label="Payee">{text(d.payee)}</Fact>
        <Fact label="Seller">{text(e.seller_id)}</Fact>
        <Fact label="Recorded">{when(e)}</Fact>
        <Fact label="Payment">{paymentModeLabel(d.payment_mode)}</Fact>
        <Fact label="Payment reference"><Code>{text(d.payment_ref)}</Code></Fact>
        <Fact label="Approval">{approvalLabel(d.approval_method)}</Fact>
        <Fact label="Approval record"><Code>{text(d.mandate_id)}</Code></Fact>
        <Fact label="Deal"><Code>{text(d.deal_id)}</Code></Fact>
      </dl>
    </Card>
  );
}

export function PurchasesView() {
  const m = useBuyerMemory();
  const [q, setQ] = useState("");
  const rows = selectMemory(m.entries, "purchase", q).filter(isPurchase);
  return (
    <div className="grid gap-3.5">
      {m.state.status === "ready" && m.entries.length > 0 && <Search value={q} onChange={setQ} />}
      {rows.map((e) => <PurchaseCard key={e.id} e={e} />)}
      {q && m.entries.length > 0 && rows.length === 0 && <p className="text-muted">No recorded purchase matches that text.</p>}
      <MemoryStatus m={m} empty="No purchases yet. A receipt appears here after each approved purchase." />
    </div>
  );
}

const BAND: Record<Extract<MemoryEntry, { kind: "lesson" }>["detail"]["gap_band"], string> = {
  within5: "price gap within 5%",
  within10: "price gap within 10%",
  within20: "price gap within 20%",
  over20: "price gap over 20%",
};

/** One ledger row: a dot, what it says, and the detail underneath. */
function LedgerRow({ dot, children }: { dot: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8px_minmax(0,1fr)] items-start gap-3 border-t border-line py-3">
      <i className={`mt-1.5 size-2 rounded-full ${dot}`} aria-hidden />
      <div className="min-w-0 break-words text-[13px]/[18px] text-muted">{children}</div>
    </div>
  );
}

function DecisionCard({ e }: { e: MemoryEntry }) {
  if (e.kind === "veto") {
    const url = sourceUrl(e);
    return (
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Verdict kind="veto">Vetoed</Verdict>
          <span className="flex items-center gap-2 text-[13px] text-muted">{when(e)} <OriginChip origin={e.origin} /></span>
        </div>
        <p className="mt-3 text-[22px]/[28px] font-semibold tracking-[-0.01em] text-balance">{e.summary}</p>
        <div className="mt-4">
          <LedgerRow dot="bg-coral-mark">
            <p className="flex flex-wrap items-center gap-2 text-ink-2">
              Seller {text(e.seller_id)} · rule <Code>{text(e.detail.rule_id)}</Code>
              {e.buyer_id === "" && <span className="text-muted">· not tied to a buyer</span>}
            </p>
            <Reason e={e} reason={e.detail.reason} />
            <p className="mt-1">{url ? <SourceLink href={url} /> : <span>No source link recorded.</span>}</p>
          </LedgerRow>
        </div>
      </Card>
    );
  }
  if (e.kind !== "lesson") return null;
  const d = e.detail;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Verdict kind={d.won ? "buy" : "out"}>{d.won ? "Won" : "Lost"} round <Code>{text(d.round_id)}</Code></Verdict>
        <span className="flex items-center gap-2 text-[13px] text-muted">{when(e)} <OriginChip origin={e.origin} /></span>
      </div>
      <p className="mt-3 text-[22px]/[28px] font-semibold tracking-[-0.01em] text-balance">{e.summary}</p>
      <div className="mt-4">
        <LedgerRow dot={d.won ? "bg-mint-mark" : "bg-ghost-1"}>
          <div className="flex flex-wrap items-center gap-2">
            <Tag>seller {text(e.seller_id)}</Tag>
            {!e.buyer_id && <Tag>seller lesson, not tied to a buyer</Tag>}
            {!d.won && <Tag>{BAND[d.gap_band]}</Tag>}
          </div>
          <Reason e={e} reason={d.reason} />
        </LedgerRow>
      </div>
      <p className="rounded-xl bg-surface-2 px-4 py-3 text-[13px]/[18px]">{d.what_to_change ? <><b className="font-semibold">Recorded lesson.</b> {d.what_to_change}</> : <span className="text-muted">No change recorded for this loss.</span>}</p>
    </Card>
  );
}

const FILTERS = [["all", "All"], ["veto", "Vetoes"], ["lesson", "Lessons"]] as const;

export function DecisionsView() {
  const m = useBuyerMemory();
  const [kind, setKind] = useState<"all" | "veto" | "lesson">("all");
  const [q, setQ] = useState("");
  const decisions = useMemo(() => m.entries.filter((e) => e.kind === "veto" || e.kind === "lesson"), [m.entries]);
  const [showLessons, setShowLessons] = useState(false);
  const lessonCount = decisions.filter((e) => e.kind === "lesson").length;
  const rows = selectMemory(decisions, kind, q).filter((e) => e.kind !== "lesson" || showLessons || kind === "lesson");
  return (
    <div className="grid gap-3.5">
      {m.state.status === "ready" && decisions.length > 0 && <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Show" className="flex gap-1">
          {FILTERS.map(([k, label]) => (
            <button
              key={k}
              aria-pressed={kind === k}
              onClick={() => setKind(k)}
              className={`min-h-11 rounded-full px-4 text-[14px] font-medium ${kind === k ? "bg-pulse-soft text-pulse-soft-ink" : "text-muted hover:bg-surface-2 hover:text-ink"}`}
            >
              {label}
              <span className="ml-1.5 font-mono text-[12px] opacity-70">{k === "all" ? decisions.length : decisions.filter((e) => e.kind === k).length}</span>
            </button>
          ))}
        </div>
        <Search value={q} onChange={setQ} />
      </div>}
      {kind !== "lesson" && lessonCount > 0 && (
        <button type="button" aria-pressed={showLessons} onClick={() => setShowLessons((v) => !v)} className="min-h-11 justify-self-start btn rounded-xl bg-surface px-5 shadow-ring text-[14px] font-medium text-muted hover:bg-surface-2 hover:text-ink">
          {showLessons ? `Hide ${lessonCount} seller lessons` : `Show ${lessonCount} seller lessons`}
        </button>
      )}
      {rows.map((e) => <DecisionCard key={e.id} e={e} />)}
      {(q || kind !== "all") && decisions.length > 0 && rows.length === 0 && <p className="text-muted">No recorded decision matches that filter.</p>}
      <MemoryStatus m={m} empty="No decisions yet. Vetoes and the lessons sellers learned appear here after a round closes." />
    </div>
  );
}

/** The dashboard's card: the latest few purchases from the same read, with an honest unavailable state. */
export function RecentPurchases() {
  const m = useBuyerMemory();
  const rows = selectMemory(m.entries, "purchase", "").filter(isPurchase).slice(0, 3);
  return (
    <Card>
      <Label>Purchases</Label>
      {m.state.status === "loading" ? (
        <p className="text-[13px] text-muted">Loading...</p>
      ) : m.state.status === "offline" ? (
        <p className="text-[13px] text-muted">Your receipts appear here after your first approved purchase.</p>
      ) : m.state.status === "error" ? (
        <>
          <p className="text-[15px] font-medium">Not available right now.</p>
          <RetryButton reload={m.reload} />
        </>
      ) : rows.length === 0 ? (
        <p className="text-[13px] text-muted">No purchases yet. Your receipts appear here after your first approved purchase.</p>
      ) : (
        <ul className="grid gap-2">
          {rows.map((e) => (
            <li key={e.id} className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="text-[18px] font-semibold tabular-nums">{amountLabel(e.detail)}</span>
              <span className="flex min-w-0 flex-wrap items-center gap-2 break-words text-[13px] text-muted">{text(e.detail.payee)} · {when(e)} <OriginChip origin={e.origin} /> no real money</span>
            </li>
          ))}
        </ul>
      )}
      <Link href="/buyer/purchases" className="mt-3 inline-flex min-h-11 items-center text-[14px] text-pulse underline underline-offset-4">All purchases</Link>
    </Card>
  );
}
