// web/src/lib/scoreboard.ts
// The landing's three numbers, read from the scoreboard Lane C generates (data/scoreboard.json). The copy in fixtures/ is kept
// identical by scoreboard.test.ts, so the page can never drift from the measured file. Nothing here is typed in by hand.
import scoreboard from "./fixtures/scoreboard.json" with { type: "json" };

interface Tile { id: string; status: string; detail: Record<string, unknown> }
const tiles = (scoreboard as { tiles: Tile[]; generated_at: string }).tiles;
const tile = (id: string) => tiles.find((t) => t.id === id);
const num = (v: unknown) => (typeof v === "number" ? v : NaN);

export interface ProofStat { value: string; label: string; caveat: string; measured: boolean }

/** "39 of 39" style facts. A tile that is missing or not measured yields a "not measured" line rather than a number. */
export function proofStats(shieldName: string): ProofStat[] {
  const fit = tile("fit_accuracy"); const fitChecked = (fit?.detail.checked ?? {}) as Record<string, unknown>;
  const atk = tile("attacks_blocked"); const held = (atk?.detail.held_out ?? {}) as Record<string, unknown>;
  const voice = tile("voice_attacks"); const first = (voice?.detail.first_run ?? {}) as Record<string, unknown>;
  const heldBlocked = Math.round(num(held.attacks) * num(held.block_rate));
  const honestBlocked = Array.isArray(held.false_blocks) ? held.false_blocks.length : NaN;
  const honestN = Number.isFinite(num(held.false_block_rate)) && honestBlocked >= 0 ? Math.round(honestBlocked / num(held.false_block_rate)) : NaN;
  const stat = (ok: boolean, value: string, label: string, caveat: string): ProofStat => ({ value: ok ? value : "not measured", label, caveat: ok ? caveat : "no measured tile", measured: ok });
  return [
    stat(fit?.status === "measured" && Number.isFinite(num(fitChecked.correct)), `${num(fitChecked.correct)} of ${num(fitChecked.n)}`, "fit checks right", "tuned set"),
    stat(atk?.status === "measured" && Number.isFinite(heldBlocked), `${heldBlocked} of ${num(held.attacks)}`, `attacks stopped by ${shieldName}`, Number.isFinite(honestN) ? `held-out, rules only; ${honestBlocked} of ${honestN} honest pages blocked` : "held-out, rules only"),
    stat(voice?.status === "measured" && Number.isFinite(num(first.denied)), `${num(first.denied)} of ${num(first.n)}`, "voice attacks denied", "first run"),
  ];
}

export const SCOREBOARD_GENERATED_AT = (scoreboard as { generated_at: string }).generated_at;
