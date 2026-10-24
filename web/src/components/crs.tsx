// The CRS supplier signal beside a seller: band chip, Lane A's fixed reason and, for a recorded result, when it was cached.
import type { CrsView } from "@/lib/crs";

const BAND: Record<CrsView["band"], { text: string; tone: string }> = {
  verified_stable: { text: "CRS verified", tone: "border-mint text-mint" },
  caution: { text: "CRS caution", tone: "border-amber text-amber" },
  not_verified: { text: "CRS not verified", tone: "border-line-2 text-muted" },
  unavailable: { text: "CRS unavailable", tone: "border-line-2 text-muted" },
};

export function CrsSignal({ view }: { view: CrsView | null }) {
  if (!view) return null;
  const b = BAND[view.band];
  return (
    <span className="mt-1 block text-[12px] leading-[1.4] text-muted">
      <span className={`mr-1.5 inline-flex rounded-md border px-1.5 py-px font-mono text-[11px] font-semibold ${b.tone}`}>{b.text}</span>
      {view.reason}
      {view.cached && <span className="block font-mono text-[11px]">{view.cached}</span>}
    </span>
  );
}
