"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, Code, Label, OriginChip, RecordedBanner, RunsLocally } from "@/components/ui";
import recorded from "@/lib/fixtures/sell-recorded.json";
import { useApiBase } from "@/lib/useApiBase";
import { BRAND } from "@/lib/brand";
import {
  CONDITIONS, SELLER_KIT_URL, buildConfig, emptyForm, emptyRow, fetchNeeds, fetchShops, parseNeeds, parseShops, slugify, submitConfig,
  type Created, type FieldError, type ListingRow, type OpenNeed, type SellForm, type ShopRow,
} from "@/lib/sellerKit";

const input = "min-h-11 w-full rounded-xl border-0 bg-surface px-3.5 py-2 text-[16px] text-ink shadow-ring outline-none placeholder:text-muted/70 focus:shadow-[var(--shadow-ring),var(--shadow-focus)]";
const button = "btn min-h-12 rounded-xl bg-pulse px-6 py-2 text-[15px] font-medium text-pulse-ink hover:shadow-card disabled:opacity-60";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-[13px] font-medium text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-[12px] leading-4 text-muted">{hint}</span>}
    </label>
  );
}

/** /sell: a plain form that turns a shop into a SellerConfig and sends it to the Seller Kit API (:8791). No styling work here: Vedant owns the UI. */
export default function SellPage() {
  const [form, setForm] = useState<SellForm>(emptyForm);
  const [idTouched, setIdTouched] = useState(false);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  const [shops, setShops] = useState<ShopRow[] | null>(null);
  const [needs, setNeeds] = useState<OpenNeed[] | null>(null);
  const kit = useApiBase(SELLER_KIT_URL);
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
    <div className="mx-auto grid w-full max-w-3xl grid-cols-[minmax(0,1fr)] gap-6 pt-2 md:pt-10">
      <header className="grid gap-4">
        <span className="inline-flex items-center gap-2 text-[15px] font-medium text-ink-2">
          <span className="dot text-live" aria-hidden /> Seller Kit <OriginChip origin="SIM" />
        </span>
        <h1 className="text-[34px] font-medium leading-[38px] tracking-[-0.025em] text-balance md:text-[48px] md:leading-[52px]">
          Sell on {BRAND}. <span className="text-muted">Your agent bids, never below your floor.</span>
        </h1>
        <p className="max-w-[60ch] text-[17px] leading-[26px] text-ink-2">
          Describe your shop once. The Seller Kit checks it and writes a config your own seller agent runs from. Everything here is a simulation:
          the kit cannot verify a real shop, so shops it writes are SIM.
        </p>
        <ol className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {["Describe your shop", "Set a floor per condition", "Get your agent config", "Your agent bids sealed"].map((t, i) => (
            <li key={t} className="flex items-center gap-2.5 rounded-xl bg-surface px-3 py-2.5 text-[13px] font-medium leading-[18px] shadow-ring">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-surface-2 font-mono text-[12px]">{i + 1}</span>{t}
            </li>
          ))}
        </ol>
      </header>

      {kit.local ? (
        <>
        <RecordedBanner at={recorded.recorded_at} />
        <RunsLocally what="The Seller Kit">
          It checks your shop and writes a config file that your own seller agent runs from, on your machine. This hosted page cannot reach it,
          so the form is not shown and nothing here is sent anywhere. Below is what the kit answered when it was recorded.
        </RunsLocally>
        </>
      ) : (
      <>
      {offline && (
        <Card stripe="coral">
          <p className="font-medium">Seller Kit offline.</p>
          <p className="mt-1 text-muted">
            Nothing was sent. Start it with <Code>python3 scripts/launch.py up --only seller-kit</Code> and reload.
          </p>
        </Card>
      )}

      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        <Card>
          <Label>Your shop</Label>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Store name">
              <input className={input} value={form.name} maxLength={60} required onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label="Owner (optional)">
              <input className={input} value={form.owner} maxLength={60} onChange={(e) => set("owner", e.target.value)} />
            </Field>
            <Field label="What kind of shop" hint="For example: local shop, refurbisher, online reseller.">
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
          <Label>Pricing</Label>
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
          <Label>What you sell</Label>
          <p className="mb-3 text-[13px] text-muted">
            One row per part and condition. The floor is the lowest unit price your agent will ever bid, so it never goes under it. Add a second row with
            the same part and another condition to offer both in one bid.
          </p>
          <div className="grid gap-4">
            {form.rows.map((r, i) => (
              <fieldset key={i} className="grid gap-4 rounded-xl border border-line bg-surface-2/60 p-4 sm:grid-cols-2">
                <legend className="px-1 text-[12px] text-muted">Listing {i + 1}</legend>
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
            className="btn mt-4 min-h-11 rounded-xl bg-surface px-4 py-2 text-[14px] font-medium text-ink shadow-ring hover:bg-surface-2"
            onClick={() => set("rows", [...form.rows, emptyRow()])}
          >
            Add a listing
          </button>
        </Card>

        <Card>
          <Label>Perks and claims</Label>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Perks (one per line)" hint="For example: 30-day returns, free local pickup.">
              <textarea className={`${input} min-h-24`} value={form.perks} onChange={(e) => set("perks", e.target.value)} />
            </Field>
            <Field label="Claims about your parts (one per line)" hint="For example: new, sealed. A buyer can hold you to these.">
              <textarea className={`${input} min-h-24`} value={form.claims} onChange={(e) => set("claims", e.target.value)} />
            </Field>
          </div>
        </Card>

        {errors.length > 0 && (
          <Card stripe="coral">
            <p role="alert" className="font-medium">
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
          <button type="submit" className={button} disabled={busy}>
            {busy ? "Checking..." : "Create my seller agent config"}
          </button>
        </div>
      </form>
      </>
      )}

      {created && (
        <Card stripe="mint">
          <Label>Config written</Label>
          <p>
            <strong>{created.name}</strong> <OriginChip origin={created.origin} /> is saved as <Code>{created.config_path}</Code>.
          </p>
          <p className="mt-3 text-[13px] font-medium">Run your agent</p>
          <pre className="mt-1 overflow-x-auto rounded-lg bg-soft p-3 font-mono text-[12px]">{created.run_command}</pre>
          <p className="mt-3 text-[13px] font-medium">What happens next</p>
          <ol className="mt-1 list-decimal pl-5 text-[14px] text-muted">
            <li>Run the command above on a machine with this repo and its agents environment. It starts your seller agent on a free port from 8016.</li>
            <li>The buyer agent only asks the sellers on its list. Your agent bids once the buyer is told its address; that is not automatic yet.</li>
            <li>In a sealed round your agent bids from your listings and never below your floor. All of this is SIM.</li>
          </ol>
        </Card>
      )}

      <Card>
        <Label>Shops written so far</Label>
        {shownShops === null ? (
          <p className="text-muted">{offline ? "Seller Kit offline." : "Loading..."}</p>
        ) : shownShops.length === 0 ? (
          <p className="text-muted">None yet.</p>
        ) : (
          <ul className="grid gap-2">
            {shownShops.map((s) => (
              <li key={s.id} className="text-[14px]">
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
        <Label>Open needs you could bid on</Label>
        {shownNeeds === null ? (
          <p className="text-muted">{offline ? "Seller Kit offline." : "Loading..."}</p>
        ) : shownNeeds.length === 0 ? (
          <p className="text-muted">No open needs.</p>
        ) : (
          <ul className="grid gap-2">
            {shownNeeds.map((n) => (
              <li key={n.id} className="text-[14px]">
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
        <p className="mt-2 text-[12px] text-muted">The buyer&apos;s spending cap is never shown to sellers.</p>
      </Card>
    </div>
  );
}
