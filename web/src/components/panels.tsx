// Dashboard panels drawn to scale, and the designed "nothing to show yet" states. A panel is never blank:
// before pairing or while the market is out of reach it says what it will show and why it is empty.

import { callLine, rulerLayout, type RulerInput } from "@/lib/geometry";
import type { GoalView } from "@/lib/screens";
import { Card, Label, OriginChip, money } from "./ui";

/** The allowance drawn against the goal cap: the filled part buys itself, the hatched part calls the buyer first. */
export function AllowancePanel({ allowance: a, cap }: { allowance: GoalView["allowance"]; cap: number | null }) {
  const line = a && cap !== null ? callLine(a.perPurchase, cap) : null;
  return (
    <Card>
      <Label>Allowance</Label>
      {!a ? (
        <p className="text-[13px] text-muted">No spending rule is recorded for you yet.</p>
      ) : a.perPurchase <= 0 ? (
        <p className="text-[18px] font-medium">Every buy calls you first.</p>
      ) : (
        <div className="grid gap-3">
          <p className="text-[34px] font-semibold leading-none tracking-[-0.03em] tabular-nums">
            {money(a.perPurchase)}
            <small className="ml-2 text-[12px] font-normal tracking-normal text-muted">per buy without a call</small>
          </p>
          {line && cap !== null ? (
            <div role="img" aria-label={`Allowance ${money(a.perPurchase)} drawn against the ${money(cap)} cap. Above the allowance the agent calls you first.`}>
              <div className="relative h-[26px] rounded-md border border-line-2 bg-[repeating-linear-gradient(135deg,var(--soft)_0_6px,var(--panel)_6px_12px)]">
                <div className="absolute inset-y-0 left-0 rounded-l-[5px] bg-ink" style={{ width: `${line.autoPct}%` }} />
              </div>
              <div className="mt-1 flex justify-between font-mono text-[11px] text-muted tabular-nums">
                <span>$0</span>
                <span>{money(cap)} cap</span>
              </div>
              <p className="mt-2 flex flex-wrap gap-x-4 text-[12px] text-ink-2">
                <span><i className="mr-1.5 inline-block h-2.5 w-3.5 rounded-sm bg-ink align-[-1px]" />Buys itself, sends a receipt</span>
                <span><i className="mr-1.5 inline-block h-2.5 w-3.5 rounded-sm border border-line-2 bg-[repeating-linear-gradient(135deg,var(--line-2)_0_3px,var(--panel)_3px_6px)] align-[-1px]" />Calls you first</span>
              </p>
            </div>
          ) : (
            <p className="text-[13px] text-muted">The goal cap is needed to draw this to scale.</p>
          )}
          <p className="text-[13px] tabular-nums text-muted">
            {money(a.spent)} of {money(a.periodLimit)} used this {a.period}. Ladder step {a.ladderStep}: each clean delivery raises it.
          </p>
        </div>
      )}
    </Card>
  );
}

export interface Clearance {
  cards: (RulerInput & { origin: string })[];
  limitMm: number;
  told: string;
}

/** Card lengths against the case limit on one shared axis: the limit is at the same x on every row. */
export function ClearanceRuler({ cards, limitMm, told }: Clearance) {
  const l = rulerLayout(cards, limitMm);
  if (!l) return <p className="text-[13px] text-muted">No card lengths are recorded to compare with the {limitMm} mm limit.</p>;
  const origin = new Map(cards.map((c) => [c.label, c.origin]));
  return (
    <div className="grid gap-1 rounded-xl border border-line p-3" role="img" aria-label={`Card lengths against the ${limitMm} mm case limit`}>
      <p className="flex flex-wrap justify-between gap-2 text-[13px]">
        <b className="font-medium">Card length against your case</b>
        <span className="font-mono text-[11px] text-muted">{l.min} to {l.max} mm · {told}</span>
      </p>
      <div className="grid gap-0.5">
        {l.rows.map((r) => (
          <div key={r.label} className="grid min-h-[26px] grid-cols-[minmax(0,110px)_minmax(0,1fr)_84px] items-center gap-2.5 sm:grid-cols-[minmax(0,150px)_minmax(0,1fr)_92px]">
            <span className="min-w-0 text-[12px] leading-tight">{r.label} <OriginChip origin={origin.get(r.label) ?? "SIM"} /></span>
            <span className="relative block h-3">
              <span className="absolute inset-x-0 top-[5px] h-px bg-line" />
              <span className={`absolute inset-y-0.5 left-0 rounded-r-[3px] ${r.fits ? "bg-ink" : "border border-ink-2 bg-[repeating-linear-gradient(90deg,var(--ink-2)_0_2px,transparent_2px_5px)]"}`} style={{ width: `${r.pct}%` }} />
              <span aria-hidden className="absolute -inset-y-1 border-l-2 border-ink" style={{ left: `${r.limitPct}%` }} />
            </span>
            <span className="text-right font-mono text-[11px] tabular-nums">
              {r.mm} mm<small className="block font-sans text-[10px] text-muted">{r.fits ? `fits, ${r.deltaMm} mm spare` : `${r.deltaMm} mm too long`}</small>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Owned parts. No approved buyer-private source exists yet, so unless cards are passed in this says so; nothing is inferred from text. */
export function OwnedPartsPanel({ clearance }: { clearance?: Clearance }) {
  return (
    <Card>
      <Label>Already in your rig</Label>
      {clearance ? (
        <ClearanceRuler {...clearance} />
      ) : (
        <>
          <p className="text-[18px] font-medium">Unavailable</p>
          <p className="mt-1 text-[13px] text-muted">No approved buyer-private record of owned parts exists yet, so none are listed and no fit limit can be drawn.</p>
        </>
      )}
    </Card>
  );
}

/** Before pairing or while the market is out of reach: what each panel will show, so the dashboard is never empty. */
export function PanelPreviews({ reason }: { reason: string }) {
  const panels: [string, string][] = [
    ["Goal", "What you asked for, the cap and the deadline, once this screen is paired."],
    ["Allowance", "How much the agent may spend without calling you, drawn against the goal cap."],
    ["Already in your rig", "Parts you own and how far a card may reach in your case. Not connected to a source yet."],
    ["Purchase memory", "Past purchases, vetoes and seller lessons from the recorded run."],
  ];
  return (
    <div className="grid gap-3.5">
      <p className="rounded-[10px] border border-dashed border-line px-3 py-2.5 text-[13px] text-muted" role="status">{reason}</p>
      <div className="grid gap-3.5 md:grid-cols-2">
        {panels.map(([title, text]) => (
          <Card key={title}>
            <Label>{title}</Label>
            <p className="text-[13px] text-muted">{text}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
