"use client";

import type { CSSProperties, ReactNode } from "react";
import { BRAND } from "@/components/floor/brand";
import type { FloorPhase, FloorScript, SellerView } from "@/components/floor/floorPhases";
import { SLOT_COLOR, usd } from "@/components/floor/FloorRingSvg";

/** The HUD around the stage: top-left lines and referee call, the top-right ASI:One PiP, the seller ledger and the deal card.
 * Pure presentational: everything comes from the script and the current phase. Under 640 px wide the HUD and PiP sit in flow
 * above and below the stage and the ledger is two by two (floor.md "Phone shell"). Sizes are design pixels at the 960 wide stage,
 * multiplied by --s (width / 960), so the smallest text is 11 design px and reads at 22 px on a 1920 frame. */

const COMPACT_BELOW = 640;
const SHIELD = "#22d3ee";
const REFEREE = "#c7d4ff";
const MUTED = "#8fa0b2";

const css = `
.fh { position: relative; width: 100%; background: #0b1b2b; color: #eef3f8; border-radius: calc(20px * var(--r)); overflow: hidden; box-shadow: inset 0 0.5px 0 #ffffff1f, 0 0 0 0.5px #eef3f81f, 0 4px 40px 8px #00000066, 0 34px 70px -34px #00000099; font-family: var(--font-geist), "Geist", ui-sans-serif, system-ui, sans-serif; }
.fh * { box-sizing: border-box; }
.fh-mono { font-family: var(--font-geist-mono), "Geist Mono", ui-monospace, Menlo, Consolas, monospace; }
.fh-in { animation: fh-in 450ms ease-out both; }
@keyframes fh-in { from { opacity: 0; transform: translateY(calc(6px * var(--s))); } to { opacity: 1; transform: none; } }
.fh-calm .fh-in { animation: none; }
@media (prefers-reduced-motion: reduce) { .fh-in { animation: none; } }
.fh-hud { display: grid; gap: calc(6px * var(--s)); pointer-events: none; }
.fh-over .fh-hud { position: absolute; left: calc(20px * var(--s)); top: calc(18px * var(--s)); right: calc(22% + 36px * var(--s)); z-index: 2; }
.fh-flow .fh-hud { padding: 12px 12px 4px; }
.fh-live { font-size: calc(12px * var(--s)); line-height: 1.35; letter-spacing: 0.04em; text-transform: uppercase; color: ${MUTED}; font-weight: 500; }
.fh-live b { color: ${REFEREE}; font-weight: 500; }
.fh-sim { display: inline-block; margin-left: 0.6em; padding: 0 0.5em; border: 1px dashed ${MUTED}; border-radius: 6px; font-size: 0.92em; color: #eef3f8; }
.fh-round { font-size: calc(15px * var(--s)); line-height: 1.35; font-weight: 500; letter-spacing: -0.01em; min-height: 1.35em; }
.fh-flow .fh-round { font-size: 13px; }
.fh-round em { font-style: normal; color: ${SHIELD}; }
.fh-call { min-height: calc(32px * var(--s)); }
.fh-flow .fh-call { min-height: 28px; }
.fh-call span { display: inline-flex; align-items: center; gap: calc(8px * var(--s)); min-height: calc(32px * var(--s)); padding: 0 calc(12px * var(--s)); border-radius: 999px; background: #1e4ed838; border: 1px solid ${REFEREE}; font-size: calc(12px * var(--s)); line-height: 1.3; font-weight: 500; }
.fh-call span b { color: ${REFEREE}; font-weight: 500; letter-spacing: 0.04em; }
.fh-pip { border-radius: calc(16px * var(--s)); background: #112437f0; box-shadow: inset 0 0.5px 0 #ffffff1f, 0 0 0 0.5px #eef3f81f, 0 4px 40px 8px #00000066; overflow: hidden; }
.fh-over .fh-pip { position: absolute; right: calc(20px * var(--s)); top: calc(18px * var(--s)); width: 22%; min-width: calc(150px * var(--s)); max-width: calc(220px * var(--s)); z-index: 2; }
.fh-flow .fh-pip { margin: 8px 12px 0; border-radius: 16px; }
.fh-pip-head { display: flex; align-items: center; gap: calc(8px * var(--s)); padding: calc(8px * var(--s)) calc(12px * var(--s)); border-bottom: 1px solid #eef3f81f; font-size: calc(11px * var(--s)); line-height: 1.3; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: ${MUTED}; }
.fh-dot { width: calc(6px * var(--s)); height: calc(6px * var(--s)); border-radius: 50%; background: ${SHIELD}; box-shadow: 0 0 0 calc(3px * var(--s)) #22d3ee40; flex: none; }
.fh-msgs { display: grid; gap: calc(6px * var(--s)); padding: calc(8px * var(--s)) calc(10px * var(--s)) calc(10px * var(--s)); }
.fh-msg { font-size: calc(12px * var(--s)); line-height: 1.25; padding: calc(5px * var(--s)) calc(8px * var(--s)); border-radius: calc(10px * var(--s)); background: #16304a; max-width: 96%; }
.fh-flow .fh-msg { font-size: 12px; }
.fh-msg.you { background: ${SHIELD}; color: #0b1b2b; justify-self: end; }
.fh-ledger { display: grid; grid-template-columns: repeat(4, 1fr); gap: calc(8px * var(--s)); }
.fh-over .fh-ledger { position: absolute; left: calc(20px * var(--s)); right: calc(20px * var(--s)); bottom: calc(16px * var(--s)); z-index: 2; }
.fh-flow .fh-ledger { grid-template-columns: repeat(2, 1fr); gap: 8px; padding: 8px 12px 12px; }
.fh-card { background: #112437e6; border: 1px solid #eef3f824; border-radius: calc(12px * var(--s)); padding: calc(8px * var(--s)) calc(10px * var(--s)); min-width: 0; transition: opacity 500ms, border-color 500ms; }
.fh-flow .fh-card { border-radius: 12px; padding: 8px 10px; }
.fh-card.out { opacity: 0.55; }
.fh-card.win { border-color: #0f9d76; }
.fh-name { display: flex; align-items: center; gap: calc(6px * var(--s)); font-size: calc(11px * var(--s)); line-height: 1.3; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: ${MUTED}; white-space: nowrap; overflow: hidden; }
.fh-name i { width: calc(8px * var(--s)); height: calc(8px * var(--s)); border-radius: 50%; flex: none; }
.fh-name span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.fh-name u { text-decoration: none; margin-left: auto; padding-left: 0.4em; opacity: 0.8; }
.fh-price { margin-top: calc(2px * var(--s)); font-size: calc(15px * var(--s)); line-height: 1.35; font-weight: 500; font-variant-numeric: tabular-nums; }
.fh-price.sealed { color: ${MUTED}; }
.fh-word { margin-top: calc(2px * var(--s)); font-size: calc(11px * var(--s)); line-height: 1.3; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: ${MUTED}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fh-word.bad { color: #e5484d; } .fh-word.warn { color: #fcd34d; } .fh-word.good { color: #0f9d76; } .fh-word.shield { color: ${SHIELD}; }
.fh-deal { position: absolute; z-index: 3; left: 38%; top: 52%; transform: translate(-50%, -50%); width: min(calc(420px * var(--s)), calc(100% - 40px * var(--s))); padding: calc(20px * var(--s)) calc(24px * var(--s)); border-radius: calc(20px * var(--s)); background: #112437f5; box-shadow: inset 0 0.5px 0 #ffffff1f, 0 0 0 0.5px #eef3f81f, 0 4px 40px 8px #00000066; text-align: center; }
.fh-flow .fh-deal { left: 50%; top: auto; bottom: 12px; transform: translate(-50%, 0); width: calc(100% - 24px); padding: 16px; border-radius: 16px; }
.fh-deal-in { animation: fh-deal 500ms ease-out both; }
@keyframes fh-deal { from { opacity: 0; margin-top: calc(8px * var(--s)); } to { opacity: 1; margin-top: 0; } }
.fh-calm .fh-deal-in { animation: none; }
.fh-deal .k { font-size: calc(12px * var(--s)); line-height: 1.3; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #0f9d76; }
.fh-deal .n { font-size: calc(40px * var(--s)); line-height: 1.1; font-weight: 500; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; margin-top: calc(6px * var(--s)); }
.fh-flow .fh-deal .n { font-size: 28px; }
.fh-deal .t { font-size: calc(15px * var(--s)); line-height: 1.35; margin-top: calc(4px * var(--s)); }
.fh-deal .l { font-size: calc(12px * var(--s)); line-height: 1.35; color: ${MUTED}; margin-top: calc(10px * var(--s)); }
.fh-deal .l b { color: #0f9d76; font-weight: 500; }
.fh-flow .fh-deal .l, .fh-flow .fh-deal .t { font-size: 13px; }
`;

function roundLine(script: FloorScript, phase: FloorPhase): ReactNode {
  const alive = Object.values(phase.sellers).filter((v) => v.state !== "eaten").length;
  const head = `Round ${phase.round} of ${phase.rounds}`;
  const part = <em>{phase.part}</em>;
  if (phase.kind === "crown" || phase.kind === "deal" || phase.kind === "paid") {
    const won = Object.values(phase.sellers).find((v) => v.state === "winner")?.price ?? null;
    const price = phase.deal?.price ?? won;
    return <>Deal · {part}{price !== null && <> · {usd(price)}</>}{phase.deal?.approvedByPhone && <> · approved by phone</>}</>;
  }
  const status = phase.kind === "check" ? "the checker verifies" : Object.values(phase.sellers).some((v) => v.price !== null) ? "revealed" : "sealed";
  return <>{head} · {part} · {alive} seller{alive === 1 ? "" : "s"} · {status}</>;
}

function wordClass(v: SellerView): string {
  if (v.state === "winner" || v.ledger.startsWith("Fit OK")) return "good";
  if (v.reason === "shield_block") return "shield";
  if (v.reason === "failed_fit") return "warn";
  if (v.reason === "highest_price" || v.reason === "advocate_veto" || v.reason === "refused") return "bad";
  return "";
}

function Top({ script, phase }: { script: FloorScript; phase: FloorPhase }) {
  return (
    <div className="fh-hud fh-mono">
      <div className="fh-live">
        Live from the {BRAND} floor · refereed by <b>CRS</b>
        {script.sim && <span className="fh-sim">SIM</span>}
      </div>
      <div className="fh-round" key={`${phase.kind}-${phase.round}`}><span className="fh-in" style={{ display: "inline-block", fontFamily: "var(--font-geist), Geist, ui-sans-serif, system-ui, sans-serif" }}>{roundLine(script, phase)}</span></div>
      <div className="fh-call">{phase.callText && <span className="fh-in" key={phase.callText}><b>Referee</b>{phase.callText}</span>}</div>
    </div>
  );
}

function Pip({ script, phase }: { script: FloorScript; phase: FloorPhase }) {
  const first = script.phases[0]?.pip[0];
  const shown = phase.pip.slice(-3);
  return (
    <div className="fh-pip" aria-label="ASI:One chat, mirrored">
      <div className="fh-pip-head fh-mono"><span className="fh-dot" />ASI:One · the buyer&apos;s agent</div>
      <div className="fh-msgs">
        {shown.map((m, i) => (
          <div key={`${m}-${i}`} className={`fh-msg fh-in${m === first ? " you" : ""}`}>{m}</div>
        ))}
      </div>
    </div>
  );
}

function Ledger({ script, phase }: { script: FloorScript; phase: FloorPhase }) {
  return (
    <div className="fh-ledger fh-mono">
      {script.sellers.map((s) => {
        const v = phase.sellers[s.id];
        if (!v) return null;
        const word = v.state === "sealed" && v.ledger === "Sealed" ? "bid in" : v.ledger;
        return (
          <div key={s.id} className={`fh-card${v.state === "eaten" ? " out" : ""}${v.state === "winner" ? " win" : ""}`}>
            <div className="fh-name"><i style={{ background: SLOT_COLOR[s.slot] }} /><span>{s.name}</span><u>{s.origin}</u></div>
            <div className={`fh-price${v.price === null ? " sealed" : ""}`}>{v.price === null ? "Sealed" : usd(v.price)}</div>
            <div className={`fh-word ${wordClass(v)}`} title={word}>{word}</div>
          </div>
        );
      })}
    </div>
  );
}

function Deal({ deal }: { deal: NonNullable<FloorPhase["deal"]> }) {
  const lines = deal.lines.filter((l) => l !== "Stripe test mode");
  return (
    <div className="fh-deal fh-mono" aria-live="polite">
      <div className="fh-deal-in">
        <div className="k">Deal</div>
        <div className="n" style={{ fontFamily: "var(--font-geist), Geist, ui-sans-serif, system-ui, sans-serif" }}>{usd(deal.price)}</div>
        <div className="t" style={{ fontFamily: "var(--font-geist), Geist, ui-sans-serif, system-ui, sans-serif" }}>{deal.part}</div>
        <div className="l">
          {lines.join(" · ")}
          {deal.approvedByPhone && !lines.some((l) => l.toLowerCase().includes("approved by phone")) && <>{lines.length > 0 ? " · " : ""}<b>approved by phone</b></>}
          {deal.stripeTest && <div>Stripe test mode</div>}
        </div>
      </div>
    </div>
  );
}

/** Wraps the renderer (children) with the HUD. `width` is the stage's CSS width; the stage keeps a 16:9 box. */
export function FloorHud({ script, phase, width, reducedMotion = false, children }: { script: FloorScript; phase: FloorPhase; width: number; reducedMotion?: boolean; children: ReactNode }) {
  const compact = width < COMPACT_BELOW;
  const s = compact ? 1 : Math.max(0.5, width / 960);
  const vars = { "--s": s, "--r": compact ? 0.8 : 1 } as CSSProperties;
  const stage = (
    <div style={{ position: "relative", width: "100%", height: (width * 9) / 16 }}>
      {children}
      {phase.deal && <Deal deal={phase.deal} />}
    </div>
  );
  return (
    <div className={`fh ${compact ? "fh-flow" : "fh-over"}${reducedMotion ? " fh-calm" : ""}`} style={vars}>
      <style>{css}</style>
      {compact ? (
        <>
          <Top script={script} phase={phase} />
          {stage}
          <Pip script={script} phase={phase} />
          <Ledger script={script} phase={phase} />
        </>
      ) : (
        <div style={{ position: "relative" }}>
          {stage}
          <Top script={script} phase={phase} />
          <Pip script={script} phase={phase} />
          <Ledger script={script} phase={phase} />
        </div>
      )}
    </div>
  );
}
