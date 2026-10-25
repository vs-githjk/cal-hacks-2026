// The build panel: the planner's parts, sellers and total for one build, against the cap, with the owned parts kept.
// Pure: give it a BuildResult (SAMPLE_BUILD until the market's build rounds are live) and it draws.

import { capPercent, partRows, PART_NAMES, type BuildResult } from "@/lib/build";
import { Card, Label, OriginChip, Pill, Stat, money } from "./ui";

const STATUS = { locked: ["done", "Build locked"], open: ["hunting", "Rounds running"], blocked: ["hold", "Blocked, nothing paid"] } as const;

export function BuildPanel({ build: b, origin = "SIM" }: { build: BuildResult; origin?: string }) {
  const rows = partRows(b);
  const total = b.totalCents / 100;
  const cap = b.capCents / 100;
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
        <div className="h-full bg-ink" style={{ width: `${capPercent(b.totalCents, b.capCents)}%` }} />
      </div>
      <ul className="grid gap-1.5">
        {rows.map((r) => (
          <li key={r.part} className="grid grid-cols-[64px_1fr_auto] items-baseline gap-x-3 rounded-lg px-2 py-1.5 even:bg-soft">
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
              <span className="block text-[14px] font-semibold">{r.price === null ? "?" : money(r.price)}</span>
              <span className={`block text-[11px] ${r.overBy ? "text-amber" : "text-muted"}`}>
                {r.overBy ? `${money(r.overBy)} over ${money(r.budget)}` : `budget ${money(r.budget)}`}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {!!b.comparisons?.length && (
        <div className="mt-3 rounded-lg border border-line px-2 py-1.5">
          <p className="text-[12px] font-semibold uppercase tracking-[0.04em] text-muted">Comparison, not a bid</p>
          <ul className="mt-1 grid gap-1">
            {b.comparisons.map((c) => (
              <li key={`${c.part}-${c.seller}`} className="text-[12px] text-muted">
                {PART_NAMES[c.part] ?? c.part}, {c.seller} <OriginChip origin={c.origin} /> <span className="tabular-nums">{money(c.priceCents / 100)}</span>. {c.note}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!b.checks?.length && (
        <div className="mt-3">
          <p className="text-[12px] font-semibold uppercase tracking-[0.04em] text-muted">Fit checks</p>
          <ul className="mt-1 grid gap-1">
            {b.checks.map((c, i) => (
              <li key={i} className="text-[12px]">
                {PART_NAMES[c.a] ?? c.a} and {PART_NAMES[c.b] ?? c.b}: {c.detail}{" "}
                <span className={c.state === "clash" ? "font-semibold text-coral" : c.state === "unknown" ? "text-muted" : ""}>{c.state}</span>{" "}
                <span className="font-mono text-muted">{c.source}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {b.approval && <p className="mt-3 text-[12px]">Approval: {b.approval.state}, {money(b.approval.total)} across {b.approval.sellers} sellers</p>}
      {Object.keys(b.owned).length > 0 && (
        <p className="mt-3 text-[12px] text-muted">
          Kept, no round: {Object.entries(b.owned).map(([k, name]) => `${PART_NAMES[k] ?? k} (${name})`).join(", ")}
        </p>
      )}
      {!!b.rejected && <p className="mt-3 text-[12px] text-amber">{b.rejected} rows from the feed failed the build shape and are not shown.</p>}
    </Card>
  );
}
