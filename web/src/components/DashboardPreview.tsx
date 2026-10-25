"use client";
// web/src/components/DashboardPreview.tsx
// The buyer dashboard in miniature, on the landing (#448, round 3): one goal, the sealed round, the approval code and the receipt,
// so a visitor sees what the product is before they sign up. Every value is the recorded sample run (lib/sample.ts), labelled SIM.
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { approval, goal, rankedBids, receipt } from "@/lib/sample";
import { latestRound } from "@/lib/screens";
import { SHIELD } from "@/lib/brand";
import { OriginChip, StatusPill, money } from "./ui";

const sealed = rankedBids.length;
const vetoed = rankedBids.filter((b) => b.recommendation === "veto").length;

export function DashboardPreview() {
  const [rounds] = useTable(tables.round);
  const live = latestRound(rounds);
  const liveSealed = live ? Number(live.sealedCount) : null;
  return (
    <div className="fm-glass overflow-hidden rounded-[22px] p-0" role="img" aria-label="The buyer dashboard: a goal, a sealed round, an approval code and a receipt, from a recorded sample run">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <span className="flex items-center gap-2 text-[13px] font-medium text-ink-2">
          <span className="flex gap-1.5" aria-hidden><i className="h-2.5 w-2.5 rounded-full bg-coral-mark/70" /><i className="h-2.5 w-2.5 rounded-full bg-amber/60" /><i className="h-2.5 w-2.5 rounded-full bg-mint-mark/70" /></span>
          Your dashboard
        </span>
        <OriginChip origin="SIM" label={live ? "SIM sample run, round from this market" : "SIM sample run"} />
      </div>
      <div className="grid gap-3 p-4 md:grid-cols-4 md:p-5">
        <Mini label="Goal" pill={<StatusPill tone="live" pulse>Hunting</StatusPill>}>
          <p className="text-[15px] font-medium leading-5 text-balance"><q>{goal.text}</q></p>
          <p className="mt-2 font-mono text-[12px] text-muted">cap {money(goal.cap)}</p>
        </Mini>
        <Mini label="Round" pill={live ? <StatusPill tone={live.state === "closed" ? "good" : "live"} pulse={live.state !== "closed"}>{live.state === "closed" ? "Closed" : "Open"}</StatusPill> : <StatusPill tone="sealed">Sealed</StatusPill>}>
          <p className="text-[32px] font-medium leading-9 tracking-[-0.02em] tabular-nums">{liveSealed ?? sealed}</p>
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] leading-[18px] text-ink-2">{live ? <>bids sealed <OriginChip origin={live.origin} /></> : <>bids sealed · {vetoed} vetoed · {SHIELD} 1 blocked</>}</p>
        </Mini>
        <Mini label="Approve" pill={<StatusPill tone="live" pulse>Calling</StatusPill>}>
          <p className="font-mono text-[22px] font-medium leading-7 tracking-[0.04em]">{approval.wordPair}</p>
          <p className="mt-1 text-[13px] leading-[18px] text-ink-2">{money(approval.amount)} is above your {money(approval.allowance)} allowance</p>
        </Mini>
        <Mini label="Receipt" pill={<StatusPill tone="good">Paid</StatusPill>}>
          <p className="text-[26px] font-medium leading-8 tracking-[-0.02em] tabular-nums">{money(receipt.amount)}</p>
          <p className="mt-1 text-[13px] leading-[18px] text-ink-2">signed mandate · test mode</p>
        </Mini>
      </div>
    </div>
  );
}

function Mini({ label, pill, children }: { label: string; pill: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="fm-tile rounded-2xl p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium uppercase tracking-[0.04em] text-muted">{label}</span>
        {pill}
      </div>
      {children}
    </div>
  );
}
