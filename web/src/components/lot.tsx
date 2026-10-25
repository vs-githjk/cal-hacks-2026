"use client";
// Lot Wall: Vidyut's one order on the left, the seller's view of a pooled lot as a wall of bricks on the right.
// One brick is REAL (Vidyut's, gold, labelled); the rest are SIM builders (grey, labelled). Reads only lib/lot.ts.
import { useState } from "react";
import { conditionsText, deadlineText, demandText, realOrder, STAGE_LINE, type Lot, type LotOrder } from "@/lib/lot";
import { Card, Code, Label, OriginChip, Stat, Tag, money } from "./ui";

// The one brick that is not a design token: gold marks the single REAL order. Dark ink text keeps contrast in both themes.
const GOLD = "border-[#9a6f00] bg-[#e5b132] text-[#121417]";

function Brick({ o, selected, onPick }: { o: LotOrder; selected: boolean; onPick: () => void }) {
  const real = o.label === "REAL";
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={selected}
      aria-label={`${o.label} order, ${o.name}, up to ${money(o.cap)}`}
      className={`flex min-h-14 min-w-0 flex-col items-center justify-center rounded-lg border px-1 py-1.5 text-center ${
        real ? GOLD : "border-line bg-slate-soft text-slate"
      } ${selected ? "outline outline-2 outline-offset-2 outline-accent" : ""}`}
    >
      <span className="font-mono text-[10px] font-bold tracking-[0.06em]">{o.label}</span>
      <span className="text-[14px] font-semibold tabular-nums">{money(o.cap)}</span>
    </button>
  );
}

function OrderCard({ o }: { o: LotOrder }) {
  return (
    <Card stripe="amber">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Label>{o.label === "REAL" ? "Your goal" : "Order"}</Label>
        <span className={`rounded-md border px-1.5 py-0.5 font-mono text-[11px] font-bold ${o.label === "REAL" ? GOLD : "border-line bg-slate-soft text-slate"}`}>{o.label}</span>
      </div>
      <p className="text-[28px] font-semibold tracking-[-0.01em] tabular-nums">{money(o.cap)}</p>
      <p className="text-[13px] text-muted">the most {o.name} will pay for one RTX 5070 Ti, before sales tax</p>
      <dl className="mt-3 grid grid-cols-2 gap-2">
        <Stat label="Condition" value={conditionsText(o.conditions)} />
        <Stat label="Case fits" value={o.caseMaxGpuMm ? `${o.caseMaxGpuMm} mm` : "unknown"} />
        <Stat label="Power supply" value={o.psuWatts ? `${o.psuWatts} W` : "unknown"} />
        <Stat label="Needed" value={deadlineText(o.deadline)} />
      </dl>
    </Card>
  );
}

export function LotScreen({ state, lot }: { state: "loading" | "offline" | "ready"; lot: Lot | null }) {
  const real = lot ? realOrder(lot) : null;
  const [picked, setPicked] = useState<string | null>(null);
  const shown = lot && real ? (lot.orders.find((o) => o.id === picked) ?? real) : null;
  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="text-[18px] font-bold tracking-[-0.01em]">
          Lot Wall <span className="font-medium text-muted">what a seller sees when requests pool</span>
        </div>
        <OriginChip origin="SIM" />
      </div>
      <p className="rounded-[10px] border border-dashed border-line px-3 py-2.5 text-[14px] text-ink">{STAGE_LINE}</p>
      {state === "loading" ? (
        <p className="text-muted">Loading the lot...</p>
      ) : state === "offline" || !lot || !real || !shown ? (
        <Card>
          <p className="text-[22px] font-medium">The lot is not available.</p>
          <p className="mt-1 text-muted">
            Nothing is shown because nothing could be read. Write it with <Code>python3 -m sim.lot_wall</Code> and reload this page.
          </p>
        </Card>
      ) : (
        <div className="grid gap-3.5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
          <div className="grid content-start gap-3.5">
            <OrderCard o={shown} />
            {shown.label !== "REAL" && (
              <button type="button" onClick={() => setPicked(null)} className="min-h-11 rounded-lg border border-line px-4 py-2 text-[14px] font-medium">
                Back to your goal
              </button>
            )}
          </div>
          <Card>
            <div className="mb-2.5 flex flex-wrap items-center gap-2">
              <Label>The pooled lot, seller&apos;s view</Label>
              <Tag>{lot.orders.length} orders</Tag>
              <Tag>1 REAL</Tag>
              <Tag>{lot.orders.length - 1} SIM</Tag>
            </div>
            <ul className="grid grid-cols-4 gap-2 sm:grid-cols-6 xl:grid-cols-8" aria-label={`${lot.orders.length} pooled orders for one RTX 5070 Ti`}>
              {lot.orders.map((o) => (
                <li key={o.id} className="min-w-0">
                  <Brick o={o} selected={o.id === shown.id} onPick={() => setPicked(o.id === real.id ? null : o.id)} />
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[13px] text-muted">
              Gold is the buyer&apos;s real request. Grey bricks are simulated builders from our wind tunnel, one request each. Each brick shows the most that order will pay, before sales tax.
            </p>
            <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Stat label="Median ceiling" value={money(lot.capMedian)} />
              <Stat label="Lowest ceiling" value={money(lot.capMin)} />
              <Stat label="Highest ceiling" value={money(lot.capMax)} />
            </dl>
            {lot.demandAt.length > 0 && (
              <div className="mt-4">
                <Label>Orders that can pay at each price</Label>
                <ul className="grid gap-1.5">
                  {lot.demandAt.map((d) => (
                    <li key={d.price} className="grid grid-cols-[64px_1fr_56px] items-center gap-2 text-[13px]">
                      <span className="font-mono tabular-nums">{money(d.price)}</span>
                      <span className="h-2.5 overflow-hidden rounded-full bg-soft" aria-hidden>
                        <span className="block h-full rounded-full bg-slate" style={{ width: `${(d.count / lot.orders.length) * 100}%` }} />
                      </span>
                      <span className="text-right tabular-nums text-muted">{demandText(d.count, lot.orders.length)}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[12px] text-muted">Demand only. This is not a sale or a market result.</p>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
