"use client";

import { cloneElement, useCallback, useEffect, useState } from "react";
import { Card, Code, Details, OriginChip, RecordedBanner } from "@/components/ui";
import recorded from "@/lib/fixtures/sell-recorded.json";
import { useApiBase } from "@/lib/useApiBase";
import { BRAND } from "@/lib/brand";
import { draftToForm, sellView, type Vetted } from "@/lib/sellerDraft";
import {
  CONDITIONS, SELLER_KIT_URL, buildConfig, emptyForm, emptyRow, fetchNeeds, fetchShops, parseNeeds, parseShops, slugify, submitConfig,
  type Created, type FieldError, type ListingRow, type OpenNeed, type SellForm, type ShopRow,
} from "@/lib/sellerKit";

const input = "tabular-nums min-h-11 w-full rounded-xl bg-surface px-4 py-2 text-[15px]/[20px] shadow-ring placeholder:text-muted";
const button = "btn min-h-11 rounded-xl bg-pulse px-5 py-2 font-medium text-pulse-ink disabled:opacity-60";

/** A numbered section heading, like the Seller Kit steps: a small mono disc, then the title. */
function Label({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 text-[13px]/[16px] font-medium text-muted">{children}</h2>;
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <h2 className="mb-3 flex items-center gap-3 text-[17px]/[22px] font-medium">
      <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-full bg-surface-2 font-mono text-[12px] font-medium text-ink-2">{n}</span>
      {children}
    </h2>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactElement<{ placeholder?: string }> }) {
  // The hint is the input's placeholder (#448: fewer words on screen; the example is still there while the field is empty).
  const input = hint && !children.props.placeholder ? cloneElement(children, { placeholder: hint }) : children;
  return (
    <label className="block min-w-0">
      <span className="mb-1 block text-[13px] font-medium">{label}</span>
      {input}
    </label>
  );
}

const EXAMPLE = "I run a small repair shop in Oakland. I have three refurbished 4070 Supers and some 750W PSUs, 90-day warranty, and I won't go below $520 on the cards.";

type DraftState = { kind: "idle" } | { kind: "busy" } | { kind: "note"; text: string } | { kind: "done"; vetted: Vetted };

/** Ask Claude (through /api/seller-draft) for a draft. Any failure is the plain form with a one-line note. */
async function askClaude(text: string): Promise<DraftState> {
  try {
    const r = await fetch("/api/seller-draft", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }) });
    const body: unknown = await r.json();
    const b = body as { ok?: boolean; note?: string; error?: string; draft?: Vetted["draft"]; questions?: string[]; dropped?: string[] };
    if (r.status === 400 && b.error) return { kind: "note", text: b.error };
    if (b.ok && b.draft) return { kind: "done", vetted: { draft: b.draft, questions: b.questions ?? [], dropped: b.dropped ?? [] } };
    return { kind: "note", text: b.note ?? "Claude is unavailable right now; fill in the form below." };
  } catch {
    return { kind: "note", text: "Claude is unavailable right now; fill in the form below." };
  }
}

/** /sell: a form that turns a shop into a SellerConfig and sends it to the Seller Kit API (:8791). */
export default function SellPage() {
  const [form, setForm] = useState<SellForm>(emptyForm);
  const [idTouched, setIdTouched] = useState(false);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  const [shops, setShops] = useState<ShopRow[] | null>(null);
  const [needs, setNeeds] = useState<OpenNeed[] | null>(null);
  const [chat, setChat] = useState("");
  const [draft, setDraft] = useState<DraftState>({ kind: "idle" });
  const kit = useApiBase(SELLER_KIT_URL);
  const view = sellView(kit.local);
  // the hosted site shows the recorded SIM snapshot (#398); locally, what the kit answers
  const shownShops = kit.local ? parseShops(recorded.shops) : shops;
  const shownNeeds = kit.local ? parseNeeds(recorded.needs) : needs;

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [s, n] = await Promise.all([fetchShops(signal), fetchNeeds(signal)]);
    if (signal?.aborted) return;
    setShops(s);
    setNeeds(n);
    setOffline(s === null && n === null);
  }, []);

  useEffect(() => {
    if (!kit.base) return; // not hydrated yet, or the hosted site: the Seller Kit runs locally, so never fetch 127.0.0.1
    const ctl = new AbortController();
    // refresh() sets state only after an await, so this is not a synchronous cascade
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh(ctl.signal);
    return () => ctl.abort();
  }, [kit.base, refresh]);

  const set = <K extends keyof SellForm>(k: K, v: SellForm[K]) => setForm((f) => ({ ...f, [k]: v }));
  const setRow = (i: number, patch: Partial<ListingRow>) =>
    setForm((f) => ({ ...f, rows: f.rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) }));
  const margin = form.mode === "fixed_margin";
  const shownId = idTouched ? form.id : slugify(form.name);

  const onDraft = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chat.trim()) return;
    setDraft({ kind: "busy" });
    const res = await askClaude(chat);
    setDraft(res);
    if (res.kind === "done") {
      // Prefill the form below. The owner edits it and confirms; the Seller Kit still validates it and Smell Test still screens it.
      setForm(draftToForm(res.vetted.draft));
      setIdTouched(false);
      setErrors([]);
      setCreated(null);
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreated(null);
    const { config, problems } = buildConfig({ ...form, id: shownId });
    if (problems.length) {
      setErrors(problems);
      return;
    }
    setBusy(true);
    setErrors([]);
    const res = await submitConfig(config);
    setBusy(false);
    if (res.kind === "offline") {
      setOffline(true);
      return;
    }
    setOffline(false);
    if (res.kind === "refused") {
      setErrors(res.errors);
      return;
    }
    setCreated(res.created);
    void refresh();
  };

  return (
    <div className="mx-auto grid w-full max-w-[1120px] grid-cols-[minmax(0,1fr)] gap-6 pt-2 md:px-4 md:pt-6">
      <header>
        <p className="text-[13px] leading-[18px] text-muted">Seller Kit</p>
        <h1 className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[28px] font-medium leading-[34px] tracking-[-0.015em]">
          Sell on {BRAND} <OriginChip origin="SIM" />
        </h1>
        <p className="mt-2 text-[15px]/[20px] text-ink-2">Describe your shop once. Your agent bids from it, never below your floor.</p>
        <Details summary="What this does"><p>The Seller Kit checks your shop and writes a config your own seller agent runs from. It cannot verify a real shop, so every shop it writes is SIM.</p></Details>
      </header>

      {kit.local && <RecordedBanner at={recorded.recorded_at} />}
      {/* #449 06:17: the Claude draft and the form always show; only the final create needs the Seller Kit (operator's machine) */}
      <>
      {offline && !kit.local && (
        <div className="flex flex-wrap items-center gap-x-3 text-[14px] text-ink-2">
          <span className="flex items-center gap-2"><span aria-hidden className="h-2 w-2 rounded-full bg-coral-mark" />Seller Kit offline. Nothing was sent.</span>
          <Details summary="How to start it" className="mt-0"><p>Run <Code>python3 scripts/launch.py up --only seller-kit</Code> and reload.</p></Details>
        </div>
      )}

      <Card>
        <form onSubmit={onDraft} className="grid gap-3">
          <h2 className="text-[17px]/[22px] font-medium">Create your seller agent with Claude</h2>
          <p className="text-[14px]/[20px] text-muted">
            Tell Claude about your shop in a few sentences. It fills in the form below. It only writes down what you say, and you decide every number.
          </p>
          <label className="block">
            <span className="sr-only">Describe your shop</span>
            <textarea
              className={`${input} min-h-28`}
              value={chat}
              maxLength={2000}
              placeholder={EXAMPLE}
              onChange={(e) => setChat(e.target.value)}
            />
          </label>
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" className="btn min-h-11 rounded-xl bg-pulse-soft px-5 py-2 font-medium text-pulse-soft-ink disabled:opacity-60" disabled={draft.kind === "busy" || !chat.trim()}>
              {draft.kind === "busy" ? "Drafting..." : "Draft with Claude"}
            </button>
            <button type="button" className="min-h-11 text-[14px] text-muted hover:text-ink" onClick={() => setChat(EXAMPLE)}>
              Use an example
            </button>
          </div>
          <div aria-live="polite">
            {draft.kind === "note" && <p className="text-[14px] text-ink-2">{draft.text}</p>}
            {draft.kind === "done" && (
              <div className="grid gap-2 text-[14px]">
                {draft.vetted.questions.length > 0 && (
                  <div>
                    <p className="text-ink-2">Claude needs {draft.vetted.questions.length === 1 ? "one more answer" : "two more answers"}. Add them to your text and draft again, or fill them in below.</p>
                    <ul className="mt-1 list-disc pl-5">
                      {draft.vetted.questions.map((q) => (
                        <li key={q}>{q}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {draft.vetted.dropped.length > 0 && (
                  <p className="text-muted">Left out because you did not say it: {draft.vetted.dropped.join("; ")}.</p>
                )}
                {draft.vetted.draft.lines.some((l) => l.quantity !== null) && (
                  <p className="text-muted">
                    Stock you named: {draft.vetted.draft.lines.filter((l) => l.quantity !== null).map((l) => `${l.quantity} x ${l.part}`).join(", ")}. The kit has no stock field, so it is not sent.
                  </p>
                )}
                <p className="text-muted">Add the link to each listing page yourself. Then send: the Seller Kit validates it and Smell Test screens your text.</p>
              </div>
            )}
          </div>
        </form>
      </Card>

      {draft.kind === "done" && (
        <p className="rounded-xl bg-pulse-soft px-4 py-2 text-[14px]/[20px] font-medium text-pulse-soft-ink">Drafted by Claude. Check every field.</p>
      )}

      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        <Card>
          <Step n={1}>Your shop</Step>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Store name">
              <input className={input} value={form.name} maxLength={60} required onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label="Owner (optional)">
              <input className={input} value={form.owner} maxLength={60} onChange={(e) => set("owner", e.target.value)} />
            </Field>
            <Field label="Kind of shop" hint="Local shop, refurbisher, online reseller.">
              <input className={input} value={form.archetype} maxLength={200} required onChange={(e) => set("archetype", e.target.value)} />
            </Field>
            <Field label="Agent id" hint="Lowercase letters, digits, - and _. Also the config file name.">
              <input
                className={input}
                value={shownId}
                maxLength={40}
                onChange={(e) => {
                  setIdTouched(true);
                  set("id", e.target.value);
                }}
              />
            </Field>
          </div>
        </Card>

        <Card>
          <Step n={2}>Pricing</Step>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="How you price">
              <select className={input} value={form.mode} onChange={(e) => set("mode", e.target.value as SellForm["mode"])}>
                <option value="discount">Discount off my list price</option>
                <option value="fixed_margin">Fixed margin on my cost</option>
              </select>
            </Field>
            <Field label={margin ? "Margin on cost (percent)" : "Discount (percent)"}>
              <input className={input} inputMode="decimal" value={form.percent} onChange={(e) => set("percent", e.target.value)} />
            </Field>
            <Field label="Flat shipping (USD)">
              <input className={input} inputMode="decimal" value={form.shipping} onChange={(e) => set("shipping", e.target.value)} />
            </Field>
          </div>
        </Card>

        <Card>
          <Step n={3}>What you sell</Step>
          <p className="mb-3 text-[13px] text-muted">One row per part and condition. Your agent never bids under the floor.</p>
          <Details summary="About floors and conditions" className="mb-3 mt-0"><p>The floor is the lowest unit price your agent will ever bid. Add a second row with the same part and another condition to offer both in one bid.</p></Details>
          <div className="grid gap-4">
            {form.rows.map((r, i) => (
              <fieldset key={i} className="grid gap-3 rounded-xl bg-surface-2 p-3 sm:grid-cols-2">
                <legend className="px-1 text-[13px]/[16px] font-medium text-muted">Listing {i + 1}</legend>
                <Field label="Part" hint="Lowercase, like: rtx 5070 ti or psu 750w">
                  <input className={input} value={r.sku} maxLength={80} required onChange={(e) => setRow(i, { sku: e.target.value })} />
                </Field>
                <Field label="Condition">
                  <select className={input} value={r.condition} onChange={(e) => setRow(i, { condition: e.target.value as ListingRow["condition"] })}>
                    {CONDITIONS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={margin ? "Your cost (USD)" : "List price (USD)"}>
                  <input className={input} inputMode="decimal" value={r.amount} required onChange={(e) => setRow(i, { amount: e.target.value })} />
                </Field>
                <Field label="Floor for this condition (USD)">
                  <input className={input} inputMode="decimal" value={r.floor} required onChange={(e) => setRow(i, { floor: e.target.value })} />
                </Field>
                <div className="sm:col-span-2">
                  <Field label="Listing page (http or https)">
                    <input className={input} value={r.url} required onChange={(e) => setRow(i, { url: e.target.value })} />
                  </Field>
                </div>
                {form.rows.length > 1 && (
                  <button
                    type="button"
                    className="min-h-11 justify-self-start text-[14px] text-muted hover:text-ink"
                    onClick={() => set("rows", form.rows.filter((_, j) => j !== i))}
                  >
                    Remove this listing
                  </button>
                )}
              </fieldset>
            ))}
          </div>
          <button
            type="button"
            className="btn mt-3 min-h-11 rounded-xl bg-pulse-soft px-5 py-2 text-[14px] font-medium text-pulse-soft-ink"
            onClick={() => set("rows", [...form.rows, emptyRow()])}
          >
            Add a listing
          </button>
        </Card>

        <Card>
          <Step n={4}>Perks and claims</Step>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Perks, one per line" hint="30-day returns, local pickup.">
              <textarea className={`${input} min-h-24`} value={form.perks} onChange={(e) => set("perks", e.target.value)} />
            </Field>
            <Field label="Claims, one per line" hint="New, sealed. Buyers can hold you to these.">
              <textarea className={`${input} min-h-24`} value={form.claims} onChange={(e) => set("claims", e.target.value)} />
            </Field>
          </div>
        </Card>

        {errors.length > 0 && (
          <Card>
            <p role="alert" className="flex items-center gap-2 font-medium">
              <span aria-hidden className="size-2 shrink-0 rounded-full bg-coral-mark" />
              Not sent. Fix {errors.length === 1 ? "this" : `these ${errors.length}`}:
            </p>
            <ul className="mt-2 list-disc pl-5 text-[14px]">
              {errors.map((er, i) => (
                <li key={i}>
                  <Code>{er.field}</Code> {er.message}
                </li>
              ))}
            </ul>
          </Card>
        )}

        <div>
          <button type="submit" className={button} disabled={busy || !view.canCreate}>
            {busy ? "Checking..." : "Create my seller agent config"}
          </button>
          {view.createNote && <p className="mt-2 text-[14px]/[20px] text-muted">{view.createNote}</p>}
        </div>
      </form>
      </>

      {created && (
        <Card>
          <Label>Config written</Label>
          <p>
            <strong>{created.name}</strong> <OriginChip origin={created.origin} /> is saved as <Code>{created.config_path}</Code>.
          </p>
          <p className="mt-3 text-[13px] font-medium">Run your agent</p>
          <pre className="mt-1 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-[12px]/[18px]">{created.run_command}</pre>
          {created.readiness && (
            <>
              <p className="mt-3 text-[13px] font-medium">Readiness</p>
              <p className="mt-1 text-[14px]">{created.readiness.line}</p>
              {created.readiness.listings.length > 0 && (
                <ul className="mt-1 grid gap-1 text-[13px] text-muted">
                  {created.readiness.listings.map((r) => (
                    <li key={r.sku}>
                      <Code>{r.sku}</Code>: {r.summary}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          <Details summary="What happens next">
            <ol className="list-decimal pl-5">
              <li>Run the command above on a machine with this repo and its agents environment. It starts your seller agent on a free port from 8016.</li>
              <li>The buyer agent only asks the sellers on its list. Your agent bids once the buyer is told its address; that is not automatic yet.</li>
              <li>In a sealed round your agent bids from your listings and never below your floor. All of this is SIM.</li>
            </ol>
          </Details>
        </Card>
      )}

      <Details summary="Shops written and open requests" className="mt-0">
        <div className="grid items-start gap-6 md:grid-cols-2">
      <Card>
        <Label>Shops written</Label>
        {shownShops === null ? (
          <p className="text-muted">{offline ? "Seller Kit offline." : "Loading..."}</p>
        ) : shownShops.length === 0 ? (
          <p className="text-muted">None yet.</p>
        ) : (
          <ul>
            {shownShops.map((s) => (
              <li key={s.id} className="border-t border-line py-2.5 text-[14px] first:border-t-0">
                <strong>{s.name}</strong> <OriginChip origin={s.origin} />{" "}
                <span className="text-muted">
                  {s.archetype}: {s.skus.join(", ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <Label>Open requests</Label>
        {shownNeeds === null ? (
          <p className="text-muted">{offline ? "Seller Kit offline." : "Loading..."}</p>
        ) : shownNeeds.length === 0 ? (
          <p className="text-muted">No open requests. They appear when a buyer posts one.</p>
        ) : (
          <ul>
            {shownNeeds.map((n) => (
              <li key={n.id} className="border-t border-line py-2.5 text-[14px] first:border-t-0">
                {n.quantity} x <strong>{n.sku_spec}</strong>{" "}
                <span className="text-muted">
                  ({n.allowed_conditions.join(" or ")}
                  {n.delivery_window ? `, ${n.delivery_window}` : ""})
                </span>{" "}
                <OriginChip origin={n.origin} />
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-[12px] text-muted">Buyer caps are never shown.</p>
      </Card>
        </div>
      </Details>
    </div>
  );
}
