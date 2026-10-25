// The build panel: the planner's parts, sellers and total for one build, against the cap, with the owned parts kept.
// Pure: give it a BuildResult (SAMPLE_BUILD until the market's build rounds are live) and it draws.

import { partRows, PART_NAMES, type BuildResult } from "@/lib/build";
import { Card, Label, OriginChip, Pill, Stat, money } from "./ui";
import { BoutBadge, type BoutStatus } from "./arena";
import { roman } from "@/lib/roman";

const STATUS = { locked: ["done", "Build locked"], open: ["hunting", "Rounds running"], blocked: ["hold", "Blocked, nothing paid"] } as const;

export function BuildPanel({ build: b, origin = "SIM" }: { build: BuildResult; origin?: string }) {
  const rows = partRows(b);
  const total = b.totalCents / 100;
  const cap = b.capCents / 100;
  const firstOpen = rows.findIndex((r) => r.state === "open");
  // locked and swapped parts are won; the first open part of a running build is in the arena; other open parts wait.
  const boutOf = (state: string, i: number): BoutStatus => (state !== "open" ? "won" : b.status === "open" && i === firstOpen ? "in-arena" : "waiting");
  const locked = b.status === "locked";
  return (
    <Card stripe={b.status === "locked" ? "mint" : b.status === "open" ? "ink" : "amber"}>
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <Label>Your build</Label>
        <div className="flex items-center gap-2">
          <OriginChip origin={origin} />
          <Pill tone={STATUS[b.status][0]}>{STATUS[b.status][1]}</Pill>
        </div>
      </div>
      <dl className="mb-3 grid grid-cols-3 gap-2">
        <Stat label="Total" value={money(total)} sub={`of ${money(cap)} cap`} />
        <Stat label="Parts" value={String(rows.filter((r) => r.state !== "open").length)} sub={`of ${rows.length}`} />
        <Stat label="Sellers" value={String(b.sellers.length)} />
      </dl>
      <div role="img" aria-label={`${money(total)} of the ${money(cap)} cap`} className="mb-3 h-2 overflow-hidden rounded-full bg-soft">
        <div className="h-full bg-accent" style={{ width: `${Math.min(100, (total / cap) * 100)}%` }} />
      </div>
      <ul className="grid gap-1.5">
        {rows.map((r, i) => (
          <li key={r.part} className="grid grid-cols-[auto_64px_1fr_auto] items-baseline gap-x-3 rounded-lg px-2 py-1.5 even:bg-soft">
            <span className="w-7 font-display text-[16px] text-accent" aria-label={`Bout ${i + 1}`}>{roman(i + 1)}</span>
            <span className="text-[12px] font-semibold uppercase tracking-[0.04em] text-muted">{r.label}</span>
            <span className="min-w-0">
              <span className="block truncate text-[14px] font-medium">{r.name}</span>
              <span className="block text-[12px] text-muted">
                {r.seller || "Waiting for its round"}
                {r.origin && <span className="ml-1.5"><OriginChip origin={r.origin} /></span>}
                {r.state === "swapped" && <span className="ml-1.5 font-semibold text-amber">swapped after a clash</span>}
              </span>
            </span>
            <span className="text-right tabular-nums">
              <span className="mb-0.5 block"><BoutBadge status={boutOf(r.state, i)} /></span>
              <span className="block text-[14px] font-semibold">{r.price === null ? "?" : money(r.price)}</span>
              <span className={`block text-[11px] ${r.overBy ? "text-amber" : "text-muted"}`}>
                {r.overBy ? `${money(r.overBy)} over ${money(r.budget)}` : `budget ${money(r.budget)}`}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <div className={`mt-3 flex items-baseline justify-between border-t-2 pt-2.5 ${locked ? "border-accent" : "border-line-2"}`}>
        <span className="font-display text-[13px] uppercase tracking-[0.14em] text-ink-2">Build total</span>
        <span className={`font-display text-[22px] tabular-nums ${locked ? "text-accent" : "text-ink-2"}`}>{money(total)}</span>
      </div>
      {Object.keys(b.owned).length > 0 && (
        <p className="mt-3 text-[12px] text-muted">
          Kept, no round: {Object.entries(b.owned).map(([k, name]) => `${PART_NAMES[k] ?? k} (${name})`).join(", ")}
        </p>
      )}
      {!!b.rejected && <p className="mt-3 text-[12px] text-amber">{b.rejected} rows from the feed failed the build shape and are not shown.</p>}
    </Card>
  );
}
