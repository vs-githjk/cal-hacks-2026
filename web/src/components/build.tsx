// The build panel: the planner's parts, sellers and total for one build, against the cap, with the owned parts kept.
// Pure: give it a BuildResult (SAMPLE_BUILD until the market's build rounds are live) and it draws.

import { partRows, PART_NAMES, type BuildResult } from "@/lib/build";
import { Card, Label, OriginChip, money } from "./ui";
import { ProofLines } from "./ProofLines";

const STATUS = {
  locked: ["bg-mint", "Locked", "text-ink"],
  open: ["bg-pulse", "Rounds running", "text-ink-2"],
  blocked: ["bg-coral", "Blocked, nothing paid", "text-ink-2"],
} as const;

const Dot = ({ cls }: { cls: string }) => <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${cls}`} aria-hidden />;

export function BuildPanel({ build: b, origin = "SIM" }: { build: BuildResult; origin?: string }) {
  const rows = partRows(b);
  const total = b.totalCents / 100;
  const cap = b.capCents / 100;
  const picked = rows.filter((r) => r.price !== null).length;
  const [dot, text, tone] = STATUS[b.status];
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-2">
        <Label>Your build</Label>
        <div className="flex items-center gap-2">
          <span className={`flex items-center gap-1.5 text-[13px] ${tone}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
            {text}
          </span>
          <OriginChip origin={origin} />
        </div>
      </div>
      <div className="flex items-end justify-between gap-2">
        <p>
          <span className="font-mono text-[32px]/[36px] font-medium tabular-nums text-ink">{money(total)}</span>
          <span className="text-[15px] text-muted"> of {money(cap)}</span>
        </p>
        <p className="text-[13px] text-muted">{picked} of {rows.length} parts, {b.sellers.length} sellers</p>
      </div>
      <div role="img" aria-label={`${money(total)} of the ${money(cap)} cap`} className="mt-3 mb-4 flex h-3 gap-[2px] overflow-hidden rounded-full bg-surface-2">
        {rows.map((r) => r.price !== null && (
          <div key={r.part} className={r.state === "swapped" ? "bg-pulse/70" : "bg-pulse"} style={{ width: `${(r.price * 100) / cap}%` }} title={`${r.label} ${money(r.price)}`} />
        ))}
      </div>
      <ul className="divide-y divide-line border-y border-line">
        {rows.map((r) => {
          const st = b.partStatus?.[r.part];
          return (
            <li key={r.part} className="grid grid-cols-[72px_minmax(0,1fr)_auto_auto] items-baseline gap-x-4 py-2.5">
              <span className="text-[13px] text-muted">{r.label}</span>
              <span className="min-w-0">
                <span className="block truncate text-[14px] text-ink">{r.name}</span>
                <span className="block text-[12.5px] text-muted">
                  {r.price === null ? (
                    st === "bidding" ? <span className="text-ink-2"><Dot cls="bg-pulse" />In a round</span>
                    : st === "failed" ? <span className="text-ink-2"><Dot cls="bg-coral" />{r.note}</span>
                    : "Not started"
                  ) : (
                    <>
                      {r.seller || r.note}
                      {r.origin && <span className="ml-2"><OriginChip origin={r.origin} /></span>}
                      {r.state === "swapped" && <span className="text-muted">, swapped after a socket clash</span>}
                    </>
                  )}
                </span>
              </span>
              {r.price === null ? <span /> : <span className="text-right text-[14px] font-medium tabular-nums">{money(r.price)}</span>}
              {r.price === null ? (
                <span className="min-w-[88px] text-right text-[12.5px] tabular-nums text-muted">budget {money(r.budget)}</span>
              ) : r.overBy > 0 ? (
                <span className="min-w-[88px] text-right text-[12.5px] tabular-nums text-amber">{money(r.overBy)} over</span>
              ) : (
                <span className="min-w-[88px] text-right text-[12.5px] tabular-nums text-muted">{money(r.budget - r.price)} under</span>
              )}
              {r.price !== null && <ProofLines build={b} part={r.part} />}
            </li>
          );
        })}
      </ul>
      {!!b.comparisons?.length && (
        <div className="mt-4">
          <p className="text-[13px] font-medium text-ink-2">Comparison, not a bid</p>
          <ul className="mt-1 grid gap-1">
            {b.comparisons.map((c) => (
              <li key={`${c.part}-${c.seller}`} className="text-[12.5px] text-muted">
                {PART_NAMES[c.part] ?? c.part}, {c.seller} <OriginChip origin={c.origin} /> <span className="tabular-nums">{money(c.priceCents / 100)}</span>. {c.note}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!b.checks?.length && (
        <div className="mt-4">
          <p className="text-[13px] font-medium text-ink-2">Fit checks</p>
          <ul className="mt-1 grid gap-1">
            {b.checks.map((c, i) => (
              <li key={i} className="text-[12.5px] text-muted">
                {PART_NAMES[c.a] ?? c.a} and {PART_NAMES[c.b] ?? c.b}: {c.detail}{" "}
                <span className={c.state === "clash" ? "font-medium text-coral" : ""}>{c.state}</span>{" "}
                <span className="font-mono">{c.source}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {b.approval && <p className="mt-4 text-[12.5px] text-muted">Approval: {b.approval.state}, {money(b.approval.total)} across {b.approval.sellers} sellers</p>}
      {Object.keys(b.owned).length > 0 && (
        <p className="mt-4 text-[12.5px] text-muted">
          Kept, no round: {Object.entries(b.owned).map(([k, name]) => `${PART_NAMES[k] ?? k} (${name})`).join(", ")}
        </p>
      )}
      {!!b.rejected && <p className="mt-4 text-[12.5px] text-amber">{b.rejected} rows from the feed failed the build shape and are not shown.</p>}
    </Card>
  );
}
