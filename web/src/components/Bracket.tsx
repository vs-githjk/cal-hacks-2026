"use client";
// web/src/components/Bracket.tsx
// Bidding Royale: the closed round as a knockout bracket for the buyer, Vidyut. Every stage, heat and reason comes
// from lib/bracket.ts, which reads only round_result rows; nothing here ranks or decides. Stages reveal one by one
// (each step is one referee decision), and under reduced motion the final bracket shows at once.
import { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { latestRound } from "@/lib/screens";
import { buildBracket, roundWinner, type Bracket as BracketData, type Entrant, type Heat, type Knock, type Stage } from "@/lib/bracket";
import { Card, Label, OriginChip, SourceLink, Verdict, money } from "./ui";

const STEP_MS = 900; // per stage; a 16 entrant field (7 stages) stays under 7 s

const STAGE_NOTE: Record<Stage["kind"], string> = {
  gate: "Referee refusals",
  advocate: "Advocate vetoes",
  knockout: "Ranked 1v1 by the referee",
  champion: "The round winner",
};

const CODE_LABEL: Record<Knock["reasonCode"], string> = {
  shield_block: "Shield block",
  below_floor: "Below floor",
  over_cap: "Over cap",
  off_need: "Off need",
  sold_out: "Sold out",
  refused: "Refused",
  advocate_veto: "Veto",
  claim_false: "Claim false",
  outranked: "Outranked",
};

/** Reads its own tables so it never draws from a half-loaded round (results arrive after the round row). */
export function Bracket() {
  const [rounds, roundsReady] = useTable(tables.round);
  const [results, resultsReady] = useTable(tables.roundResult);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const ready = roundsReady && resultsReady && eventsReady;
  const round = latestRound(rounds);
  const built = useMemo((): { b: BracketData } | { error: string } | null => {
    if (!ready || !round || round.state !== "closed") return null;
    try {
      const b = buildBracket(results, round.id);
      if (b.champion !== roundWinner(results, round.id, events)) return { error: "the bracket champion is not the round winner" };
      return { b };
    } catch (e) {
      return { error: e instanceof Error ? e.message : String(e) };
    }
  }, [ready, round, results, events]);

  return (
    <div className="mt-3.5">
      <Card>
        <Label>Bidding Royale · Vidyut&apos;s round{round ? ` · ${round.id}` : ""}</Label>
        {!ready ? (
          <p className="text-muted">Connecting...</p>
        ) : !round ? (
          <p className="text-muted">No round yet. The bracket draws from the referee&apos;s decisions when a round closes.</p>
        ) : !built ? (
          <p className="text-muted">Bids are sealed. The bracket draws when the referee closes the round.</p>
        ) : "error" in built ? (
          <p className="text-coral">Bracket not shown: {built.error}.</p>
        ) : (
          <BracketView key={`${built.b.roundId}:${results.length}`} b={built.b} />
        )}
      </Card>
    </div>
  );
}

function BracketView({ b }: { b: BracketData }) {
  const reduce = useReducedMotion();
  const total = b.stages.length;
  const [step, setStep] = useState(1);
  const [paused, setPaused] = useState(false);
  const shown = reduce ? total : step; // reduced motion: the final bracket at once
  const done = shown >= total;
  const playing = !paused && !done;

  useEffect(() => {
    if (!playing || reduce) return;
    const t = setTimeout(() => setStep((n) => n + 1), STEP_MS);
    return () => clearTimeout(t);
  }, [playing, step, reduce]);

  return (
    <div>
      {!reduce && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-[13px]">
          <button
            type="button"
            className="rounded-md border border-line-2 px-2.5 py-1 font-semibold"
            onClick={() => (done ? (setStep(1), setPaused(false)) : setPaused((p) => !p))}
          >
            {done ? "Replay" : playing ? "Pause" : "Play"}
          </button>
          <span className="text-muted">Stage {Math.min(shown, total)} of {total}</span>
        </div>
      )}
      <ol className="grid gap-3.5 lg:auto-cols-[minmax(0,1fr)] lg:grid-flow-col">
        {b.stages.map((s, i) =>
          i < shown ? (
            <motion.li
              key={s.name}
              initial={reduce ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 260, damping: 26 }}
              className="min-w-0"
            >
              <StageColumn stage={s} b={b} />
            </motion.li>
          ) : (
            <li key={s.name} className="min-w-0 rounded-[10px] border border-dashed border-line p-3 text-[13px] text-muted" aria-hidden>
              {s.name}
            </li>
          ),
        )}
      </ol>
      <p className="mt-3 text-[12px] text-muted">
        Drawn only from this round&apos;s round_result rows. Prices are landed, before sales tax; adjusted is the score the referee ranked on.
      </p>
    </div>
  );
}

function StageColumn({ stage, b }: { stage: Stage; b: BracketData }) {
  return (
    <section className="grid min-w-0 content-start gap-2">
      <header>
        <h3 className="text-[14px] font-semibold">{stage.name}</h3>
        <p className="text-[12px] text-muted">{STAGE_NOTE[stage.kind]}</p>
      </header>
      {stage.kind === "champion" ? (
        stage.heats[0] ? <Champion e={b.entrants[stage.heats[0].entrants[0]!]!} /> : <p className="text-[13px] text-muted">No bid was eligible.</p>
      ) : stage.kind === "knockout" ? (
        stage.heats.map((h, i) => <HeatCard key={i} heat={h} b={b} />)
      ) : (
        <Screening heat={stage.heats[0]!} b={b} />
      )}
    </section>
  );
}

/** Gate or Heat 1: who the referee or advocate knocked out, and how many went through. */
function Screening({ heat, b }: { heat: Heat; b: BracketData }) {
  const out = new Set(heat.knocked.map((k) => k.id));
  const through = heat.entrants.filter((id) => !out.has(id)).length;
  return (
    <div className="grid gap-2">
      {heat.knocked.length === 0 && <p className="text-[13px] text-muted">Nobody knocked out here.</p>}
      {heat.knocked.map((k) => (
        <div key={k.id} className="rounded-[10px] bg-soft px-3 py-2 opacity-80">
          <EntrantLine e={b.entrants[k.id]!} out />
          <KnockoutReason k={k} />
        </div>
      ))}
      <p className="text-[12px] font-medium text-muted">{through} through of {heat.entrants.length}</p>
    </div>
  );
}

function HeatCard({ heat, b }: { heat: Heat; b: BracketData }) {
  return (
    <div className="rounded-[10px] border border-line px-3 py-2">
      {heat.entrants.map((id) => {
        const k = heat.knocked.find((x) => x.id === id);
        return (
          <div key={id} className={k ? "opacity-60" : ""}>
            <EntrantLine e={b.entrants[id]!} out={!!k} />
            {k && <KnockoutReason k={k} />}
          </div>
        );
      })}
      {heat.bye && <p className="mt-1 text-[12px] text-muted">Bye: no opponent at this seed</p>}
    </div>
  );
}

function EntrantLine({ e, out }: { e: Entrant; out?: boolean }) {
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 py-0.5">
      <span className={`min-w-0 break-words text-[13px] ${out ? "text-muted" : "font-semibold"}`}>
        {e.rank && <span className="mr-1 font-mono text-[11px] text-muted">#{e.rank}</span>}
        <span className={out ? "line-through decoration-1" : ""}>{e.name}</span>{" "}
        <OriginChip origin={e.origin} />
      </span>
      <span className="font-mono text-[12px] tabular-nums">{money(e.adjusted ?? e.landed)}</span>
    </div>
  );
}

function KnockoutReason({ k }: { k: Knock }) {
  return (
    <div className="mt-1 grid gap-0.5 text-[12px]">
      <span className="flex flex-wrap items-center gap-1.5">
        <Verdict kind={k.reasonCode === "outranked" ? "out" : "veto"}>{CODE_LABEL[k.reasonCode]}</Verdict>
        <span className="break-all font-mono text-[11px] text-muted">{k.ruleId ?? k.reasonCode}</span>
      </span>
      <span className="break-words text-muted">{k.reasonText}</span>
      {k.sourceUrl && <SourceLink href={k.sourceUrl} />}
    </div>
  );
}

function Champion({ e }: { e: Entrant }) {
  return (
    <div className="rounded-[10px] border-l-4 border-l-mint bg-mint-soft px-3 py-2.5">
      <p className="min-w-0 break-words text-[15px] font-semibold">
        {e.name} <OriginChip origin={e.origin} />
      </p>
      <dl className="mt-1.5 grid gap-0.5 text-[13px]">
        <div className="flex justify-between gap-2"><dt className="text-muted">Landed, before sales tax</dt><dd className="font-mono tabular-nums">{money(e.landed)}</dd></div>
        <div className="flex justify-between gap-2"><dt className="text-muted">Adjusted</dt><dd className="font-mono tabular-nums">{money(e.adjusted ?? e.landed)}</dd></div>
      </dl>
      {e.adjustmentReason && <p className="mt-1 text-[12px] text-muted">{e.adjustmentReason}</p>}
      {e.sourceUrl && <div className="mt-1"><SourceLink href={e.sourceUrl} /></div>}
      <p className="mt-1 font-mono text-[11px] text-muted">{e.rowRef} · rank 1</p>
    </div>
  );
}
