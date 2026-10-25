// The buyer's request, before it reaches an agent. This file validates what the buyer typed, keeps their exact words,
// and guards the two things that are not connected yet: sending a goal from the app, and speech input. It never decides
// what the market stocks. It maps the words to one of the catalog parts below only when they name exactly one part
// clearly (#449 PL-14): a vague "gpu" or "psu", or words naming two or more different parts, come back as a question
// for the buyer and never as a guess.

import { formatMoney } from "./money.ts";

export const CONDITIONS = ["new", "open-box", "refurbished", "used"] as const; // contracts/Need.schema.json
export const MAX_TEXT = 500;

export interface GoalRequest {
  /** One id per send, so a retry or a second tap is the same request. */
  requestId: string;
  /** Exactly what the buyer typed. */
  requestText: string;
  cap: number | null;
  /** YYYY-MM-DD, the buyer's own calendar day. */
  deadline: string | null;
  /** Empty means the buyer named none. */
  conditions: string[];
  /** Always empty today: no approved buyer-private owned-parts source exists, so none is invented. */
  ownedPartIds: string[];
}

/** The form's raw values. */
export interface GoalDraft {
  text: string;
  cap: string;
  deadline: string;
  conditions: string[];
}
export const EMPTY_DRAFT: GoalDraft = { text: "", cap: "", deadline: "", conditions: [] };

export interface Problem {
  field: keyof GoalDraft;
  message: string;
}

const MONEY = /^\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$/;

/** A positive dollar amount, null for empty, undefined for anything else. */
function parseCap(s: string): number | null | undefined {
  const t = s.trim();
  if (!t) return null;
  if (!MONEY.test(t)) return undefined;
  const n = Number(t.replace(/[$,\s]/g, ""));
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** True for a real calendar day written YYYY-MM-DD ("2026-02-30" is not one). */
function isCalendarDay(s: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(y, mo - 1, d);
  return date.getFullYear() === y && date.getMonth() === mo - 1 && date.getDate() === d;
}

/** Validate the form. Every problem comes back together; the request keeps the buyer's words untouched. */
export function buildGoalRequest(draft: GoalDraft, requestId: string, today: Date): { ok: true; request: GoalRequest } | { ok: false; problems: Problem[] } {
  const problems: Problem[] = [];
  if (!draft.text.trim()) problems.push({ field: "text", message: "Say what you want to buy." });
  else if (draft.text.length > MAX_TEXT) problems.push({ field: "text", message: `Keep the request under ${MAX_TEXT} characters.` });

  const cap = parseCap(draft.cap);
  if (cap === undefined) problems.push({ field: "cap", message: "Enter the budget cap as dollars, for example 650 or $1,300.50, or leave it empty." });

  const day = draft.deadline.trim();
  if (day && (!isCalendarDay(day) || day < ymd(today))) problems.push({ field: "deadline", message: "Pick a real date from today on, or leave it empty." });

  if (draft.conditions.some((c) => !(CONDITIONS as readonly string[]).includes(c))) problems.push({ field: "conditions", message: `Conditions can be ${CONDITIONS.join(", ")}.` });

  if (problems.length) return { ok: false, problems };
  return {
    ok: true,
    request: { requestId, requestText: draft.text, cap: cap ?? null, deadline: day || null, conditions: CONDITIONS.filter((c) => draft.conditions.includes(c)), ownedPartIds: [] },
  };
}

// ---- Posting the goal to the market (reducers.postGoal). The market checks the rest: type, cap > 0, ISO deadline, new id, caller.

export interface PostGoalArgs {
  id: string;
  buyerId: string;
  type: string;
  cap: number;
  deadline: string;
  poNumber: string;
  origin: string;
  items: { skuSpec: string; condition: string; variant: string; quantity: number; skippedOwnedPartId: string }[];
}

/** The full catalog sellers stock tonight. Sellers match need items by exact lowercase sku_spec. */
export const CATALOG = [
  { sku: "rtx 5070 ti", label: "RTX 5070 Ti" },
  { sku: "rtx 4070 super 12gb", label: "RTX 4070 Super" },
  { sku: "rx 7800 xt 16gb", label: "RX 7800 XT" },
  { sku: "psu 850w", label: "850W PSU" },
  { sku: "psu 750w", label: "750W PSU" },
  { sku: "case", label: "PC case" },
] as const;

const NOT_STOCKED = "Sellers tonight don't carry that part. Tap one above: RTX 5070 Ti, RTX 4070 Super, RX 7800 XT, an 850W or 750W PSU, or a PC case.";
const ONE_AT_A_TIME = "That names more than one part. Ask for one part at a time; post the next one after this.";

/** "A", "A or B", "A, B or C" of the catalog labels for these skus. */
function choices(skus: readonly string[]): string {
  const labels = skus.map((sku) => CATALOG.find((c) => c.sku === sku)!.label);
  return labels.length < 2 ? labels.join("") : `${labels.slice(0, -1).join(", ")} or ${labels[labels.length - 1]}`;
}

const GPU_MODELS = [
  { re: /\b(?:rtx\s*)?5070\s*ti\b/g, sku: "rtx 5070 ti" },
  { re: /\b(?:rtx\s*)?4070\s*super\b/g, sku: "rtx 4070 super 12gb" },
  { re: /\b(?:rx\s*)?7800\s*xt\b/g, sku: "rx 7800 xt 16gb" },
] as const;

/**
 * What the typed words name: one catalog sku, or a problem to show the buyer. A sku comes back only when the words name exactly one
 * part clearly. A bare "gpu" or "psu" asks which one; two or more different parts ask for one part at a time; a part sellers do not
 * carry says so. #449 PL-14: nothing here picks a card or a wattage the buyer did not name.
 */
export function matchCatalog(text: string): { sku: string } | { problem: string } {
  let t = text.toLowerCase();
  const gpu = new Set<string>(); // named catalog cards, plus "other" for a model sellers do not carry
  for (const m of GPU_MODELS) {
    const rest = t.replace(m.re, " ");
    if (rest !== t) gpu.add(m.sku);
    t = rest;
  }
  if (/\b(?:rtx|rx|gtx)\s*\d{3,4}/.test(t) || /(?<![$\d,.])\b\d{4}\s*(?:ti|super|xt|gpu|graphics|video)\b/.test(t)) gpu.add("other");
  const psu = new Set<string>(); // named wattages: "psu 850w", "psu 750w", or "other" for one sellers do not carry
  for (const w of t.matchAll(/\b(\d{3,4})\s*-?\s*w(?:atts?)?\b/g)) psu.add(w[1] === "850" ? "psu 850w" : w[1] === "750" ? "psu 750w" : "other");
  const vagueGpu = gpu.size === 0 && /\b(?:gpu|graphics card|video card)\b/.test(t);
  const vaguePsu = psu.size === 0 && /\b(?:psu|power supply)\b/.test(t);
  // "in case", "case of" and the buyer's own case ("fits my case", "my mid-tower case") are not a request for a PC case
  const pcCase = /\b(?:pc case|mid-tower|full-tower|mini-tower)\b|(?<!\bin(?:\s+(?:this|that|any|which))?\s)\bcase\b(?!\s+of\b)/.test(t.replace(/\b(?:my|your|our)\s+(?:[\w-]+\s+){0,2}case\b/g, " "));
  const families = [gpu.size > 0 || vagueGpu, psu.size > 0 || vaguePsu, pcCase].filter(Boolean).length;
  if (gpu.size > 1 || psu.size > 1 || families > 1) return { problem: ONE_AT_A_TIME };
  const [card] = gpu;
  if (card) return card === "other" ? { problem: NOT_STOCKED } : { sku: card };
  const [watts] = psu;
  if (watts) return watts === "other" ? { problem: NOT_STOCKED } : { sku: watts };
  if (pcCase) return { sku: "case" };
  if (vagueGpu) return { problem: `Which card do you want? Tap one above: ${choices(["rtx 5070 ti", "rtx 4070 super 12gb", "rx 7800 xt 16gb"])}.` };
  if (vaguePsu) return { problem: `Which power supply do you want? Tap one above: ${choices(["psu 750w", "psu 850w"])}.` };
  return { problem: NOT_STOCKED };
}

/** The seller sku for typed words, or null when they do not name exactly one clear catalog part (matchCatalog says why). */
export function catalogSku(text: string): string | null {
  const m = matchCatalog(text);
  return "sku" in m ? m.sku : null;
}

export function postGoalArgs(request: GoalRequest, buyerId: string, today: Date): PostGoalArgs | { error: string } {
  if (request.cap === null) return { error: "Add a top price so sellers know your cap." };
  const part = matchCatalog(request.requestText);
  if ("problem" in part) return { error: part.problem };
  const skuSpec = part.sku;
  const [y, m, d] = (request.deadline ?? ymd(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 7))).split("-").map(Number);
  return {
    id: `g_${request.requestId.replace(/[^A-Za-z0-9]/g, "").slice(0, 12)}`,
    buyerId,
    type: "budget_cap",
    cap: request.cap,
    deadline: new Date(y!, m! - 1, d!, 23, 59).toISOString(), // the buyer's local end of day
    poNumber: "",
    origin: "SIM",
    items: [{ skuSpec, condition: request.conditions[0] ?? "new", variant: "retail", quantity: 1, skippedOwnedPartId: "" }],
  };
}

/** Find offers needs a signed-up buyer and no send in flight. */
export const canFindOffers = (buyerId: string | null, busy: boolean): boolean => buyerId !== null && !busy;

// ---- The draft: kept through pairing, never shown to a different buyer.

export interface StoredDraft {
  /** The buyer it was typed under; null when it was typed before pairing. */
  owner: string | null;
  draft: GoalDraft;
}

const isStrings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");

/** The saved draft if it is exactly the shape this file writes, else null. */
export function parseStoredDraft(raw: string | null): StoredDraft | null {
  try {
    const v = JSON.parse(raw ?? "null");
    const d = v?.draft;
    if (!v || typeof v !== "object" || !(v.owner === null || typeof v.owner === "string") || !d || typeof d.text !== "string" || typeof d.cap !== "string" || typeof d.deadline !== "string" || !isStrings(d.conditions)) return null;
    return { owner: v.owner, draft: { text: d.text, cap: d.cap, deadline: d.deadline, conditions: d.conditions } };
  } catch {
    return null;
  }
}

/** A draft typed before pairing goes to whoever pairs; a buyer's own draft goes to nobody else, and an unpaired screen never shows it. */
export function draftFor(stored: StoredDraft | null, owner: string | null): GoalDraft {
  return stored && (stored.owner === null || stored.owner === owner) ? stored.draft : { ...EMPTY_DRAFT };
}

/** The honest route today: this text goes to the buyer agent in ASI:One. Only the buyer's own words and the details they filled in. */
export function fallbackMessage(r: GoalRequest): string {
  return [
    r.requestText,
    r.cap !== null ? `Budget cap: ${formatMoney(r.cap)}` : "",
    r.deadline ? `Needed by: ${r.deadline}` : "",
    r.conditions.length ? `Acceptable conditions: ${r.conditions.join(", ")}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

// ---- Sending a goal from the app. BLOCKED: no authenticated command that starts the buyer agent and answers with a
// persisted goal id is confirmed. Writing a market goal (post_goal) does not start a hunt, and agents/buyer/web_chat.py is
// a loopback chat proxy that returns reply text, not a goal id. Until one exists GOAL_COMMAND stays null and sending says so.

export type SubmitErrorKind = "blocked" | "sign_in" | "timeout" | "unsupported" | "unreachable" | "rejected" | "aborted";

export class GoalSubmitError extends Error {
  readonly kind: SubmitErrorKind;
  constructor(kind: SubmitErrorKind, message: string) {
    super(message);
    this.kind = kind;
    this.name = "GoalSubmitError";
  }
}

/** The confirmed command, when there is one: send the request as the paired buyer, answer with the persisted goal id. It signals sign_in and unsupported itself. */
export type GoalCommand = (request: GoalRequest, signal: AbortSignal) => Promise<{ goalId: unknown }>;
export const GOAL_COMMAND: GoalCommand | null = null;

const SUBMIT_TIMEOUT_MS = 15_000;
const inFlight = new Map<string, Promise<{ goalId: string }>>();

/** Send once per request id (a second tap shares the first answer). Resolves only with a persisted goal id; a slow answer is "unknown", never "failed" or "sent". */
export function submitGoal(request: GoalRequest, signal?: AbortSignal, options: { command?: GoalCommand | null; timeoutMs?: number } = {}): Promise<{ goalId: string }> {
  const command = options.command === undefined ? GOAL_COMMAND : options.command;
  if (!command) return Promise.reject(new GoalSubmitError("blocked", "This screen cannot start the buyer agent yet: no app command for it is confirmed. Send the request in ASI:One instead."));
  if (signal?.aborted) return Promise.reject(new GoalSubmitError("aborted", "Sending was cancelled."));
  const existing = inFlight.get(request.requestId);
  if (existing) return existing;
  const p = send(command, request, signal, options.timeoutMs ?? SUBMIT_TIMEOUT_MS).finally(() => inFlight.delete(request.requestId));
  inFlight.set(request.requestId, p);
  return p;
}

async function send(command: GoalCommand, request: GoalRequest, signal: AbortSignal | undefined, timeoutMs: number): Promise<{ goalId: string }> {
  const ctl = new AbortController();
  const cancel = () => ctl.abort();
  signal?.addEventListener("abort", cancel);
  const slow = new GoalSubmitError("timeout", "No answer came back in time. The request may or may not have been recorded. Check your searches before sending it again.");
  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true; // before the abort: the command's own AbortError must not be read as the reason
      ctl.abort();
      reject(slow);
    }, timeoutMs);
  });
  try {
    const answer = await Promise.race([command(request, ctl.signal), late]);
    const id = answer?.goalId;
    if (typeof id !== "string" || !id.trim()) throw new GoalSubmitError("rejected", "The app did not get a goal id back, so nothing is recorded as sent.");
    return { goalId: id };
  } catch (e) {
    if (timedOut) throw slow;
    if (e instanceof GoalSubmitError) throw e;
    if (signal?.aborted) throw new GoalSubmitError("aborted", "Sending was cancelled.");
    throw new GoalSubmitError("unreachable", "The request could not be sent. It may or may not have been recorded. Check your searches before sending it again.");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

// ---- Speech input. BLOCKED: no speech service is approved or confirmed (outbound phone approval is Lane D's call
// transport, not browser dictation), and nothing here may start paid or third-party audio traffic on its own.

export type SpeechErrorKind = "unavailable" | "denied" | "no_speech" | "aborted";

export class SpeechError extends Error {
  readonly kind: SpeechErrorKind;
  constructor(kind: SpeechErrorKind, message: string) {
    super(message);
    this.kind = kind;
    this.name = "SpeechError";
  }
}

export interface SpeechTransport {
  listen(signal: AbortSignal): Promise<string>;
}
export const SPEECH_TRANSPORT: SpeechTransport | null = null;

const DENIED = ["NotAllowedError", "SecurityError", "PermissionDeniedError"];
const nameOf = (e: unknown) => (e as { name?: string } | null)?.name ?? "";

/** What the buyer said, trimmed. Any refusal or failure leaves typing untouched and says so. */
export async function dictate(transport: SpeechTransport | null, signal: AbortSignal): Promise<string> {
  if (!transport) throw new SpeechError("unavailable", "Voice entry is not connected yet. Type your request instead.");
  let heard: string;
  try {
    heard = await transport.listen(signal);
  } catch (e) {
    if (signal.aborted || nameOf(e) === "AbortError") throw new SpeechError("aborted", "Listening was cancelled.");
    if (DENIED.includes(nameOf(e))) throw new SpeechError("denied", "Microphone access was refused. Type your request instead, or allow the microphone in your browser settings.");
    throw new SpeechError("unavailable", "Voice entry stopped working. Type your request instead.");
  }
  const text = heard.trim();
  if (!text) throw new SpeechError("no_speech", "Nothing was heard. Try again or type your request.");
  return text;
}

/** Dictation only fills the request box. It carries no approval and changes nothing else. */
export function applyDictation(current: string, heard: string): string {
  const h = heard.trim();
  if (!h) return current;
  if (!current.trim()) return h;
  return /\s$/.test(current) ? current + h : `${current} ${h}`;
}
