// web/src/components/hyphenate.tsx
// Hyphenate screen: the purchasing seat and the AP clerk seat for a simulated studio. Vidyut asks, the controls answer,
// and every decision carries its reason. Reads only lib/hyphenate.ts; everything on it is SIM.
import type { ReactNode } from "react";
import {
  counts,
  decisionsFor,
  findingLabel,
  isBlank,
  kindLabel,
  nameOf,
  poOrder,
  statusLabel,
  stamp,
  stops,
  toneOf,
  usd,
  type Company,
  type Decision,
  type Finding,
  type Invoice,
  type Po,
  type Snapshot,
  type Tone,
  type Vendor,
} from "@/lib/hyphenate";
import { Card, Code, Label, OriginChip, Stat, Tag, Verdict, type VerdictKind } from "./ui";

const TONE_VERDICT: Record<Tone, VerdictKind> = { bad: "veto", warn: "caution", good: "buy", neutral: "out" };
const TONE_BORDER: Record<Tone, "coral" | "amber" | "mint" | "ink"> = { bad: "coral", warn: "amber", good: "mint", neutral: "ink" };

/** An outcome or status word as a coloured verdict (coloured dot plus words, never colour alone). */
function Word({ word, text }: { word: string; text?: string }) {
  return <Verdict kind={TONE_VERDICT[toneOf(word)]}>{text ?? statusLabel(word)}</Verdict>;
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[14px] text-muted">{children}</p>;
}

/** One decision: what happened, who or what decided, and the reason written at the time. */
function DecisionRow({ d, company }: { d: Decision; company: Company }) {
  const tone = toneOf(d.outcome);
  return (
    <li className={`border-l-4 pl-3 ${{ bad: "border-l-coral", warn: "border-l-amber", good: "border-l-mint", neutral: "border-l-line" }[tone]}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-mono text-[12px] text-muted">{stamp(d.at)}</span>
        <span className="text-[13px] font-semibold">{kindLabel(d.kind)}</span>
        <Word word={d.outcome} text={d.outcome.replace(/_/g, " ")} />
        <span className="text-[12px] text-muted">{d.actor.kind === "person" ? nameOf(company, d.actor.id) : d.actor.kind === "rule" ? "a rule" : d.actor.kind}</span>
      </div>
      <p className="mt-1 text-[14px]">{d.reason}</p>
      {(d.rule || d.evidence.length > 0) && (
        <details className="mt-1 text-[12px] text-muted">
          <summary className="min-h-6 cursor-pointer">Rule and evidence · {d.id}</summary>
          {d.rule && <p className="mt-1"><Code>{d.rule.id}</Code> {d.rule.text}</p>}
          {d.evidence.length > 0 && (
            <ul className="mt-1 grid gap-0.5">
              {d.evidence.map((e, i) => (
                <li key={`${e.type}-${e.id}-${i}`}>{e.type} <Code>{e.id}</Code> {e.detail}</li>
              ))}
            </ul>
          )}
        </details>
      )}
    </li>
  );
}

function DecisionList({ items, company, empty }: { items: Decision[]; company: Company; empty: string }) {
  if (items.length === 0) return <Empty>{empty}</Empty>;
  return (
    <ol className="grid gap-3">
      {items.map((d) => (
        <DecisionRow key={d.id} d={d} company={company} />
      ))}
    </ol>
  );
}

function WhoAsked({ s }: { s: Snapshot }) {
  const asker = s.pos[0]?.requester ?? "vidyut";
  const person = s.company.people.find((p) => p.id === asker);
  const people = s.company.people.filter((p) => !p.system);
  const agents = s.company.people.filter((p) => p.system);
  return (
    <Card>
      <Label>Who asked</Label>
      <div className="text-[22px] font-medium tracking-[-0.01em]">{person?.name ?? asker}</div>
      <p className="mt-1 text-[14px] text-muted">
        asks for gear for {s.company.name}. {person ? `${person.role.replace(/_/g, " ")}, ${person.dept}.` : ""} A requester can never approve their own order.
      </p>
      <dl className="mt-3 grid grid-cols-3 gap-2">
        {Object.entries(s.company.budgets).map(([dept, cap]) => (
          <Stat key={dept} label={`${dept} budget`} value={usd(cap)} sub={`${usd(s.company.budgetUsed[dept] ?? 0)} committed`} />
        ))}
      </dl>
      <p className="mt-3 text-[13px] text-muted">
        People: {people.map((p) => `${p.name} (${p.role.replace(/_/g, " ")})`).join(", ")}.
      </p>
      <p className="mt-1 text-[13px] text-muted">
        Agents with no approve permission: {agents.map((a) => a.name).join(", ") || "none listed"}.
      </p>
    </Card>
  );
}

function PoCard({ po, s }: { po: Po; s: Snapshot }) {
  const ds = decisionsFor(s.decisions, `po:${po.id}`);
  const no = ds.find((d) => d.kind === "po_reject");
  const replan = ds.find((d) => d.kind === "replan");
  const tone = toneOf(po.status);
  return (
    <Card stripe={TONE_BORDER[tone]}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[16px] font-semibold">
          {po.id} <span className="font-medium text-muted">{usd(po.total)}</span>
        </div>
        <Word word={po.status} />
      </div>
      <p className="mt-1 text-[14px] text-muted">
        {nameOf(s.company, po.requester)} for {po.dept}: {po.justification || "no reason given"}
        {po.parent ? ` (re-plan of ${po.parent})` : ""}
      </p>
      <ul className="mt-2 grid gap-1 text-[14px]">
        {po.lines.map((l) => (
          <li key={l.sku} className="flex flex-wrap items-center gap-2">
            <span className="tabular-nums">{l.qty} x</span>
            <span>{l.sku}</span>
            <Tag>{l.condition}</Tag>
            <span className="text-muted tabular-nums">{usd(l.unit)} each</span>
          </li>
        ))}
      </ul>
      {po.routeNotes.length > 0 && <p className="mt-2 text-[13px] text-muted">Route: needs {po.needs.join(" and ") || "no one"}. {po.routeNotes.join(" ")}</p>}
      {po.approvals.length > 0 && (
        <p className="mt-1 text-[13px]">
          Approved by {po.approvals.map((a) => `${nameOf(s.company, a.by)} (${a.role.replace(/_/g, " ")}, ${stamp(a.at)})`).join(", ")}.
        </p>
      )}
      {no && (
        <p className="mt-2 rounded-[10px] bg-coral-soft px-3 py-2 text-[14px] text-coral">
          {no.reason}
        </p>
      )}
      {replan && <p className="mt-2 rounded-[10px] bg-amber-soft px-3 py-2 text-[14px] text-amber first-letter:uppercase">{replan.reason}</p>}
    </Card>
  );
}

function Orders({ s }: { s: Snapshot }) {
  return (
    <div className="grid gap-3.5">
      <Label>Orders and the controller&apos;s answer</Label>
      {s.pos.length === 0 ? <Empty>No orders yet.</Empty> : poOrder(s.pos).map((po) => <PoCard key={po.id} po={po} s={s} />)}
    </div>
  );
}

function Receiving({ s }: { s: Snapshot }) {
  const rows = s.pos.filter((p) => p.receipts.length > 0);
  const ds = s.decisions.filter((d) => d.kind === "receiving");
  return (
    <Card>
      <Label>Short shipment at receiving</Label>
      {rows.length === 0 ? (
        <Empty>Nothing received yet.</Empty>
      ) : (
        rows.map((po) => (
          <div key={po.id} className="mb-3 last:mb-0">
            <div className="text-[14px] font-semibold">{po.id}</div>
            <ul className="mt-1 grid gap-1 text-[14px]">
              {po.lines.map((l) => (
                <li key={l.sku} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span>{l.sku}</span>
                  <span className="tabular-nums text-muted">ordered {l.qty}</span>
                  <Verdict kind="buy">{l.accepted} accepted</Verdict>
                  {l.rejected > 0 && <Verdict kind="veto">{l.rejected} rejected ({l.rejectReasons.join(", ").replace(/_/g, " ")})</Verdict>}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
      {ds.length > 0 && <div className="mt-3 border-t border-line pt-3"><DecisionList items={ds} company={s.company} empty="" /></div>}
    </Card>
  );
}

function FindingRow({ f, hold }: { f: Finding; hold: boolean }) {
  return (
    <li className="text-[14px]">
      <Verdict kind={hold ? "veto" : "out"}>{findingLabel(f.code)}</Verdict>
      <span className="ml-2 text-muted">{f.detail}</span>
      {f.credit > 0 && <span className="ml-2 text-[13px] text-muted">credit due {usd(f.credit)}</span>}
    </li>
  );
}

function InvoiceCard({ inv, s }: { inv: Invoice; s: Snapshot }) {
  const vendor: Vendor | undefined = s.vendors.find((v) => v.id === inv.vendorId);
  const match = decisionsFor(s.decisions, `invoice:${inv.id}`).find((d) => d.kind === "invoice_match");
  return (
    <Card stripe={TONE_BORDER[toneOf(inv.status)]}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[16px] font-semibold">
          Bill {inv.number} <span className="font-medium text-muted">{usd(inv.total)} against {inv.poId}</span>
        </div>
        <Word word={inv.status} />
      </div>
      <p className="mt-1 text-[13px] text-muted">
        {vendor?.name ?? inv.vendorId}{vendor && vendor.riskLevel !== "normal" ? ` is now ${vendor.riskLevel}: ${vendor.riskReasons.join("; ")}` : ""}
        {inv.supersedes ? ` · replaces ${inv.supersedes}` : ""}
        {inv.remitTo ? ` · asked to be paid to ${inv.remitTo}` : ""}
      </p>
      {inv.findings.length > 0 || inv.info.length > 0 ? (
        <ul className="mt-2 grid gap-1.5">
          {inv.findings.map((f, i) => <FindingRow key={`${f.code}-${i}`} f={f} hold />)}
          {inv.info.map((f, i) => <FindingRow key={`i-${f.code}-${i}`} f={f} hold={false} />)}
        </ul>
      ) : (
        <p className="mt-2 text-[14px] text-mint">Bill, order and receiving agree. Payable {usd(inv.payable)}.</p>
      )}
      {match && inv.status === "held" && <p className="mt-2 text-[12px] text-muted">Decision {match.id}</p>}
    </Card>
  );
}

function Invoices({ s }: { s: Snapshot }) {
  return (
    <div className="grid gap-3.5">
      <Label>Bills and the three-way match</Label>
      {s.invoices.length === 0 ? <Empty>No bills yet.</Empty> : s.invoices.map((inv) => <InvoiceCard key={inv.id} inv={inv} s={s} />)}
    </div>
  );
}

function Holds({ s }: { s: Snapshot }) {
  const held = stops(s.decisions).filter((d) => d.kind === "payment_release" || d.kind === "vendor_bank_change" || d.kind === "invoice_match");
  const unverified = s.vendors.filter((v) => !v.bankVerified);
  return (
    <Card>
      <Label>Holds on money going out</Label>
      {unverified.length > 0 && (
        <p className="mb-3 rounded-[10px] bg-amber-soft px-3 py-2 text-[14px] text-amber">
          Waiting on a second person to verify bank details: {unverified.map((v) => v.name).join(", ")}.
        </p>
      )}
      <DecisionList items={held} company={s.company} empty="Nothing is held." />
    </Card>
  );
}

function Books({ s }: { s: Snapshot }) {
  const b = s.books;
  return (
    <Card>
      <Label>Books and month close</Label>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Stat label="Debits" value={usd(b.debit)} />
        <Stat label="Credits" value={usd(b.credit)} />
        <Stat label="Trial balance" value={b.balanced ? "Balanced" : "Out of balance"} sub={b.problems ? `${b.problems} vendor ledger problems` : "vendor ledger ties"} />
      </dl>
      <p className="mt-3 text-[14px]">
        {b.closed.length === 0
          ? "No month is closed yet."
          : `Closed: ${b.closed.map((c) => `${c.period} by ${nameOf(s.company, c.by)} (${stamp(c.at)})`).join(", ")}. Posting into a closed month is refused.`}
      </p>
      {s.recon.map((r) => (
        <div key={r.payment} className="mt-3 border-t border-line pt-3 text-[14px]">
          <div className="font-semibold">
            {r.payment}: ledger {usd(r.ledger)}
            {r.bank !== null ? `, bank ${usd(r.bank)}` : ""}
            {r.sellerClaim !== null ? `, seller said ${usd(r.sellerClaim)}` : ""}
          </div>
          <p className="mt-0.5 text-muted">{r.believed ? `Believed: ${r.believed}. ` : ""}{r.reason}</p>
        </div>
      ))}
    </Card>
  );
}

function AuditTrail({ s }: { s: Snapshot }) {
  return (
    <Card>
      <Label>Audit trail · {s.decisionTotal} decisions, each with its reason</Label>
      <DecisionList items={s.decisions} company={s.company} empty="No decisions yet." />
    </Card>
  );
}

export interface HyphenateScreenProps {
  /** loading: first answer not in yet; offline: API unreachable or answered something else. */
  state: "loading" | "offline" | "ready";
  snapshot: Snapshot | null;
  onLoadMoment?: () => void;
  loadingMoment?: boolean;
}

export function HyphenateScreen(p: HyphenateScreenProps) {
  const s = p.snapshot;
  const c = s ? counts(s) : null;
  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="text-[18px] font-bold tracking-[-0.01em]">
          Hyphenate <span className="font-medium text-muted">purchasing and accounts payable seats</span>
        </div>
        <div className="flex items-center gap-2 text-[14px] text-muted">
          {s && <span>{s.company.name}</span>}
          <OriginChip origin="SIM" />
        </div>
      </div>
      <p className="rounded-[10px] border border-dashed border-line px-3 py-2.5 text-[13px] text-muted">
        A simulated 40-person studio buying computer gear. The people, vendors, bills and bank record are SIM; price references are MIRROR. No model makes a control decision: every line below is a rule with its reason.
      </p>
      {p.state === "loading" || (p.state === "ready" && !s) ? (
        <p className="text-muted">Connecting to Hyphenate...</p>
      ) : p.state === "offline" || !s ? (
        <section className="card p-[18px]">
          <p className="text-[22px] font-medium">Hyphenate is offline.</p>
          <p className="mt-1 text-muted">
            Nothing is shown because nothing could be read. Start it with <Code>python3 -m uvicorn hyphenate.api:app --port 8789</Code> and this page fills in on its own.
          </p>
        </section>
      ) : isBlank(s) ? (
        <section className="card p-[18px]">
          <p className="text-[22px] font-medium">A blank studio.</p>
          <p className="mt-1 text-muted">No orders or decisions yet. Load the seeded story to see Vidyut&apos;s request, the controller&apos;s no, the short shipment and the held bills.</p>
          {p.onLoadMoment && (
            <button
              type="button"
              onClick={p.onLoadMoment}
              disabled={p.loadingMoment}
              className="mt-3 min-h-11 rounded-lg bg-accent px-4 py-2 font-medium text-accent-ink disabled:opacity-60"
            >
              {p.loadingMoment ? "Loading..." : "Load the story"}
            </button>
          )}
        </section>
      ) : (
        <>
          {c && (
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Orders" value={String(c.orders)} />
              <Stat label="Decisions on record" value={String(c.decisions)} />
              <Stat label="Stopped or paused" value={String(c.stopped)} sub="refused, held or paused" />
              <Stat label="Bills held now" value={String(c.heldBills)} />
            </dl>
          )}
          <div className="grid gap-3.5 lg:grid-cols-[7fr_5fr]">
            <div className="grid content-start gap-3.5">
              <Orders s={s} />
              <Invoices s={s} />
            </div>
            <div className="grid content-start gap-3.5">
              <WhoAsked s={s} />
              <Receiving s={s} />
              <Holds s={s} />
              <Books s={s} />
            </div>
          </div>
          <AuditTrail s={s} />
          <p className="text-[12px] text-muted">{s.company.sod}</p>
        </>
      )}
    </div>
  );
}
