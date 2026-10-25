// #398: a recorded snapshot is shown on the hosted site where a local API cannot be reached. Pure helpers only.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The label over a recorded snapshot: always SIM, with the UTC capture time, or "capture time unknown" when it cannot be read. */
export function recordedLine(isoAt: string): string {
  const d = new Date(isoAt);
  const pad = (n: number) => String(n).padStart(2, "0");
  const when = Number.isNaN(d.getTime())
    ? "capture time unknown"
    : `captured ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
  return `Recorded snapshot (SIM), ${when}. The live version runs locally.`;
}
