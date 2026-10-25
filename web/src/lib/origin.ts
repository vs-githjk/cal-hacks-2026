// The origin labels the UI may show. SANDBOX (#449 RT-32) is a vendor's own test mode, e.g. a Stripe test charge:
// real API, no real money, so it is neither LIVE nor SIM. Anything unrecognised shows as SIM: never assume real.
// (Bids keep the three-way Origin in screens.ts; only events, which can describe a payment, carry SANDBOX.)

export type ChipOrigin = "LIVE" | "MIRROR" | "SANDBOX" | "SIM";

export const asChipOrigin = (o: string): ChipOrigin => (o === "LIVE" || o === "MIRROR" || o === "SANDBOX" ? o : "SIM");
