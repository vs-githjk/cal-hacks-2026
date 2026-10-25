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

// ---- Aquarium scene (additions only) ----
export const AQUA = { top: "#12324a", bottom: "#0b1b2b", sandA: "#c2a878", sandB: "#a88f62", weed: "#2f7a5b" } as const;
/** Seaweed stalk: x offset (in 5 px cells) of each cell from the base upward. */
export const WEED_OFFSETS = [0, 0, 5, 5, 5, 0, 0, -5, -5, 0, 0, 5] as const;
/** Deterministic darker sand cells (10 px) for a w x h floor, as [x, y] offsets from its top-left. */
export function sandCells(w: number, h: number): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  for (let j = 0; j < h / 10; j++) for (let i = 0; i < w / 10; i++) if ((i * 7919 + j * 104729 + i * j * 31) % 5 === 0) out.push([i * 10, j * 10]);
  return out;
}

// ---- Reef maze (aquarium scene) ----
// # wall (coral or rock), . corridor with a pellet, space empty corridor, 1-4 a seller pocket (a 2 x 3 room), 5 the centre pocket (winner), S Pac-Man start.
export const MAZE: readonly string[] = [
  "###################",
  "#111.....#333.....#",
  "#111.###.#333.##..#",
  "#.....#.555.#..444#",
  "#.#.222.555..#.444#",
  "#.#.222..S........#",
  "###################",
];
export const MAZE_TILE = 40;
export const MAZE_ORIGIN = { x: 100, y: 172 };
export const REEF = { coralA: "#c4566b", coralB: "#e07a5f", rock: "#4a5d6e" } as const;

/** SVG path data (one string per colour) for the maze walls: 40 px tiles with 5 px cells of irregular texture. */
export function mazeWallPaths(grid: readonly string[] = MAZE): { coralA: string; coralB: string; rock: string; light: string; dark: string } {
  const out = { coralA: "", coralB: "", rock: "", light: "", dark: "" };
  grid.forEach((row, r) => [...row].forEach((ch, c) => {
    if (ch !== "#") return;
    const x = MAZE_ORIGIN.x + c * MAZE_TILE, y = MAZE_ORIGIN.y + r * MAZE_TILE;
    const kind = (r * 5 + c * 3 + (r * c) % 3) % 4;
    const key = kind === 2 ? "rock" : kind === 1 ? "coralB" : "coralA";
    out[key] += `M${x} ${y}h${MAZE_TILE}v${MAZE_TILE}h-${MAZE_TILE}z`;
    for (let k = 0; k < 9; k++) {
      const idx = (r * 13 + c * 7 + k * 29 + k * k * 3) % 64;
      const cell = `M${x + (idx % 8) * 5} ${y + Math.floor(idx / 8) * 5}h5v5h-5z`;
      if (k % 2) out.light += cell; else out.dark += cell;
    }
  }));
  return out;
}
