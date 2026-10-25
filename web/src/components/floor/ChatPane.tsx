"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { ChatLine } from "@/lib/chatFeed";

/** The ASI:One chat, in two modes. "tile": the small video-call tile, one latest message at a time. "full": the whole conversation.
 * Sizes use container query units so the same pane reads at 390 px, 960 px and on the 1920 x 1080 frame. */

const INK = "#0b1b2b";
const PANEL = "#ffffff";
const TEXT = "#0b1b2b";
const MUTED = "#5b6b7c";
const HAIR = "#e6eaef";
const BUBBLE = "#f1f4f7";
const BLUE = "#1e4ed8";
const LIVE = "#22c55e";
const SANS: CSSProperties = { fontFamily: "var(--font-geist), Geist, ui-sans-serif, system-ui, sans-serif" };
const MONO: CSSProperties = { fontFamily: "var(--font-geist-mono), 'Geist Mono', ui-monospace, Menlo, Consolas, monospace" };

const SELLER_COLORS: Record<string, string> = { "1": "#e5484d", "2": "#f38ba8", "3": "#22d3ee", "4": "#f59e0b" };
const FALLBACK_AVATAR = "#9aa7b4";

/** Avatar colour by agent: buyer yellow, shield cyan, advocate mint, referee periwinkle, sellers by slot, others muted. */
export function agentColor(who: string): string {
  if (who === "buyer") return "#fcd34d";
  if (who === "shield") return "#22d3ee";
  if (who === "advocate") return "#34d399";
  if (who === "referee" || who === "caller") return "#c7d4ff";
  const m = /^seller_?(\d+)$/.exec(who);
  if (m) return SELLER_COLORS[m[1]!] ?? FALLBACK_AVATAR;
  return FALLBACK_AVATAR;
}

const css = `
.cp { container-type: inline-size; position: relative; width: 100%; height: 100%; background: ${PANEL}; color: ${TEXT}; overflow: hidden; display: flex; flex-direction: column; border-radius: 18px; }
.cp-full { height: 100%; }
.cp * { box-sizing: border-box; min-width: 0; }
.cp-head { display: flex; align-items: center; gap: 6px; flex: none; padding: max(4px, 2.4cqw) max(8px, 3.2cqw); background: #ffffff; border-bottom: 1px solid ${HAIR}; font-size: max(11px, 4cqw); font-weight: 500; line-height: 1.3; color: ${TEXT}; }
.cp-full .cp-head { padding: 12px 20px; font-size: 13px; }
.cp-dot { width: max(6px, 1.8cqw); height: max(6px, 1.8cqw); border-radius: 50%; flex: none; background: #b4bfcb; }
.cp-full .cp-dot { width: 8px; height: 8px; }
.cp-dot.live { background: ${LIVE}; }
.cp-title { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cp-sim { flex: none; padding: 0 0.45em; border: 1px solid #cfd6de; border-radius: 4px; background: #f7f9fb; color: ${MUTED}; letter-spacing: 0.06em; }
.cp-unread { flex: none; min-width: 1.6em; padding: 0 0.4em; text-align: center; border-radius: 999px; background: ${BLUE}; color: #ffffff; font-weight: 600; }
.cp-tilebody { position: relative; flex: 1 1 auto; overflow: hidden; }
.cp-latest { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: center; gap: 2px; padding: max(6px, 3cqw) max(8px, 3.4cqw); }
.cp-who { font-size: max(10px, 3.8cqw); line-height: 1.25; color: ${MUTED}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cp-text { font-size: max(10px, 4.6cqw); line-height: 1.3; overflow-wrap: anywhere; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 4; overflow: hidden; color: ${TEXT}; }
.cp-empty { color: ${MUTED}; }
.cp-scroll { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 16px 20px 20px; display: flex; flex-direction: column; gap: 12px; }
.cp-row { display: flex; gap: 10px; align-items: flex-start; max-width: min(100%, 36em); font-size: 15px; line-height: 1.4; }
.cp-row.me { align-self: flex-end; flex-direction: row-reverse; }
.cp-av { width: 2em; height: 2em; border-radius: 50%; flex: none; display: grid; place-items: center; color: ${INK}; font-weight: 600; font-size: 0.8em; }
.cp-col { display: grid; gap: 2px; justify-items: start; }
.cp-row.me .cp-col { justify-items: end; }
.cp-name { font-size: 0.8em; color: ${MUTED}; }
.cp-bub { padding: 0.5em 0.85em; border-radius: 1em; background: ${BUBBLE}; color: ${TEXT}; overflow-wrap: anywhere; white-space: pre-wrap; }
.cp-row.me .cp-bub { background: ${BLUE}; color: #ffffff; }
.cp-dots { display: inline-flex; gap: 0.3em; align-items: center; height: 1.1em; }
.cp-dots i { width: 0.45em; height: 0.45em; border-radius: 50%; background: #9aa7b4; display: block; animation: cp-dot 1.1s ease-in-out infinite; }
.cp-dots i:nth-child(2) { animation-delay: 0.15s; } .cp-dots i:nth-child(3) { animation-delay: 0.3s; }
.cp-calm .cp-dots i { animation: none; opacity: 0.7; }
@keyframes cp-dot { 0%, 80%, 100% { opacity: 0.3; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-0.2em); } }
.cp-tile .cp-dots { font-size: max(10px, 4.6cqw); }
`;

function Dots() {
  return <span className="cp-dots" role="img" aria-label="thinking"><i /><i /><i /></span>;
}

function Avatar({ line }: { line: ChatLine }) {
  const initial = (line.who === "buyer" ? "B" : line.name.trim().charAt(0) || line.who.charAt(0) || "?").toUpperCase();
  return <span className="cp-av" style={{ background: agentColor(line.who), ...SANS }} aria-hidden="true">{initial}</span>;
}

/** A thinking line is only shown while it is the newest line from its agent. */
function visibleLines(lines: ChatLine[]): ChatLine[] {
  const lastBy = new Map<string, string>();
  for (const l of lines) lastBy.set(l.who, l.id);
  return lines.filter((l) => l.kind !== "thinking" || lastBy.get(l.who) === l.id);
}

export function ChatPane({ lines, live, mode, unread = 0, reducedMotion }: { lines: ChatLine[]; live: boolean; mode: "tile" | "full"; unread?: number; reducedMotion: boolean }) {
  const shown = visibleLines(lines);
  const latest = shown[shown.length - 1] ?? null;
  const sim = lines.length > 0 && lines.every((l) => l.sim);
  const scroller = useRef<HTMLDivElement>(null);
  const lastId = shown[shown.length - 1]?.id;

  useEffect(() => {
    if (mode !== "full") return;
    const el = scroller.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: reducedMotion ? "auto" : "smooth" });
  }, [mode, lastId, reducedMotion]);

  const head = (
    <div className="cp-head" style={MONO}>
      <span className={`cp-dot${live ? " live" : ""}`} aria-hidden="true" />
      <span className="cp-title">ASI:One · Fish Market Buyer</span>
      {sim && <span className="cp-sim">SIM</span>}
      {mode === "tile" && unread > 0 && <span className="cp-unread" aria-label={`${unread} new messages`}>{unread > 99 ? "99+" : unread}</span>}
    </div>
  );

  if (mode === "tile") {
    return (
      <div className={`cp cp-tile${reducedMotion ? " cp-calm" : ""}`} style={SANS}>
        <style>{css}</style>
        {head}
        <div className="cp-tilebody">
          <AnimatePresence initial={false} mode="popLayout">
            <motion.div
              key={latest?.id ?? "empty"}
              className="cp-latest"
              initial={reducedMotion ? false : { opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -12 }}
              transition={{ duration: reducedMotion ? 0 : 0.2, ease: "easeOut" }}
            >
              {!latest ? (
                <div className="cp-text cp-empty">Waiting for the buyer...</div>
              ) : (
                <>
                  <div className="cp-who" style={MONO}>{latest.name}</div>
                  {latest.kind === "thinking" ? <div className="cp-text"><Dots /></div> : <div className="cp-text">{latest.text}</div>}
                </>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    );
  }

  return (
    <div className={`cp cp-full${reducedMotion ? " cp-calm" : ""}`} style={SANS}>
      <style>{css}</style>
      {head}
      <div className="cp-scroll" ref={scroller} role="log" aria-live="polite" aria-label="ASI:One conversation">
        {shown.length === 0 && <div className="cp-row cp-empty" style={{ color: MUTED }}>Waiting for the buyer...</div>}
        {shown.map((l) => {
          const me = l.who === "owner";
          return (
            <motion.div
              key={l.id}
              className={`cp-row${me ? " me" : ""}`}
              initial={reducedMotion ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: reducedMotion ? 0 : 0.2, ease: "easeOut" }}
            >
              {!me && <Avatar line={l} />}
              <div className="cp-col">
                {!me && <div className="cp-name" style={MONO}>{l.name}</div>}
                <div className="cp-bub">{l.kind === "thinking" ? <Dots /> : l.text}</div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
