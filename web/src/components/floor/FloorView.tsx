"use client";
// /floor, the ring view (v2, docs/design-system/floor.md): the stage canvas plus plain HTML for the HUD, the referee call, the ASI:One
// picture-in-picture, the ledger and the deal card. Rows come from the same market tables as the arena view; with no rows it plays the
// built-in reference scenario, labelled SIM. Under 640 px the HUD sits above the stage and the PiP below it, in flow.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { useAgents } from "@/components/useAgents";
import { ASI_ONE_URL, latestActivity, realRows } from "@/lib/agentFeed";
import type { ArenaRows } from "@/lib/arenaScene";
import { formatMoney } from "@/lib/money";
import { FLOOR as C } from "./floorTokens";
import { hudText, planFromRows, type FloorPhase, type FloorPlan, type SellerView } from "./floorPhases";
import { FloorRing, type FloorTheme } from "./FloorRing";
import { BRAND } from "./brand";

const LOOP_GAP_MS = 2500;
const sans = { fontFamily: C.fontSans } as const;
const mono = { fontFamily: C.fontMono, letterSpacing: "0.04em" } as const;

export function RingFloor() {
  const [rounds] = useTable(tables.round);
  const [needs] = useTable(tables.sellerNeeds);
  const [results] = useTable(tables.roundResult);
  const [events] = useTable(tables.floorEvent);
  const rows = useMemo<ArenaRows>(() => ({ rounds, needs, results, events }), [rounds, needs, results, events]);
  const plan = useMemo(() => planFromRows(rows), [rows]);
  // A new plan (new round, new result) restarts the show from its first phase.
  const sig = `${plan.origin}|${plan.part}|${plan.phases.length}|${plan.winnerKey}|${plan.phases[0]?.sellers.map((s) => s.name).join(",")}|${plan.phases.at(-1)?.sellers.map((s) => s.price).join(",")}`;
  return <Player key={sig} plan={plan} />;
}

function Player({ plan }: { plan: FloorPlan }) {
  const reduced = !!useReducedMotion();
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  // Fish by default; ghosts stay behind the switch (or ?theme=ghosts). Read once on mount: the page only mounts in the browser.
  const [theme, setTheme] = useState<FloorTheme>(() => (new URLSearchParams(window.location.search).get("theme") === "ghosts" ? "ghosts" : "fish"));
  const elapsed = useRef(0);
  const phases = plan.phases;
  const last = phases.length - 1;
  const ph = phases[Math.min(index, last)]!;
  const atEnd = index >= last && !ph.hold;

  const go = useCallback((i: number) => { elapsed.current = 0; setIndex(Math.min(Math.max(i, 0), last)); }, [last]);

  // The clock: moves to the next phase when its time is up. Reduced motion steps by timer and draws no movement.
  // It depends on the phase's numbers, not the plan object, which is rebuilt whenever a table row re-delivers.
  const phMs = ph.ms;
  const phHold = ph.hold;
  const sample = plan.sample;
  useEffect(() => {
    if (paused || phHold) return;
    if (atEnd) {
      if (!sample) return; // a real round rests on its deal card
      const t = setTimeout(() => go(0), LOOP_GAP_MS + phMs);
      return () => clearTimeout(t);
    }
    if (reduced) {
      const t = setTimeout(() => go(index + 1), phMs);
      return () => clearTimeout(t);
    }
    let raf = 0;
    const start = performance.now() - elapsed.current;
    const tick = (now: number) => {
      elapsed.current = now - start;
      if (elapsed.current >= phMs) return go(index + 1);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [index, paused, reduced, phMs, phHold, atEnd, sample, go]);

  const live = useAgents();
  const agentLine = useMemo(() => {
    if (plan.sample || !live.rows) return null;
    const row = latestActivity(realRows(live.rows));
    return row?.last_message ? `${row.name}: ${row.last_message}` : null;
  }, [plan.sample, live.rows]);

  const chat = useMemo(() => {
    const lines = phases.slice(0, index + 1).map((p) => p.pip).filter((x): x is string => !!x);
    return lines.filter((l, i) => l !== lines[i - 1]).slice(-2);
  }, [phases, index]);

  const label = `Ring view, step ${index + 1} of ${phases.length}. ${hudText(ph.hud)}`;

  return (
    <div className="grid gap-3">
      <div className="relative overflow-hidden rounded-2xl sm:rounded-[20px]" style={{ background: C.stage, boxShadow: C.shadowGlass, color: C.line }}>
        {/* HUD: on phones above the stage, on wider screens over it and clear of the PiP by its width plus 36 px */}
        <div data-testid="floor-hud" className="pointer-events-none relative z-10 grid content-start gap-1.5 px-3 pb-1 pt-3 sm:absolute sm:left-5 sm:right-[calc(22%+36px)] sm:top-[18px] sm:p-0" style={sans}>
          <p className="text-[12px] uppercase leading-4" style={{ ...mono, color: C.muted }}>
            Live from the {BRAND} floor · refereed by <b className="font-medium" style={{ color: C.referee }}>CRS</b>
            <Origin plan={plan} />
          </p>
          <p className="text-[13px] font-medium leading-5 tracking-[-0.01em] sm:text-[15px]" data-testid="floor-round">
            <HudLine ph={ph} />
          </p>
          {ph.call && (
            <div role="status" className="inline-flex w-fit max-w-full flex-wrap items-center gap-x-2 rounded-2xl border px-3 py-1 text-[11px] leading-[18px] sm:min-h-8 sm:rounded-full sm:text-[12px]" style={{ ...mono, background: C.refereeSoft, borderColor: C.referee }}>
              <b className="font-medium uppercase" style={{ color: C.referee }}>Referee</b>
              <span className="min-w-0">{ph.call}</span>
            </div>
          )}
        </div>
        <FloorRing phases={phases} index={index} elapsed={elapsed} reduced={reduced} label={label} theme={theme} />
        <ChatPip lines={agentLine ? [...chat.slice(-1), agentLine] : chat} sample={plan.sample} />
        {ph.end && <DealCard card={ph.end} />}
        <Ledger sellers={ph.sellers} winner={plan.winnerKey} ph={ph} />
      </div>
      <Controls index={index} total={phases.length} paused={paused} atEnd={atEnd} hold={ph.hold} reduced={reduced} onPrev={() => go(index - 1)} onNext={() => go(index + 1)} onToggle={() => setPaused((p) => !p)} onReplay={() => { setPaused(false); go(0); }} theme={theme} onTheme={() => setTheme((t) => (t === "fish" ? "ghosts" : "fish"))} />
    </div>
  );
}

function HudLine({ ph }: { ph: FloorPhase }) {
  const h = ph.hud;
  const text = hudText(h);
  const at = h.part ? text.indexOf(h.part) : -1;
  if (at < 0) return <>{text}</>;
  return <>{text.slice(0, at)}<em className="not-italic" style={{ color: C.live }}>{h.part}</em>{text.slice(at + h.part.length)}</>;
}

function Origin({ plan }: { plan: FloorPlan }) {
  return (
    <span className="ml-2 inline-block rounded-full px-2 py-0.5 align-middle text-[10px] font-medium" style={{ ...mono, background: plan.sample ? "#92400e4d" : "#0f9d7633", color: plan.sample ? C.amberText : C.mintText }}>
      {plan.sample ? "SIM" : plan.origin}
    </span>
  );
}

/** FaceTime-style tile: the ASI:One chat as the buyer's agent talks the round through. Top right over the stage, in flow below it on phones. */
function ChatPip({ lines, sample }: { lines: string[]; sample: boolean }) {
  return (
    <aside
      data-testid="floor-pip"
      aria-label="ASI:One chat"
      className="relative z-10 mx-3 mt-2 overflow-hidden rounded-2xl sm:absolute sm:right-5 sm:top-[18px] sm:m-0 sm:w-[22%] sm:min-w-[150px] sm:max-w-[220px]"
      style={{ background: C.pipBg, boxShadow: C.shadowGlass, ...sans }}
    >
      <div className="flex items-center gap-2 border-b px-3 py-2 text-[11px] uppercase leading-[14px]" style={{ ...mono, borderColor: C.pipLine, color: C.muted }}>
        <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: C.live, boxShadow: `0 0 0 3px ${C.shieldSoft}` }} />
        <span className="min-w-0 truncate">ASI:One · the buyer</span>
        {sample && <span className="ml-auto" style={{ color: C.amberText }}>SIM</span>}
      </div>
      <ul className="grid gap-1.5 px-2.5 pb-1 pt-2" style={{ minHeight: 64 }}>
        {lines.length === 0 && <li className="text-[11px]" style={{ color: C.muted }}>Waiting for the buyer.</li>}
        {lines.map((l, i) => {
          const newest = i === lines.length - 1;
          return (
            <li key={i} className="max-w-[96%] rounded-[10px] px-2 py-[5px] text-[11px] leading-[14px] sm:text-[12px] sm:leading-[15px]" style={{ background: newest ? C.live : C.pipBubble, color: newest ? C.tagInk : C.line, justifySelf: newest ? "end" : "start" }}>
              {l}
            </li>
          );
        })}
      </ul>
      <a href={ASI_ONE_URL} target="_blank" rel="noreferrer" className="block px-3 pb-2 text-[11px] underline" style={{ color: C.pulse }}>Open ASI:One</a>
    </aside>
  );
}

function DealCard({ card }: { card: NonNullable<FloorPhase["end"]> }) {
  const deal = card.title === "DEAL";
  return (
    <div data-testid="floor-deal" aria-live="polite" className="pointer-events-none relative z-10 mx-3 mt-2 rounded-[20px] px-5 py-4 text-center sm:absolute sm:left-[38%] sm:top-[52%] sm:m-0 sm:w-[min(420px,calc(100%-40px))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:px-6 sm:py-5" style={{ background: C.dealBg, boxShadow: C.shadowGlass, ...sans }}>
      <p className="text-[12px] uppercase leading-4" style={{ ...mono, color: deal ? C.mintText : C.amberText }}>{deal ? "Deal" : "No deal"}</p>
      <p className="mt-1.5 text-[28px] font-medium leading-8 tracking-[-0.02em] tabular-nums sm:text-[40px] sm:leading-[44px]">{card.price ?? "No part"}</p>
      <p className="mt-1 text-[15px] leading-5">{card.part || "The part"}</p>
      <p className="mt-2.5 text-[12px] leading-4" style={{ ...mono, color: C.muted }}>{card.line}</p>
    </div>
  );
}

function Ledger({ sellers, winner, ph }: { sellers: SellerView[]; winner: string | null; ph: FloorPhase }) {
  const n = Math.min(Math.max(sellers.length, 1), 5);
  return (
    <ul data-testid="floor-ledger" aria-label="Sellers" className="relative z-10 grid grid-cols-2 gap-2 px-3 pb-3 pt-2 sm:absolute sm:inset-x-5 sm:bottom-4 sm:p-0 sm:[grid-template-columns:var(--cols)]" style={{ "--cols": `repeat(${n}, minmax(0, 1fr))` } as React.CSSProperties}>
      {sellers.map((s) => {
        const out = s.status === "eaten" || s.status === "blocked";
        const won = s.key === winner && (s.status === "winner" || ph.kind === "end");
        const word = s.statusLine ?? (s.status === "eaten" ? s.tag : s.status === "sealed" ? "Sealed" : "In the round");
        const color = out ? C.coralText : won || s.tone === "good" ? C.mintText : s.tone === "warn" ? C.amberText : C.muted;
        const dot = s.tint === "slate" ? C.slate : s.tint === "coral" ? C.coral : s.tint === "amber" ? C.amber : s.tint === "sky" ? C.sky : C.mint;
        return (
          <li key={s.key} className="min-w-0 rounded-xl border px-2.5 py-2" style={{ background: C.ledgerBg, borderColor: won ? C.mint : C.ledgerLine, opacity: out ? 0.55 : 1 }}>
            <div className="flex items-center gap-1.5 truncate text-[11px] uppercase leading-[14px]" style={{ ...mono, color: C.muted }}>
              <i aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full" style={{ background: dot }} />
              <span className="min-w-0 truncate">{s.name}</span>
              {s.origin !== "LIVE" && <span className="ml-auto shrink-0 rounded-full px-1.5 text-[9px]" style={{ background: s.origin === "MIRROR" ? C.refereeSoft : "#92400e4d", color: s.origin === "MIRROR" ? C.referee : C.amberText }}>{s.origin}</span>}
            </div>
            <p className="mt-0.5 text-[15px] leading-5 tabular-nums" style={{ fontFamily: C.fontMono, color: s.price === null ? C.muted : C.line }}>{s.price === null ? "Sealed" : formatMoney(s.price)}</p>
            <p className="mt-0.5 truncate text-[10px] uppercase leading-[14px]" style={{ ...mono, color }}>{word}</p>
          </li>
        );
      })}
    </ul>
  );
}

function Controls(p: { index: number; total: number; paused: boolean; atEnd: boolean; hold: boolean; reduced: boolean; onPrev: () => void; onNext: () => void; onToggle: () => void; onReplay: () => void; theme: FloorTheme; onTheme: () => void }) {
  const btn = "inline-flex min-h-11 min-w-11 items-center justify-center rounded-full border border-[#e3e8ef] bg-white px-4 text-[13px] font-medium text-[#2a3440] shadow-[0_1px_2px_rgba(11,27,43,.06)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1e4ed8] disabled:opacity-40";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className={btn} onClick={p.onPrev} disabled={p.index === 0}>Prev</button>
      <button type="button" className={btn} aria-pressed={p.paused} onClick={p.onToggle} disabled={p.hold}>{p.paused ? "Play" : "Pause"}</button>
      <button type="button" className={btn} onClick={p.onNext} disabled={p.atEnd || p.hold}>Next</button>
      <button type="button" className={btn} onClick={p.onReplay} disabled={p.hold}>Replay</button>
      <button type="button" className={btn} aria-pressed={p.theme === "ghosts"} onClick={p.onTheme}>{p.theme === "fish" ? "Ghosts" : "Fish"}</button>
      <span className="ml-1 text-[12px] uppercase text-[#5b6b7c]" style={mono} aria-live="off">
        {p.hold ? "Waiting for the round to close" : `Step ${p.index + 1} of ${p.total}`}
        {p.reduced ? " · reduced motion" : ""}
      </span>
    </div>
  );
}
