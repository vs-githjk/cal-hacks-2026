"use client";
// #343 Build Board: an exploded PC, one slot per part. Visuals only: reads lib/buildBoard.ts and decides
// nothing about fit or price. A 2D grid is both the primary view and the small-screen fallback.
import { useState } from "react";
import {
  PART_LABELS, PARTS, checksFor, otherPart,
  type BuildCheck, type BuildPart, type BuildView, type Part,
} from "@/lib/buildBoard";
import { Card, Label, OriginChip, Pill, Stat, Tag, Verdict, money } from "./ui";

const STATUS_STRIPE: Record<BuildPart["status"], "coral" | "ink" | "amber" | "mint" | undefined> = {
  owned: undefined, planned: undefined, bidding: "ink", locked: "mint", replanned: "amber", failed: "coral",
};
const STATUS_TEXT: Record<BuildPart["status"], string> = {
  owned: "Already in the rig", planned: "Planned", bidding: "Round open", locked: "Locked in",
  replanned: "Swapped", failed: "No eligible bid",
};

function PartSlot({ p, lit }: { p: BuildPart; lit: boolean }) {
  return (
    <Card stripe={STATUS_STRIPE[p.status]} tactile className={lit ? "outline outline-2 outline-offset-2 outline-accent" : ""}>
      <div className="flex items-center justify-between gap-2">
        <Label>{PART_LABELS[p.part]}</Label>
        {p.champion && <OriginChip origin={p.champion.origin} />}
      </div>
      <p className="truncate text-[15px] font-semibold">{p.label}</p>
      <p className="mt-0.5 text-[12px] text-muted">{STATUS_TEXT[p.status]}</p>
      {p.champion ? (
        <div className="mt-2 flex items-baseline justify-between gap-2">
          <span className="truncate text-[13px] text-muted">{p.champion.persona}</span>
          <span className="text-[18px] font-semibold tabular-nums">{money(p.champion.landed)}</span>
        </div>
      ) : p.budget > 0 ? (
        <p className="mt-2 text-[13px] text-muted">Budget {money(p.budget)}</p>
      ) : null}
      {p.reason && <p className="mt-1.5 text-[12px] text-amber">{p.reason}</p>}
    </Card>
  );
}

function CheckRow({ c, lit, onHover }: { c: BuildCheck; lit: boolean; onHover: (on: boolean) => void }) {
  const kind = c.state === "ok" ? "buy" : c.state === "clash" ? "veto" : "out";
  return (
    <li
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      className={`flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 ${lit ? "bg-soft" : ""}`}
    >
      <span className="min-w-0 truncate text-[13px]">
        {PART_LABELS[c.a]} &harr; {PART_LABELS[c.b]} <span className="text-muted">({c.detail})</span>
      </span>
      <Verdict kind={kind}>{c.state}</Verdict>
    </li>
  );
}

const APPROVAL_TONE: Record<BuildView["approval"]["state"], "done" | "hold" | "hunting"> = {
  waiting: "hunting", calling: "hold", approved: "done", denied: "hold", paid: "done",
};

export function BuildBoardScreen({ state, build }: { state: "loading" | "offline" | "ready"; build: BuildView | null }) {
  const [hover, setHover] = useState<Part | null>(null);
  if (state === "loading") return <p className="text-muted">Loading the build...</p>;
  if (state === "offline" || !build) {
    return (
      <Card>
        <p className="text-[22px] font-medium">The build board is not available.</p>
        <p className="mt-1 text-muted">Nothing is shown because nothing could be read.</p>
      </Card>
    );
  }
  const parts = PARTS.map((p) => build.parts.find((x) => x.part === p)).filter((p): p is BuildPart => !!p);
  const litParts = hover ? new Set([hover, ...checksFor(hover, build.checks).map((c) => otherPart(c, hover))]) : null;
  const pct = build.budget > 0 ? Math.min(100, Math.round((build.spent / build.budget) * 100)) : 0;

  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="text-[18px] font-bold tracking-[-0.01em]">
          Build Board <span className="font-medium text-muted">one exploded PC, one slot per part</span>
        </div>
        <OriginChip origin={build.origin} />
      </div>

      <Card>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <Label>Budget</Label>
          <span className="text-[13px] text-muted">{money(build.spent)} of {money(build.budget)}</span>
        </div>
        <div className="mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-soft">
          <div className={`h-full rounded-full ${pct > 100 ? "bg-coral" : "bg-mint"}`} style={{ width: `${Math.min(pct, 100)}%` }} />
        </div>
      </Card>

      <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1fr)_minmax(0,320px)]">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-label={`${parts.length} parts in this build`}>
          {parts.map((p) => (
            <PartSlot key={p.part} p={p} lit={litParts?.has(p.part) ?? false} />
          ))}
        </div>

        <div className="grid content-start gap-3.5">
          <Card>
            <Label>Compatibility</Label>
            {build.checks.length ? (
              <ul className="grid gap-0.5">
                {build.checks.map((c, i) => (
                  <CheckRow key={i} c={c} lit={hover === c.a || hover === c.b} onHover={(on) => setHover(on ? c.a : null)} />
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-muted">No checks yet.</p>
            )}
          </Card>

          <Card>
            <div className="flex items-center justify-between gap-2">
              <Label>Approval</Label>
              <Pill tone={APPROVAL_TONE[build.approval.state]}>{build.approval.state}</Pill>
            </div>
            <Stat label="Whole build" value={money(build.approval.total)} sub={`${build.approval.sellers} sellers`} />
            {build.approval.mandates.length > 0 && (
              <ul className="mt-2 grid gap-1">
                {build.approval.mandates.map((m) => (
                  <li key={m.mandateHash} className="flex items-center justify-between text-[13px]">
                    <span className="truncate text-muted">{m.sellerId}</span>
                    <span className="tabular-nums">{money(m.amount)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <Card>
        <Label>Build log</Label>
        <ol className="grid gap-1.5">
          {build.events.map((e, i) => (
            <li key={i} className="flex items-start gap-2 text-[13px]">
              <Tag>{e.kind}</Tag>
              <span className="min-w-0 break-words text-ink">{e.text}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
