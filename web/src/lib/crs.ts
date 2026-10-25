// CRS supplier signal (docs/changes/0033-A-crs-supplier-signal.md): the band only, with Lane A's fixed reason text.
// No raw CRS data reaches the market or this screen. A seller with no signal (a trusted individual) is exempt: no band.

export type CrsBand = "verified_stable" | "caution" | "not_verified";
export type CrsOrigin = "LIVE" | "MIRROR" | "SIM";

// The sandbox-specific text is honest only for a result that actually came from the CRS sandbox (or a recording
// of one). Any other source (a live check, a mirrored one, or a simulated one) gets a source-neutral reason.
export const CRS_REASON: Record<CrsBand | "unavailable", string> = {
  verified_stable: "Synthetic representative identity verified by CRS sandbox.",
  caution: "CRS sandbox returned a fraud alert; additional proof is required.",
  not_verified: "CRS sandbox could not verify the synthetic representative identity.",
  unavailable: "CRS sandbox check unavailable; a current recorded result may be used.",
};
const CRS_REASON_GENERIC: Record<CrsBand, string> = {
  verified_stable: "Representative identity verified by CRS.",
  caution: "CRS returned a fraud alert; additional proof is required.",
  not_verified: "CRS could not verify the representative identity.",
};
/** #332: sandbox or live is shown LIVE; recorded or mirror is MIRROR; simulated (or anything unrecognized) is SIM. */
const SOURCE_ORIGIN: Record<string, CrsOrigin> = { sandbox: "LIVE", live: "LIVE", recorded: "MIRROR", mirror: "MIRROR", simulated: "SIM" };
const SANDBOX_TEXT_SOURCES = new Set(["sandbox", "recorded"]);

/** A cached result is usable for at most 24 hours. Future skew past this is never "fresh": a clock cannot run ahead. */
export const CRS_MAX_AGE_MS = 24 * 60 * 60 * 1000;
export const CRS_MAX_SKEW_MS = 5 * 60 * 1000;

export interface SignalRow { supplierId: string; stability: string; checkedAt: string; source: string }
export interface CrsView {
  band: CrsBand | "unavailable";
  reason: string;
  cached: string | null; // "cached from CRS <time>" for a recorded result
  eligible: boolean; // only verified_stable may be picked
  greyed: boolean; // not_verified and unavailable rows are greyed out
  origin: CrsOrigin; // honest source chip: never implies sandbox for a live, mirror or simulated row
}

const BANDS: CrsBand[] = ["verified_stable", "caution", "not_verified"];
/** "2026-10-24 07:50 UTC": the original checked_at, without Intl (server and browser format alike). */
const utc = (iso: string) => {
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? iso : `${t.toISOString().slice(0, 10)} ${t.toISOString().slice(11, 16)} UTC`;
};

export function crsFor(rows: readonly SignalRow[], sellerId: string, nowMs: number): CrsView | null {
  const r = rows.filter((x) => x.supplierId === sellerId).sort((a, b) => Date.parse(b.checkedAt) - Date.parse(a.checkedAt))[0];
  if (!r) return null;
  const origin = SOURCE_ORIGIN[r.source] ?? "SIM";
  const age = nowMs - Date.parse(r.checkedAt);
  if (!(age <= CRS_MAX_AGE_MS && age >= -CRS_MAX_SKEW_MS)) {
    return { band: "unavailable", reason: CRS_REASON.unavailable, cached: null, eligible: false, greyed: true, origin };
  }
  const band: CrsBand = BANDS.includes(r.stability as CrsBand) ? (r.stability as CrsBand) : "not_verified"; // malformed or unknown: not verified
  const reason = SANDBOX_TEXT_SOURCES.has(r.source) ? CRS_REASON[band] : CRS_REASON_GENERIC[band];
  return {
    band, reason, cached: r.source === "recorded" ? `cached from CRS ${utc(r.checkedAt)}` : null,
    eligible: band === "verified_stable", greyed: band === "not_verified", origin,
  };
}
