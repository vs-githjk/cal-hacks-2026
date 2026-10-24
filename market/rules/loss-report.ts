import type { Ranked } from "./scoring";

export interface LossReportArgs {
  id: string; roundId: string; sellerId: string; won: boolean; gapBand: string; reason: string; sourceUrl: string;
  strategyDiff: { key: string; from: string; to: string }[]; whatToChange: string; whatToChangeOrigin: string; origin: string;
}

export function priceLossReports(
  roundId: string,
  finalRanked: Ranked[],
  evidenceByBid: Map<string, { origin: string; pickedListingUrls: string[] }>,
): LossReportArgs[] {
  const winner = finalRanked.find((row) => row.complete);
  if (!winner || !Number.isFinite(winner.score) || winner.score <= 0) return [];
  const reported = new Set<string>();
  reported.add(winner.bid.seller_id);
  const reports: LossReportArgs[] = [];
  for (const row of finalRanked) {
    if (!row.complete || !Number.isFinite(row.score) || row.score <= winner.score || reported.has(row.bid.seller_id)) continue;
    reported.add(row.bid.seller_id);
    const evidence = evidenceByBid.get(row.bid.id);
    if (!evidence || !["SIM", "MIRROR", "LIVE"].includes(evidence.origin)) continue;
    const sourceUrl = evidence.pickedListingUrls.find(isSafeHttpUrl);
    if (!sourceUrl) continue;
    const gap = ((row.score - winner.score) / winner.score) * 100;
    reports.push({
      id: `loss:${encodeURIComponent(roundId)}:${encodeURIComponent(row.bid.seller_id)}`,
      roundId, sellerId: row.bid.seller_id, won: false,
      gapBand: gap <= 5 ? "within5" : gap <= 10 ? "within10" : gap <= 20 ? "within20" : "over20",
      reason: "price", sourceUrl, strategyDiff: [],
      whatToChange: "Compare your selected listing with the winning offer and review your next bid.",
      whatToChangeOrigin: "SIM template",
      origin: evidence.origin,
    });
  }
  return reports;
}

function isSafeHttpUrl(value: string): boolean {
  if (value.length > 2048 || /[\u0000-\u001f\u007f\s]/.test(value)) return false;
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && !!url.hostname && !url.username && !url.password;
  } catch { return false; }
}
