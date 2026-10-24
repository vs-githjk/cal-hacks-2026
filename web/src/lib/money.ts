// Money and counts without Intl: the server and the browser can format differently (a hydration mismatch), so one plain formatter.

/** A whole number with thousands commas: 1234567 -> "1,234,567". */
export function commas(n: number): string {
  const s = String(Math.trunc(Math.abs(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return n < 0 && Math.trunc(n) !== 0 ? `-${s}` : s;
}

/** US dollars: "$1,000" for whole dollars, "$12.50" otherwise, "-$5" for negatives. */
export function formatMoney(x: number): string {
  const cents = Math.round(Math.abs(x) * 100);
  const dollars = commas(Math.floor(cents / 100));
  const body = x % 1 ? `${dollars}.${String(cents % 100).padStart(2, "0")}` : dollars;
  return `${x < 0 ? "-" : ""}$${body}`;
}
