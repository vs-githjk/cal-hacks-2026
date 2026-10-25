// Client side of the Seller Kit API (seller_kit/api.py, :8791). Pure helpers plus three fetches.
// The page only builds a SellerConfig from the form and shows what the API answers; the API (agents/sellers/factory.py)
// is the authority on whether a config is valid, so a refusal here is never decided client side beyond "not a number".

export const SELLER_KIT_URL = process.env.NEXT_PUBLIC_SELLER_KIT_URL ?? "http://127.0.0.1:8791";

export const CONDITIONS = ["new", "open-box", "refurbished", "used"] as const;
export type Condition = (typeof CONDITIONS)[number];
export type PricingMode = "discount" | "fixed_margin";

export interface ListingRow {
  sku: string;
  condition: Condition;
  /** List price when pricing is a discount, your cost when pricing is a fixed margin. */
  amount: string;
  /** Lowest unit price the agent will ever bid for this condition. */
  floor: string;
  url: string;
}

export interface SellForm {
  id: string;
  name: string;
  owner: string;
  archetype: string;
  mode: PricingMode;
  /** Percent: margin on cost, or discount off the list price. */
  percent: string;
  shipping: string;
  perks: string;
  claims: string;
  rows: ListingRow[];
}

export interface FieldError {
  field: string;
  message: string;
}

export type ReadinessStatus = "blocks" | "warns" | "ready" | "unreadable";

/** The Seller Agent-Readiness Report for one listing page (#398): what an AI shopper sees there, with a fix per finding. */
export interface Readiness {
  url: string;
  status: ReadinessStatus;
  summary: string;
  findings: { severity: string; what_an_agent_sees: string; fix: string }[];
}

export interface Created {
  id: string;
  name: string;
  origin: string;
  config_path: string;
  run_command: string;
  /** "pass" when the Listing Injection Screen read the shop's text and no rule fired; null when the kit did not say. */
  screen: "pass" | null;
  readiness: Readiness[];
}

export interface ShopRow {
  id: string;
  name: string;
  archetype: string;
  origin: string;
  skus: string[];
  config_path: string;
}

export interface OpenNeed {
  id: string;
  sku_spec: string;
  allowed_conditions: string[];
  quantity: number;
  origin: string;
  delivery_window?: string;
}

export const emptyRow = (): ListingRow => ({ sku: "", condition: "new", amount: "", floor: "", url: "" });

export const emptyForm = (): SellForm => ({
  id: "", name: "", owner: "", archetype: "", mode: "discount", percent: "0", shipping: "0", perks: "", claims: "", rows: [emptyRow()],
});

/** The slug the API wants (lowercase letters, digits, - and _), made from the store name. */
export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
}

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

/** A finite number from form text, or null. "" is null: an empty box is not zero. */
export function num(text: string): number | null {
  const t = text.trim().replace(/^\$/, "").replace(/,/g, "");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** SellerConfig from the form. `problems` names boxes that are not numbers; everything else the API judges. */
export function buildConfig(f: SellForm): { config: Record<string, unknown>; problems: FieldError[] } {
  const problems: FieldError[] = [];
  const need = (label: string, text: string, field: string): number => {
    const n = num(text);
    if (n === null) problems.push({ field, message: `${label} must be a number` });
    return n ?? 0;
  };
  const margin = f.mode === "fixed_margin";
  const pct = need(margin ? "Margin" : "Discount", f.percent, "pricing");
  const pricing = margin ? { mode: "fixed_margin", margin_pct: pct } : { mode: "discount", discount: pct / 100 };
  const listings: Record<string, Record<string, unknown>> = {};
  f.rows.forEach((r, i) => {
    const at = `Listing ${i + 1}`;
    const sku = r.sku.trim().toLowerCase();
    const amount = need(`${at} ${margin ? "cost" : "price"}`, r.amount, `listings.${sku}`);
    const floor = need(`${at} floor`, r.floor, `listings.${sku}`);
    const base = margin ? { cost: amount } : { price: amount };
    const existing = listings[sku];
    if (!existing) {
      listings[sku] = { condition: r.condition, ...base, floor_by_condition: { [r.condition]: floor }, listing_url: r.url.trim() };
      return;
    }
    // A second row for the same sku is another condition line of it, bid as an alternative in the same sealed bid.
    const floors = existing.floor_by_condition as Record<string, number>;
    floors[r.condition] = floor;
    const alt = (existing.alt_lines ??= []) as Record<string, unknown>[];
    alt.push({ condition: r.condition, ...base, listing_url: r.url.trim() });
  });
  const shipping = need("Shipping", f.shipping, "shipping");
  const owner = f.owner.trim();
  const config: Record<string, unknown> = {
    id: f.id.trim() || slugify(f.name),
    name: f.name.trim(),
    ...(owner ? { owner } : {}),
    archetype: f.archetype.trim(),
    origin: "SIM",
    pricing,
    shipping,
    perks: lines(f.perks),
    claims: lines(f.claims),
    listings,
  };
  return { config, problems };
}

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

export function parseErrors(body: unknown): FieldError[] {
  if (!isObj(body) || !Array.isArray(body.errors)) return [];
  return body.errors.flatMap((e) =>
    isObj(e) && typeof e.field === "string" && typeof e.message === "string" ? [{ field: e.field, message: e.message }] : [],
  );
}

const READINESS: readonly string[] = ["blocks", "warns", "ready", "unreadable"];
const str = (v: unknown) => (typeof v === "string" ? v : "");

/** One report row, or null when it names no page. An unknown status is unreadable, never ready. */
function parseReadiness(r: unknown): Readiness | null {
  if (!isObj(r) || typeof r.url !== "string" || !r.url) return null;
  const status = (READINESS.includes(str(r.status)) ? r.status : "unreadable") as ReadinessStatus;
  const findings = Array.isArray(r.findings)
    ? r.findings.filter(isObj).map((f) => ({ severity: str(f.severity), what_an_agent_sees: str(f.what_an_agent_sees), fix: str(f.fix) }))
    : [];
  return { url: r.url, status, summary: str(r.summary), findings };
}

export function parseCreated(body: unknown): Created | null {
  if (!isObj(body)) return null;
  const { id, name, origin, config_path, run_command } = body;
  if (typeof id !== "string" || typeof name !== "string" || typeof config_path !== "string" || typeof run_command !== "string") return null;
  const screen = isObj(body.screen) && body.screen.verdict === "pass" ? "pass" : null;
  const readiness = Array.isArray(body.readiness) ? body.readiness.map(parseReadiness).filter((r): r is Readiness => r !== null) : [];
  return { id, name, origin: typeof origin === "string" ? origin : "SIM", config_path, run_command, screen, readiness };
}

export function parseShops(body: unknown): ShopRow[] {
  if (!Array.isArray(body)) return [];
  return body.flatMap((r) =>
    isObj(r) && typeof r.id === "string" && typeof r.name === "string"
      ? [{ id: r.id, name: r.name, archetype: String(r.archetype ?? ""), origin: String(r.origin ?? "SIM"),
           skus: Array.isArray(r.skus) ? r.skus.filter((s): s is string => typeof s === "string") : [], config_path: String(r.config_path ?? "") }]
      : [],
  );
}

export function parseNeeds(body: unknown): OpenNeed[] {
  if (!Array.isArray(body)) return [];
  return body.flatMap((r) =>
    isObj(r) && typeof r.id === "string" && typeof r.sku_spec === "string"
      ? [{ id: r.id, sku_spec: r.sku_spec, quantity: typeof r.quantity === "number" ? r.quantity : 1,
           allowed_conditions: Array.isArray(r.allowed_conditions) ? r.allowed_conditions.filter((c): c is string => typeof c === "string") : [],
           origin: typeof r.origin === "string" ? r.origin : "SIM", delivery_window: typeof r.delivery_window === "string" ? r.delivery_window : undefined }]
      : [],
  );
}

async function getJson(path: string, signal?: AbortSignal): Promise<unknown | null> {
  try {
    const r = await fetch(`${SELLER_KIT_URL}${path}`, { signal });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

/** null means the kit is down (say so; never show made-up rows). */
export const fetchShops = async (signal?: AbortSignal) => {
  const b = await getJson("/v1/sellers", signal);
  return b === null ? null : parseShops(b);
};
export const fetchNeeds = async (signal?: AbortSignal) => {
  const b = await getJson("/v1/needs/open", signal);
  return b === null ? null : parseNeeds(b);
};

export type SubmitResult = { kind: "created"; created: Created } | { kind: "refused"; errors: FieldError[] } | { kind: "offline" };

export async function submitConfig(config: Record<string, unknown>, replace = false): Promise<SubmitResult> {
  let r: Response;
  try {
    r = await fetch(`${SELLER_KIT_URL}/v1/sellers${replace ? "?replace=true" : ""}`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(config),
    });
  } catch {
    return { kind: "offline" };
  }
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    /* an answer that is not JSON is handled below */
  }
  if (r.status === 201) {
    const created = parseCreated(body);
    if (created) return { kind: "created", created };
  }
  const errors = parseErrors(body);
  return { kind: "refused", errors: errors.length ? errors : [{ field: "config", message: `the Seller Kit answered ${r.status} with nothing readable` }] };
}
