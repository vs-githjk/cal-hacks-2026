// web/src/components/floor/pixelArt.ts
// Pixel sprite grids and palette for the pixel floor ring. Pure data, no React.
// Grid letters: X body, W eye white, P pupil, B badge, E eye, M lens rim, L lens, "." empty.

export const PAL = {
  ink: "#0b1b2b", mat: "#112437", line: "#eef3f8", rope: "#5b6b7c", muted: "#8fa0b2",
  pac: "#ffd23f", red: "#e5484d", pink: "#f38ba8", cyan: "#22d3ee", orange: "#f59e0b", mint: "#34d399",
  scared: "#3b5bdb", pupil: "#1d3fb8", coral: "#f26d5b", lens: "#9fb4c7", white: "#fff",
} as const;

/** Ghost colour by seller slot 1..4 (index slot - 1). */
export const GHOST_COLORS = [PAL.red, PAL.pink, PAL.cyan, PAL.orange] as const;

export type Grid = readonly string[];

// 13x13 Pac-Man facing right, mouth open
export const PAC: Grid = [
  "....XXXXX....", "..XXXXXXXXX..", ".XXXXXXXXXXX.", ".XXXXXXXXX...", "XXXXXXXXX....", "XXXXXXX......", "XXXXXX.......",
  "XXXXXXX......", "XXXXXXXXX....", ".XXXXXXXXX...", ".XXXXXXXXXXX.", "..XXXXXXXXX..", "....XXXXX....",
];
// 13x13 Pac-Man, mouth closed (full circle)
export const PAC_CLOSED: Grid = [
  "....XXXXX....", "..XXXXXXXXX..", ".XXXXXXXXXXX.", ".XXXXXXXXXXX.", "XXXXXXXXXXXXX", "XXXXXXXXXXXXX", "XXXXXXXXXXXXX",
  "XXXXXXXXXXXXX", "XXXXXXXXXXXXX", ".XXXXXXXXXXX.", ".XXXXXXXXXXX.", "..XXXXXXXXX..", "....XXXXX....",
];
// 14x14 ghost
export const GHOST: Grid = [
  ".....XXXX.....", "...XXXXXXXX...", "..XXXXXXXXXX..", ".XXXXXXXXXXXX.", ".XWWXXXXWWXXX.", "XWWWWXXWWWWXXX", "XWWPPXXWWPPXXX",
  "XWWPPXXWWPPXXX", "XXWWXXXXWWXXXX", "XXXXXXXXXXXXXX", "XXXXXXXXXXXXXX", "XXXXXXXXXXXXXX", "XX.XXX..XXX.XX", "X...XX..XX...X",
];
// 18x14 fish facing left (head left, forked tail right). X body, T belly band, S fins and tail, W eye highlight, P pupil
export const FISH: Grid = [
  ".......SSSS.......", ".....SSSSSSS......", "....XXXXXXXXXX....", "..XXXXXXXXXXXXXSSS", ".XXXXXXXXXXXXXXSSS", "XXXWPXXXXXXXXXXSS.",
  "XXXPPXXXXXXXXXXS..", "XXXXXXXSSSXXXXXS..", "XXXXXXXXSSXXXXXS..", "TTTTTTTTTTTTTTTSS.", ".TTTTTTTTTTTTTTSSS", "..TTTTTTTTTTTTTSSS",
  "....XXXXXXXXXX....", "......SSSS........",
];
const GHOST_FLAT: Grid = GHOST.map((r) => r.replace(/[WP]/g, "X"));
/** Frightened (caught) ghost: no eyes, one blue body. */
export const GHOST_SCARED: Grid = GHOST_FLAT;

/** Cell size in SVG units for every sprite. */
export const CELL = 5;

/** Mix hex colour a toward b by t (0..1). */
export function mix(a: string, b: string, t: number): string {
  const n = (h: string, i: number) => parseInt(h.slice(1 + i * 2, 3 + i * 2), 16);
  const c = (i: number) => Math.round(n(a, i) + (n(b, i) - n(a, i)) * t).toString(16).padStart(2, "0");
  return `#${c(0)}${c(1)}${c(2)}`;
}
/** Fish palette from a body colour: belly band is 35 percent toward white, fins 22 percent toward black. Caught fish: blue, blank eye. */
export function fishColors(base: string, scared: boolean): Record<string, string> {
  const x = scared ? PAL.scared : base;
  return { X: x, T: mix(x, "#ffffff", 0.35), S: mix(x, "#000000", 0.22), W: PAL.white, P: scared ? PAL.white : PAL.ink };
}

// 11x14 Shield guard
export const SHIELD: Grid = [
  "...XXXXX...", "..XXXXXXX..", "..XEXXXEX..", "..XXXXXXX..", "...XXXXX...", ".XXXXXXXXX.", "XXXXBBBXXXX", "XXXBBBBBXXX",
  "XXXXBBBXXXX", "XXXXXBXXXXX", ".XXXXXXXXX.", ".XX.....XX.", ".XX.....XX.", "XXX.....XXX",
];
// 12x14 Auditor with magnifier
export const AUDIT: Grid = [
  "...XXXX.....", "..XXXXXX....", "..XEXXEX....", "..XXXXXX..MM", "...XXXX..MLLM", ".XXXXXXXXMLLM", "XXXXXXXXX.MM.", "XXXXXXXX.X...",
  "XXXXXXXX.....", "XXXXXXXX.....", ".XXXXXX......", ".XX..XX......", ".XX..XX......", "XXX..XXX.....",
];

export interface Run { x: number; y: number; w: number; ch: string }
const cache = new WeakMap<Grid, Run[]>();

/** Horizontal runs of equal letters (empty cells skipped), so a sprite is a few dozen rects, not hundreds. */
export function runs(grid: Grid): Run[] {
  const hit = cache.get(grid);
  if (hit) return hit;
  const out: Run[] = [];
  grid.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const ch = row[x]!;
      let w = 1;
      while (x + w < row.length && row[x + w] === ch) w++;
      if (ch !== ".") out.push({ x, y, w, ch });
      x += w;
    }
  });
  cache.set(grid, out);
  return out;
}
