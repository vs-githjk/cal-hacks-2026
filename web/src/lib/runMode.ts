// What each service is doing right now, read from the market's own public floor events (never hardcoded).
// A service that has written no event yet says so; one that has says which origin tag its events carry.

export interface EventLike {
  kind: string;
  origin: string;
}

const SERVICES: { name: string; kind: string }[] = [
  { name: "Advocate", kind: "advocate_card" },
  { name: "Shield", kind: "verdict" },
  { name: "Claim check", kind: "claim_checked" },
  { name: "Payments", kind: "payment_recorded" },
];

const ORDER = ["LIVE", "MIRROR", "SIM"];

/** "SIM (6)", "MIRROR + SIM (10)", or "no events yet". Anything not LIVE or MIRROR counts as SIM. */
export function serviceStatuses(events: readonly EventLike[], connected: boolean): { name: string; text: string }[] {
  return SERVICES.map(({ name, kind }) => {
    if (!connected) return { name, text: "unknown" };
    const mine = events.filter((e) => e.kind === kind);
    if (mine.length === 0) return { name, text: "no events yet" };
    const origins = ORDER.filter((o) => mine.some((e) => (e.origin === "LIVE" || e.origin === "MIRROR" ? e.origin : "SIM") === o));
    return { name, text: `${origins.join(" + ")} (${mine.length})` };
  });
}
