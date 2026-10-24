// Client side of Hyphenate (hyphenate/api.py, :8789): the purchasing seat and the AP clerk seat for a simulated game studio.
// Pure parsers and helpers plus one fetch. Every payload is checked before it is shown, so a bad answer gives fewer rows, never invented ones.
// Everything here is SIM (the studio, people, vendors, bank record); money is integer cents, as the API sends it.

export const HYPHENATE_URL = process.env.NEXT_PUBLIC_HYPHENATE_URL ?? "http://127.0.0.1:8789/v1/hyphenate";
export const POLL_MS = 5000;

export interface Decision {
  id: string;
  at: string;
  kind: string;
  subject: string;
  outcome: string;
  codes: string[];
  reason: string;
  actor: { kind: string; id: string };
  rule: { id: string; text: string } | null;
  evidence: { type: string; id: string; detail: string }[];
  parents: string[];
}

export interface PoLine {
  sku: string;
  desc: string;
  qty: number;
  unit: number;
  condition: string;
  accepted: number;
  rejected: number;
  billed: number;
  rejectReasons: string[];
}

export interface Approval {
  by: string;
  role: string;
  at: string;
  note: string;
}

export interface Po {
  id: string;
  requester: string;
  dept: string;
  vendorId: string;
  status: string;
  total: number;
  justification: string;
  createdAt: string;
  parent: string | null;
  replannedTo: string | null;
  paid: number;
  needs: string[];
  routeNotes: string[];
  approvals: Approval[];
  lines: PoLine[];
  receipts: string[];
  invoices: string[];
}

export interface Finding {
  code: string;
  sku: string;
  detail: string;
  credit: number;
  hold: boolean;
}

export interface Invoice {
  id: string;
  poId: string;
  vendorId: string;
  number: string;
  date: string;
  total: number;
  status: string;
  remitTo: string | null;
  findings: Finding[];
  info: Finding[];
  payable: number;
  supersedes: string | null;
}

export interface Vendor {
  id: string;
  name: string;
  riskLevel: string;
  riskReasons: string[];
  bankVerified: boolean;
}

export interface Person {
  id: string;
  name: string;
  role: string;
  dept: string;
  system: boolean;
}

export interface Company {
  name: string;
  people: Person[];
  budgets: Record<string, number>;
  budgetUsed: Record<string, number>;
  sod: string;
}

export interface Books {
  closed: { period: string; by: string; at: string }[];
  balanced: boolean;
  debit: number;
  credit: number;
  problems: number;
}

export interface Recon {
  payment: string;
  invoice: string | null;
  ledger: number;
  bank: number | null;
  sellerClaim: number | null;
  believed: string | null;
  reason: string;
}

export interface Snapshot {
  company: Company;
  pos: Po[];
  invoices: Invoice[];
  vendors: Vendor[];
  decisions: Decision[];
  decisionTotal: number;
  books: Books;
  recon: Recon[];
}

// ---------- small readers ----------

type Obj = Record<string, unknown>;
const isObj = (x: unknown): x is Obj => !!x && typeof x === "object" && !Array.isArray(x);
const str = (o: Obj, k: string, d = ""): string => (typeof o[k] === "string" ? (o[k] as string) : d);
const strOrNull = (o: Obj, k: string): string | null => (typeof o[k] === "string" ? (o[k] as string) : null);
const num = (o: Obj, k: string, d = 0): number => (typeof o[k] === "number" && Number.isFinite(o[k]) ? (o[k] as number) : d);
const numOrNull = (o: Obj, k: string): number | null => (typeof o[k] === "number" && Number.isFinite(o[k]) ? (o[k] as number) : null);
const strs = (x: unknown): string[] => (Array.isArray(x) ? x.filter((s): s is string => typeof s === "string") : []);
const objs = (x: unknown): Obj[] => (Array.isArray(x) ? x.filter(isObj) : []);

export function parseDecision(x: unknown): Decision | null {
  if (!isObj(x) || typeof x.id !== "string" || typeof x.kind !== "string" || typeof x.reason !== "string") return null;
  const actor = isObj(x.actor) ? { kind: str(x.actor, "kind"), id: str(x.actor, "id") } : { kind: "system", id: "" };
  const rule = isObj(x.rule) && typeof x.rule.id === "string" ? { id: x.rule.id, text: str(x.rule, "text") } : null;
  return {
    id: x.id,
    at: str(x, "at"),
    kind: x.kind,
    subject: str(x, "subject"),
    outcome: str(x, "outcome"),
    codes: strs(x.codes),
    reason: x.reason,
    actor,
    rule,
    evidence: objs(x.evidence).map((e) => ({ type: str(e, "type"), id: str(e, "id"), detail: str(e, "detail") })),
    parents: strs(x.parents),
  };
}

function parseFinding(o: Obj): Finding {
  return { code: str(o, "code"), sku: str(o, "sku"), detail: str(o, "detail"), credit: num(o, "credit"), hold: o.hold === true };
}

export function parsePo(x: unknown): Po | null {
  if (!isObj(x) || typeof x.id !== "string" || typeof x.requester !== "string") return null;
  const route = isObj(x.route) ? x.route : {};
  return {
    id: x.id,
    requester: x.requester,
    dept: str(x, "dept"),
    vendorId: str(x, "vendor_id"),
    status: str(x, "status"),
    total: num(x, "total"),
    justification: str(x, "justification"),
    createdAt: str(x, "created_at"),
    parent: strOrNull(x, "parent"),
    replannedTo: strOrNull(x, "replanned_to"),
    paid: num(x, "paid"),
    needs: strs(route.needs),
    routeNotes: strs(route.notes),
    approvals: objs(x.approvals).map((a) => ({ by: str(a, "by"), role: str(a, "role"), at: str(a, "at"), note: str(a, "note") })),
    lines: objs(x.lines).map((l) => ({
      sku: str(l, "sku"),
      desc: str(l, "desc"),
      qty: num(l, "qty"),
      unit: num(l, "unit"),
      condition: str(l, "condition"),
      accepted: num(l, "accepted"),
      rejected: num(l, "rejected"),
      billed: num(l, "billed"),
      rejectReasons: strs(l.reject_reasons),
    })),
    receipts: strs(x.receipts),
    invoices: strs(x.invoices),
  };
}

export function parseInvoice(x: unknown): Invoice | null {
  if (!isObj(x) || typeof x.id !== "string" || typeof x.po_id !== "string") return null;
  return {
    id: x.id,
    poId: x.po_id,
    vendorId: str(x, "vendor_id"),
    number: str(x, "number"),
    date: str(x, "date"),
    total: num(x, "total"),
    status: str(x, "status"),
    remitTo: strOrNull(x, "remit_to"),
    findings: objs(x.findings).map(parseFinding),
    info: objs(x.info).map(parseFinding),
    payable: num(x, "payable"),
    supersedes: strOrNull(x, "supersedes"),
  };
}

function parseVendor(x: unknown): Vendor | null {
  if (!isObj(x) || typeof x.id !== "string" || typeof x.name !== "string") return null;
  const risk = isObj(x.risk) ? x.risk : {};
  return { id: x.id, name: x.name, riskLevel: str(risk, "level", "normal"), riskReasons: strs(risk.reasons), bankVerified: x.bank_verified === true };
}

function parseCompany(x: unknown): Company | null {
  if (!isObj(x) || typeof x.name !== "string") return null;
  const nums = (m: unknown): Record<string, number> => {
    const out: Record<string, number> = {};
    if (isObj(m)) for (const [k, v] of Object.entries(m)) if (typeof v === "number") out[k] = v;
    return out;
  };
  return {
    name: x.name,
    people: objs(x.people).map((p) => ({ id: str(p, "id"), name: str(p, "name"), role: str(p, "role"), dept: str(p, "dept"), system: p.system === true })),
    budgets: nums(x.budgets),
    budgetUsed: nums(x.budget_used),
    sod: str(x, "sod"),
  };
}

function parseRecon(o: Obj): Recon {
  return { payment: str(o, "payment"), invoice: strOrNull(o, "invoice"), ledger: num(o, "ledger"), bank: numOrNull(o, "bank"), sellerClaim: numOrNull(o, "seller_claim"), believed: strOrNull(o, "believed"), reason: str(o, "reason") };
}

/** Build a snapshot from the raw answers of the API. null when a required answer is the wrong shape. */
export function parseSnapshot(raw: { company: unknown; pos: unknown; invoices: unknown; vendors: unknown; audit: unknown; journal: unknown; trial: unknown; recon: unknown }): Snapshot | null {
  const company = parseCompany(raw.company);
  if (!company || !isObj(raw.pos) || !Array.isArray(raw.pos.pos) || !isObj(raw.audit) || !Array.isArray(raw.audit.decisions)) return null;
  const pos = raw.pos.pos.map(parsePo).filter((p): p is Po => p !== null);
  const decisions = raw.audit.decisions.map(parseDecision).filter((d): d is Decision => d !== null);
  const invoices = isObj(raw.invoices) && Array.isArray(raw.invoices.invoices) ? raw.invoices.invoices.map(parseInvoice).filter((i): i is Invoice => i !== null) : [];
  const vendors = isObj(raw.vendors) && Array.isArray(raw.vendors.vendors) ? raw.vendors.vendors.map(parseVendor).filter((v): v is Vendor => v !== null) : [];
  const closedRaw = isObj(raw.journal) && isObj(raw.journal.closed_periods) ? raw.journal.closed_periods : {};
  const closed = Object.entries(closedRaw).map(([period, v]) => ({ period, by: isObj(v) ? str(v, "by") : "", at: isObj(v) ? str(v, "at") : "" }));
  const trial = isObj(raw.trial) ? raw.trial : {};
  const books: Books = {
    closed,
    balanced: trial.balanced === true,
    debit: num(trial, "debit"),
    credit: num(trial, "credit"),
    problems: Array.isArray(trial.subledger_problems) ? trial.subledger_problems.length : 0,
  };
  const recon = isObj(raw.recon) && Array.isArray(raw.recon.rows) ? raw.recon.rows.filter(isObj).map(parseRecon) : [];
  return { company, pos, invoices, vendors, decisions, decisionTotal: num(raw.audit, "total", decisions.length), books, recon };
}

const getJson = async (path: string, signal?: AbortSignal): Promise<unknown> => {
  const res = await fetch(`${HYPHENATE_URL}${path}`, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
};

/** null means the API could not be reached or answered something else: the page says "Hyphenate is offline". */
export async function fetchSnapshot(signal?: AbortSignal): Promise<Snapshot | null> {
  try {
    const [company, pos, invoices, vendors, audit, journal, trial, recon] = await Promise.all(
      ["/company", "/pos", "/invoices", "/vendors", "/audit?limit=1000", "/ledger/journal", "/ledger/trial-balance", "/reconciliation"].map((p) => getJson(p, signal)),
    );
    return parseSnapshot({ company, pos, invoices, vendors, audit, journal, trial, recon });
  } catch {
    return null;
  }
}

/** The demo reset: loads the seeded moment. Only offered when the studio is blank. */
export async function loadMoment(): Promise<boolean> {
  try {
    const res = await fetch(`${HYPHENATE_URL}/demo/reset?story=moment`, { method: "POST", cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

// ---------- display helpers ----------

/** Integer cents to "$1,249.99". Cents stay exact: no float division of the whole amount. */
export function usd(cents: number): string {
  const neg = cents < 0;
  const abs = Math.abs(Math.round(cents));
  const dollars = Math.floor(abs / 100).toLocaleString("en-US");
  return `${neg ? "-" : ""}$${dollars}.${String(abs % 100).padStart(2, "0")}`;
}

/** "Oct 24, 09:00" from an ISO stamp. The studio runs on a scripted SIM clock, so it is shown as given (UTC), not converted. */
export function stamp(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  return new Date(t).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
}

export type Tone = "bad" | "warn" | "good" | "neutral";

const BAD = new Set(["denied", "rejected", "hold", "held", "failed", "blocked"]);
const WARN = new Set(["replanned", "pending_verification", "pending_approval", "corrected", "requested", "routed", "partially_received"]);
const GOOD = new Set(["approved", "released", "paid", "matched", "matched_prepaid", "verified", "closed", "bound", "posted", "received", "resolved"]);

/** Colour class of an outcome or status word. Unknown words stay neutral rather than guessing good or bad. */
export function toneOf(word: string): Tone {
  if (BAD.has(word)) return "bad";
  if (WARN.has(word)) return "warn";
  if (GOOD.has(word)) return "good";
  return "neutral";
}

const KIND_LABEL: Record<string, string> = {
  po_draft: "Order drafted",
  approval_route: "Who must approve",
  po_approval: "Approval",
  po_reject: "Controller's no",
  replan: "Re-plan",
  approval_bind: "Payment bound to approval",
  receiving: "Receiving check",
  vendor_history: "Vendor record",
  accrual: "Received, not billed",
  invoice_received: "Invoice arrived",
  source_trust: "Sources disagree",
  invoice_match: "Three-way match",
  credit_memo_request: "Credit memo asked",
  bill_posting: "Bill booked",
  vendor_bank_change: "Bank details changed",
  vendor_bank_verify: "Bank details verified",
  payment_release: "Payment",
  bank_reconcile: "Bank record check",
  period_close: "Month close",
};

export const kindLabel = (kind: string): string => KIND_LABEL[kind] ?? kind.replace(/_/g, " ");

/** Machine finding codes in plain words. Unknown codes fall back to the code with spaces. */
const FINDING_LABEL: Record<string, string> = {
  qty_short: "Billed more than arrived",
  remit_to_mismatch: "Different bank account on the invoice",
  rejected_goods_billed: "Rejected goods still billed",
  price_variance: "Price differs from the PO",
  condition_mismatch: "Condition differs from the PO",
  duplicate_invoice: "Looks like a duplicate bill",
};

export const findingLabel = (code: string): string => FINDING_LABEL[code] ?? code.replace(/_/g, " ");

const STATUS_LABEL: Record<string, string> = {
  pending_approval: "Waiting for approval",
  approved: "Approved",
  partially_received: "Part received",
  received: "Received",
  closed: "Closed",
  rejected: "Rejected",
  replanned: "Re-planned",
  dropped: "Dropped",
  held: "Held",
  matched: "Matched",
  matched_prepaid: "Matched (prepaid)",
  paid: "Paid",
  superseded: "Replaced by a corrected bill",
  rejected_duplicate: "Duplicate refused",
};

export const statusLabel = (s: string): string => STATUS_LABEL[s] ?? s.replace(/_/g, " ");

/** Orders in the order they happened, so a re-plan sits right after the order it replaced. */
export function poOrder(pos: readonly Po[]): Po[] {
  return [...pos].sort((a, b) => (a.createdAt === b.createdAt ? a.id.localeCompare(b.id) : a.createdAt < b.createdAt ? -1 : 1));
}

/** Decisions about one subject ("po:PO-1002", "invoice:INV-1"), oldest first as the API returns them. */
export function decisionsFor(decisions: readonly Decision[], subject: string): Decision[] {
  return decisions.filter((d) => d.subject === subject);
}

/** Everything the controls stopped or paused: refused approvals, held bills, denied payments, a bank change waiting for a second person. */
export function stops(decisions: readonly Decision[]): Decision[] {
  return decisions.filter((d) => toneOf(d.outcome) === "bad" || d.kind === "vendor_bank_change");
}

/** Display name for a claimed id ("pepper" is Pepper Potts); an unknown id is shown as is. */
export function nameOf(company: Company, id: string): string {
  return company.people.find((p) => p.id === id)?.name ?? id;
}

export interface Counts {
  orders: number;
  decisions: number;
  stopped: number;
  heldBills: number;
}

export function counts(s: Snapshot): Counts {
  return {
    orders: s.pos.length,
    decisions: s.decisionTotal,
    stopped: stops(s.decisions).length,
    heldBills: s.invoices.filter((i) => i.status === "held").length,
  };
}

/** A fresh studio has nothing to show yet: no orders and no decisions. */
export const isBlank = (s: Snapshot): boolean => s.pos.length === 0 && s.decisions.length === 0;
