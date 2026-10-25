// Roman numerals for 1..3999 (bout numbers in the program).
const TABLE: [number, string][] = [
  [1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"], [90, "XC"],
  [50, "L"], [40, "XL"], [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"],
];

export function roman(n: number): string {
  if (!Number.isInteger(n) || n < 1 || n > 3999) throw new RangeError(`roman: ${n} is outside 1..3999`);
  let rest = n;
  let out = "";
  for (const [v, s] of TABLE) {
    while (rest >= v) {
      out += s;
      rest -= v;
    }
  }
  return out;
}
