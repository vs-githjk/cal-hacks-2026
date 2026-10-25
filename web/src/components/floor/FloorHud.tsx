"use client";

import type { CSSProperties, ReactNode } from "react";
import type { FloorPhase, FloorScript, SellerView } from "@/components/floor/floorPhases";
import { AVATAR_GRIDS, avatarColors, avatarFor, runs } from "@/components/floor/pixelArt";

/** The HUD around the stage: the seller ledger and the deal card.
 * Pure presentational: everything comes from the script and the current phase. The ledger is always in flow BELOW the stage.
 * Under 640 px wide the HUD sits above the stage and the deal card below it, and the ledger is two by two (floor.md "Phone shell").
 * Sizes are design pixels at the 960 wide stage, multiplied by --s (width / 960), so the smallest text is 11 design px and reads at 22 px on a 1920 frame. */

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = (n: number) => USD.format(n);

/** Ledger dot colours by seller slot. */
const SLOT_COLOR: Record<number, string> = { 1: "#e5484d", 2: "#f38ba8", 3: "#22d3ee", 4: "#f59e0b" };

const COMPACT_BELOW = 640;
const TWO_COLS_AT = 1024;
const SHIELD = "#22d3ee";
const MUTED = "#8fa0b2";
const MINT = "#34d399";
const SANS: CSSProperties = { fontFamily: "var(--font-geist), Geist, ui-sans-serif, system-ui, sans-serif" };

const css = `
.fh { position: relative; width: 100%; background: #0b1b2b; color: #eef3f8; border-radius: calc(20px * var(--r)); overflow: hidden; box-shadow: 0 0 0 0.5px #eef3f81f; font-family: var(--font-geist), "Geist", ui-sans-serif, system-ui, sans-serif; }
.fh * { box-sizing: border-box; min-width: 0; }
.fh { max-width: 100%; }
.fh-mono { font-family: var(--font-geist-mono), "Geist Mono", ui-monospace, Menlo, Consolas, monospace; }
.fh-in { animation: fh-in 450ms ease-out both; }
@keyframes fh-in { from { opacity: 0; transform: translateY(calc(6px * var(--s))); } to { opacity: 1; transform: none; } }
.fh-calm .fh-in { animation: none; }
@media (prefers-reduced-motion: reduce) { .fh-in { animation: none; } }
.fh-stage { position: relative; margin: 0 auto; overflow: hidden; }
.fh-bare { border-radius: 0; box-shadow: none; }
.fh-bare .fh-stage { height: auto !important; }
.fh-simchip { position: absolute; z-index: 3; left: calc(20px * var(--s)); top: calc(16px * var(--s)); padding: 0 0.55em; border: 1px solid #eef3f866; border-radius: 4px; background: #0b1b2b99; color: #eef3f8; font-size: calc(10px * var(--s)); line-height: 1.7; letter-spacing: 0.08em; pointer-events: none; }
.fh-ledger { display: grid; grid-template-columns: minmax(0, 1fr); gap: calc(6px * var(--u)); padding: calc(10px * var(--u)) calc(20px * var(--s)) calc(14px * var(--u)); }
.fh-two .fh-ledger { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.fh-flow .fh-ledger { padding: 8px 12px 12px; gap: 6px; }
.fh-frame .fh-ledger { height: calc(90px * var(--s)); padding-top: calc(8px * var(--s)); padding-bottom: 0; overflow: hidden; gap: calc(4px * var(--s)); }
.fh-row { position: relative; display: flex; align-items: center; gap: calc(10px * var(--u)); min-height: calc(56px * var(--u)); padding: calc(6px * var(--u)) calc(12px * var(--u)) calc(6px * var(--u)) calc(14px * var(--u)); background: #112437; border: 1px solid #eef3f824; border-radius: calc(12px * var(--u)); transition: opacity 400ms, background 400ms; }
.fh-frame .fh-row { min-height: calc(38px * var(--s)); padding-top: calc(3px * var(--s)); padding-bottom: calc(3px * var(--s)); }
.fh-row::before { content: ""; position: absolute; left: 0; top: calc(8px * var(--u)); bottom: calc(8px * var(--u)); width: calc(3px * var(--u)); border-radius: 2px; background: var(--c); opacity: 0; transition: opacity 300ms; }
.fh-row.on { background: #16304a; }
.fh-row.on::before { opacity: 1; }
.fh-row.out:not(.on) { opacity: 0.72; }
.fh-fish { flex: none; width: calc(36px * var(--u)); height: calc(28px * var(--u)); display: block; }
.fh-main { flex: 1 1 auto; display: grid; gap: calc(1px * var(--u)); }
.fh-top { display: flex; align-items: center; gap: calc(8px * var(--u)); }
.fh-nm { flex: 0 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: calc(13px * var(--u)); line-height: 1.3; font-weight: 600; }
.fh-chip { flex: none; text-decoration: none; padding: 0 0.5em; border: 1px solid #eef3f833; border-radius: 4px; color: ${MUTED}; font-size: calc(9.5px * var(--u)); line-height: 1.6; letter-spacing: 0.06em; }
.fh-pr { flex: none; margin-left: auto; font-size: calc(13px * var(--u)); line-height: 1.3; font-weight: 500; font-variant-numeric: tabular-nums; }
.fh-pr.sealed { color: ${MUTED}; font-weight: 400; }
.fh-why { font-size: calc(12px * var(--u)); line-height: 1.3; color: ${MUTED}; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; overflow-wrap: anywhere; }
.fh-frame .fh-why { -webkit-line-clamp: 1; }
.fh-why.bad { color: #f0777b; } .fh-why.warn { color: #fcd34d; } .fh-why.good { color: #34d399; } .fh-why.shield { color: ${SHIELD}; } .fh-why.live { color: #eef3f8; }
.fh-deal { position: absolute; z-index: 3; right: 3%; top: 50%; transform: translateY(-50%); width: min(40%, calc(320px * var(--s))); padding: calc(18px * var(--s)) calc(22px * var(--s)); border-radius: calc(14px * var(--s)); background: #0e2236; border: 1px solid #eef3f833; }
.fh-flow .fh-deal { position: static; transform: none; width: auto; margin: 8px 12px 0; padding: 16px; border-radius: 14px; }
.fh-deal-in { animation: fh-deal 500ms ease-out both; }
@keyframes fh-deal { from { opacity: 0; transform: translateY(calc(8px * var(--s))); } to { opacity: 1; transform: none; } }
.fh-calm .fh-deal-in { animation: none; }
.fh-deal .k { font-size: calc(11px * var(--s)); line-height: 1.3; letter-spacing: 0.1em; text-transform: uppercase; color: ${MINT}; }
.fh-deal .n { font-size: calc(32px * var(--s)); line-height: 1.15; font-weight: 500; font-variant-numeric: tabular-nums; margin-top: calc(4px * var(--s)); }
.fh-flow .fh-deal .n { font-size: 28px; }
.fh-deal .t { font-size: calc(13px * var(--s)); line-height: 1.35; margin-top: calc(2px * var(--s)); color: ${MUTED}; }
.fh-deal .l { font-size: calc(11px * var(--s)); line-height: 1.5; margin-top: calc(8px * var(--s)); }
.fh-deal .p { font-size: calc(11px * var(--s)); line-height: 1.5; color: ${MINT}; }
.fh-flow .fh-deal .t { font-size: 13px; }
.fh-flow .fh-deal .l, .fh-flow .fh-deal .p { font-size: 12px; }
`;

function wordClass(v: SellerView): string {
  if (v.state === "winner" || v.ledger.startsWith("Fit OK")) return "good";
  if (v.reason === "shield_block") return "shield";
  if (v.reason === "failed_fit") return "warn";
  if (v.reason === "highest_price" || v.reason === "outranked" || v.reason === "advocate_veto" || v.reason === "refused") return "bad";
  return "";
}

/** One plain line about a seller right now, from its state, ledger and reason. */
function explain(v: SellerView): string {
  if (v.state === "winner") return "Winner";
  if (v.state === "sealed") return "Bid is in, price sealed";
  if (v.state === "open") return /^Fit OK/.test(v.ledger) ? `Still in. ${v.ledger.replace(/ · /g, ", ")}` : "Still in";
  switch (v.reason) {
    case "shield_block": return "Blocked by Smell Test: hidden instructions aimed at the buying agent";
    case "outranked": return v.ledger.startsWith("Outranked · ") ? `Outranked: ${v.ledger.slice("Outranked · ".length)}` : "Outranked";
    case "refused": return "Refused: below this seller's floor price";
    case "advocate_veto": return "Vetoed by Advocate: the listing did not match the condition";
    case "highest_price": return "Out: the highest price";
    case "failed_fit": return `Out: ${v.ledger.replace(/^Out · /, "")}`;
    default: return v.ledger;
  }
}

function FishIcon({ color, out, agent }: { color: string; out: boolean; agent?: string }) {
  const kind = avatarFor(agent);
  const colors = avatarColors(kind, color, out);
  return (
    <svg className="fh-fish" viewBox="0 0 36 28" shapeRendering="crispEdges" aria-hidden="true">
      {runs(AVATAR_GRIDS[kind]).map((r, i) => (colors[r.ch] ? <rect key={i} x={r.x * 2} y={r.y * 2} width={r.w * 2} height={2} fill={colors[r.ch]} /> : null))}
    </svg>
  );
}

function Ledger({ script, phase }: { script: FloorScript; phase: FloorPhase }) {
  const focus = phase.shieldAt ?? phase.checkerAt ?? phase.buyerAt;
  const live = phase.callText ?? (phase.think && phase.think.who !== "buyer" ? phase.think.text : null);
  return (
    <div className="fh-ledger" aria-label="Sellers">
      {script.sellers.map((s) => {
        const v = phase.sellers[s.id];
        if (!v) return null;
        const on = s.id === focus;
        const out = v.state === "eaten";
        const text = on && live ? live : explain(v);
        const tone = on && live ? "live" : wordClass(v);
        const color = SLOT_COLOR[s.slot] ?? MUTED;
        return (
          <div key={s.id} className={`fh-row${on ? " on" : ""}${out ? " out" : ""}`} style={{ "--c": color } as CSSProperties}>
            <FishIcon color={color} out={out} agent={s.agent} />
            <div className="fh-main">
              <div className="fh-top">
                <span className="fh-nm">{s.name}</span>
                <u className="fh-chip fh-mono">{s.origin}</u>
                <b className={`fh-pr fh-mono${v.price === null ? " sealed" : ""}`}>{v.price === null ? "Sealed" : usd(v.price)}</b>
              </div>
              <div className={`fh-why ${tone}`} title={text}><span key={text} className="fh-in">{text}</span></div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Deal({ deal, part }: { deal: NonNullable<FloorPhase["deal"]>; part: string }) {
  const lines = deal.lines.filter((l) => l !== "Stripe test mode");
  const partLine = deal.part.startsWith(part) ? deal.part : `${part} · ${deal.part}`;
  return (
    <div className="fh-deal fh-mono" aria-live="polite">
      <div className="fh-deal-in">
        <div className="k">Deal</div>
        <div className="n" style={SANS}>{usd(deal.price)}</div>
        <div className="t" style={SANS}>{partLine}</div>
        <div className="l">
          {lines.join(" · ")}
          {deal.approvedByPhone && !lines.some((l) => l.toLowerCase().includes("approved by phone")) && <>{lines.length > 0 ? " · " : ""}approved by phone</>}
        </div>
        {deal.stripeTest && <div className="p">Paid · Stripe test mode</div>}
      </div>
    </div>
  );
}

/** The 1920 x 1080 video frame: text sized for 1920 (smallest 22 px), the stage a little narrower so the ledger fits under it. */
export const FRAME = { w: 1920, h: 1080, stageW: 1600 } as const;

/** Wraps the renderer (children) with the HUD. `width` is the stage's CSS width; the stage keeps a 16:9 box and the ledger sits below it.
 * `frame` lays the whole thing out in exactly FRAME.w x FRAME.h (the stage is then FRAME.stageW wide). */
export function FloorHud({ script, phase, width, frame = false, reducedMotion = false, bare = false, children }: { script: FloorScript; phase: FloorPhase; width: number; frame?: boolean; reducedMotion?: boolean; bare?: boolean; children: ReactNode }) {
  const compact = !frame && width < COMPACT_BELOW;
  const s = frame ? FRAME.w / 960 : compact ? 1 : Math.max(0.5, width / 960);
  const stageW = frame ? FRAME.stageW : width;
  const two = frame || width >= TWO_COLS_AT;
  const vars = { "--s": s, "--u": frame ? 2 : 1, "--r": compact ? 0.8 : 1, ...(frame ? { width: FRAME.w, height: FRAME.h } : {}) } as CSSProperties;
  const stage = (
    <div className="fh-stage" style={{ width: frame ? stageW : "100%", height: bare ? undefined : (stageW * 9) / 16 }}>
      {children}
      {!bare && script.sim && <span className="fh-simchip fh-mono">SIM</span>}
      {!compact && !bare && phase.deal && <Deal deal={phase.deal} part={script.part} />}
    </div>
  );
  return (
    <div className={`fh ${compact ? "fh-flow" : "fh-over"}${two ? " fh-two" : ""}${frame ? " fh-frame" : ""}${bare ? " fh-bare" : ""}${reducedMotion ? " fh-calm" : ""}`} style={vars}>
      <style>{css}</style>
      {stage}
      {compact && !bare && phase.deal && <Deal deal={phase.deal} part={script.part} />}
      {!bare && <Ledger script={script} phase={phase} />}
    </div>
  );
}
