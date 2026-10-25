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
// # wall (a thin coral or rock ridge), . corridor with a pellet, 1-8 a seller pocket (a 2 x 2 room), 9 the centre pocket (winner), S Pac-Man start.
// 21 x 8 tiles of 40. Pockets 1-4 are spread (top-left, bottom-right, top-centre, bottom-left); 5-8 fill the rest. Rows 0-1 hold no pocket and
// the top-right corner (x > 700, y < 200) holds walls and pellets only. The top row is the reef ceiling; the bottom row has no wall (the sand is the floor).
// Top-left of tile (0,0) is MAZE_ORIGIN. No 4 x 4 block is all corridor.
export const MAZE: readonly string[] = [
  "#####################",
  "#..##...##....##...##",
  "#11#..55.#.33.#...#.#",
  "#11...55.#.33.#.66..#",
  "#.##.##.#...####66.##",
  "#..#.#...999..##.#..#",
  "#44.#.77...#.88...22#",
  "#44.#.77.#S#.88.#.22#",
];
export const MAZE_TILE = 40;
export const MAZE_ORIGIN = { x: 60, y: 172 };
export const REEF = { coralA: "#c4566b", coralB: "#e07a5f", rock: "#4a5d6e" } as const;

/**
 * SVG path data (one string per colour) for the maze walls: a 12 unit ridge through the centre of every wall tile, joined to each
 * adjacent wall tile, built from 4 unit cells with rounded corners, a few coral branch nubs and light/dark texture cells.
 */
export function mazeWallPaths(grid: readonly string[] = MAZE): { coralA: string; coralB: string; rock: string; light: string; dark: string } {
  const U = 4, per = MAZE_TILE / U; // 10 cells per tile
  const cols = (grid[0]?.length ?? 0) * per + 2, rows = grid.length * per + 2;
  const ras = new Uint8Array(cols * rows); // 0 empty, 1 coralA, 2 coralB, 3 rock
  const at = (x: number, y: number) => (x < 0 || y < 0 || x >= cols || y >= rows ? 0 : ras[y * cols + x]!);
  const put = (x: number, y: number, k: number) => { if (x >= 0 && y >= 0 && x < cols && y < rows) ras[y * cols + x] = k; };
  const wall = (r: number, c: number) => grid[r]?.[c] === "#";
  const kindOf = (r: number, c: number, d: number) => { const m = (r * 5 + c * 3 + d * 7) % 5; return m === 2 ? 3 : m === 1 ? 2 : 1; };
  const bar = (x0: number, y0: number, x1: number, y1: number, k: number) => { for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) put(x, y, k); };
  const nubs: Array<[number, number, number, number, boolean]> = []; // x, y, direction (0 up,1 down,2 left,3 right), length, horizontal segment
  grid.forEach((row, r) => [...row].forEach((ch, c) => {
    if (ch !== "#") return;
    const cx = c * per + per / 2, cy = r * per + per / 2;
    const k = kindOf(r, c, 0);
    bar(cx - 1, cy - 1, cx + 1, cy + 1, k);
    const right = wall(r, c + 1), down = wall(r + 1, c);
    if (right) { bar(cx, cy - 1, cx + per, cy + 1, kindOf(r, c, 1)); }
    if (down) { bar(cx - 1, cy, cx + 1, cy + per, kindOf(r, c, 2)); }
    if (!right && !down && !wall(r, c - 1) && !wall(r - 1, c)) bar(cx - 3, cy - 1, cx + 3, cy + 1, k); // a lone reef pillar becomes a short ridge
    for (const [on, horiz] of [[right, true], [down, false]] as const) {
      if (!on) continue;
      const n = 2 + ((r * 3 + c * 5 + (horiz ? 1 : 0)) % 2);
      for (let j = 0; j < n; j++) {
        const off = 3 + ((r * 7 + c * 11 + j * 5 + (horiz ? 2 : 0)) % (per - 5));
        const side = (r + c + j) % 2 === 0;
        const len = 1 + ((r + c * 2 + j) % 2);
        nubs.push(horiz ? [cx + off, cy, side ? 0 : 1, len, true] : [cx, cy + off, side ? 2 : 3, len, false]);
      }
    }
  }));
  // round the convex corners: a cell with exactly two perpendicular neighbours goes
  const snap = ras.slice();
  const was = (x: number, y: number) => (x < 0 || y < 0 || x >= cols || y >= rows ? 0 : snap[y * cols + x]!);
  for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
    if (!was(x, y)) continue;
    const u = was(x, y - 1) > 0, d = was(x, y + 1) > 0, l = was(x - 1, y) > 0, rr = was(x + 1, y) > 0;
    if (Number(u) + Number(d) + Number(l) + Number(rr) === 2 && (u || d) && (l || rr)) ras[y * cols + x] = 0;
  }
  for (const [x, y, dir, len] of nubs) {
    for (let j = 0; j < len; j++) {
      const [dx, dy] = dir === 0 ? [0, -2 - j] : dir === 1 ? [0, 2 + j] : dir === 2 ? [-2 - j, 0] : [2 + j, 0];
      if (!at(x + dx, y + dy)) put(x + dx, y + dy, 2);
    }
  }
  const out = { coralA: "", coralB: "", rock: "", light: "", dark: "" };
  const names = [null, "coralA", "coralB", "rock"] as const;
  for (let y = 0; y < rows; y++) {
    let x = 0;
    while (x < cols) {
      const k = ras[y * cols + x]!;
      if (!k) { x++; continue; }
      let w = 1;
      while (x + w < cols && ras[y * cols + x + w] === k) w++;
      out[names[k]!] += `M${MAZE_ORIGIN.x + x * U} ${MAZE_ORIGIN.y + y * U}h${w * U}v${U}h-${w * U}z`;
      x += w;
    }
  }
  for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
    if (!ras[y * cols + x]) continue;
    const h = (x * 31 + y * 17 + x * y) % 7;
    const cell = `M${MAZE_ORIGIN.x + x * U} ${MAZE_ORIGIN.y + y * U}h${U}v${U}h-${U}z`;
    if (h === 0) out.light += cell; else if (h === 3) out.dark += cell;
  }
  return out;
}

// ---- Aquarium support agents (additions only) ----
// 16x14 pufferfish facing left. X body, D darker spots, S fins and tail, E eye.
export const PUFFER: Grid = [
  "....XXXXXXXX....", "..XXXXXXXXXXXX..", ".XXXDXXXXXXXXXX.", ".XXEXXXXXXXXDXXS", "XXXXXXXXXXXXXXSS", "XXXDXXXXXXXXXXSS",
  "XXXXXXXXXXXDXXSS", "XXXXXXXXXXXXXXSS", ".XXXXXDXXXXXXXS.", ".XXXXXXXXXXXXX..", "..XXXXXXXXXXXX..", "....XXXXXXXX....",
  "......SS..SS....", "......SS..SS....",
];
// 10x12 Checker: a box with a tick (T) and two feet.
export const CHECKER: Grid = [
  "..XXXXXX..", ".XXXXXXXX.", "XXXXXXXTTX", "XXXXXXTTXX", "XTTXXTTXXX", "XXTTTTXXXX", "XXXTTXXXXX", "XXXXXXXXXX",
  "XXXXXXXXXX", "XXXXXXXXXX", ".XX....XX.", ".XX....XX.",
];
// 12x14 Referee, arm down and arm up. C cap, H skin, E eye, K dark stripe, W light stripe.
export const REFEREE: Grid = [
  "...CCCCCC...", "..CCCCCCCC..", "..HHHHHHHH..", "..HEHHHHEH..", "..HHHHHHHH..", "...HHHHHH...", "..KKKKKKKK..",
  ".HWWWWWWWWH.", ".HKKKKKKKKH.", ".HWWWWWWWWH.", "..KKKKKKKK..", "..KK....KK..", "..KK....KK..", ".KKK....KKK.",
];
export const REFEREE_UP: Grid = [
  "...CCCCCC.HH", "..CCCCCCCC.H", "..HHHHHHHH.H", "..HEHHHHEH.H", "..HHHHHHHH.H", "...HHHHHH.HH", "..KKKKKKKKH.",
  ".HWWWWWWWW..", ".HKKKKKKKK..", ".HWWWWWWWW..", "..KKKKKKKK..", "..KK....KK..", "..KK....KK..", ".KKK....KKK.",
];

// ---- Aquarium product card icons (additions only) ----
// 16x12 icons. B body, K dark, A accent, G gold pins; each kind has its own colour map in PRODUCT_COLORS.
export type ProductKind = "gpu" | "cpu" | "ssd" | "ram" | "box";
export const PRODUCT_ICONS: Record<ProductKind, Grid> = {
  gpu: [
    "BBBBBBBBBBBBBBBB", "BKKKKKKBKKKKKKBB", "BKAAAAKBKAAAAKBB", "BKAKKAKBKAKKAKBB", "BKAKKAKBKAKKAKBB", "BKAAAAKBKAAAAKBB",
    "BKKKKKKBKKKKKKBB", "BBBBBBBBBBBBBBBB", "BBBBBBBBBBBBBBBB", "..GGG.GGGGGG.GG.", "..GGG.GGGGGG.GG.", "................",
  ],
  cpu: [
    "...G.G.G.G.G.G..", "..BBBBBBBBBBBB..", "GGBKKKKKKKKKKBGG", "..BKKAAAAAAKKB..", "GGBKKAKKKKAKKBGG", "..BKKAKKKKAKKB..",
    "GGBKKAAAAAAKKBGG", "..BKKKKKKKKKKB..", "GGBKKKKKKKKKKBGG", "..BBBBBBBBBBBB..", "...G.G.G.G.G.G..", "................",
  ],
  ssd: [
    "................", "................", "BBBBBBBBBBBBBBBB", "BKKKKBKKKKBKKKBB", "BKKKKBKKKKBKKKBB", "BKKKKBKKKKBKKKBB",
    "BKKKKBKKKKBKKKBB", "BBBBBBBBBBBBBBBB", "BBBBBBBBBBBBBBBB", "GG.GG.GG.GG.GG.G", "GG.GG.GG.GG.GG.G", "................",
  ],
  ram: [
    "................", "BBBBBBBBBBBBBBBB", "BKKKBKKKBKKKBKKB", "BKKKBKKKBKKKBKKB", "BKKKBKKKBKKKBKKB", "BKKKBKKKBKKKBKKB",
    "BBBBBBBBBBBBBBBB", "BBBBBBBBBBBBBBBB", "GGGGGG..GGGGGGGG", "GGGGGG..GGGGGGGG", "................", "................",
  ],
  box: [
    "................", "KKKKKKKKKKKKKKKK", "KBBBBBBAABBBBBBK", "KBBBBBBAABBBBBBK", "KKKKKKKKKKKKKKKK", "KBBBBBBAABBBBBBK",
    "KBBBBBBAABBBBBBK", "KBBBBBBAABBBBBBK", "KBBBBBBAABBBBBBK", "KBBBBBBAABBBBBBK", "KBBBBBBAABBBBBBK", "KKKKKKKKKKKKKKKK",
  ],
};
export const PRODUCT_COLORS: Record<ProductKind, Record<string, string>> = {
  gpu: { B: "#4b6b85", K: "#1d3b57", A: PAL.cyan, G: PAL.pac },
  cpu: { B: "#8fa0b2", K: "#1d3b57", A: PAL.mint, G: PAL.pac },
  ssd: { B: "#4b6b85", K: "#1d3b57", A: PAL.cyan, G: PAL.pac },
  ram: { B: "#2f7a5b", K: "#1d3b57", A: PAL.mint, G: PAL.pac },
  box: { B: AQUA.sandA, K: "#7a6540", A: "#e8d9b0" },
};
/** Which icon a part gets: GPU, CPU, SSD and RAM have their own; motherboard, cooler, PSU, case and anything else get the generic box. */
export function productKind(part: string): ProductKind {
  const p = part.toLowerCase();
  if (/\b(gpu|graphics|rtx|gtx|radeon|geforce|video card)\b/.test(p)) return "gpu";
  if (/\b(cpu|processor|ryzen|core i\d)\b/.test(p)) return "cpu";
  if (/\b(ssd|nvme|m\.2|storage|hard drive)\b/.test(p)) return "ssd";
  if (/\b(ram|memory|ddr\d?|dimm)\b/.test(p)) return "ram";
  return "box";
}

// ---- Agent avatars as pixel sprites (aquarium scene) ----
// 18 x 14 grids facing left like FISH. Eyes are W (white) and P (pupil) everywhere; K is ink (brows, mouth, notch) and never turns blue.
export type AvatarKind = "fish" | "whale" | "angler" | "hermit" | "mirror";

// seller_1 blue whale: a stack of boxes as the spout. X body, L belly, F fins and flukes, B box.
export const WHALE: Grid = [
  "BB................", "BB................", "...B..............", ".....B..........FF", "....XXXXXXXXX..FFF", "..XXXXXXXXXXXX.FF.",
  ".XXXXXXXXXXXXXXF..", "XXWPXXXXXXXXXXXX..", "XXXXXXXXXXXXXX.FF.", "LLLLLLLLLLLLLL.FFF", ".LLLLLLLLLLLL...FF", "..LLLFFLLLL.......",
  "..LLLLLLLLL.......", "....LLLLLL........",
];
// seller_3 anglerfish: H glow, G lure, K stalk, M open mouth, F fins. The half-closed eye is a body-colour lid over W and P.
export const ANGLER: Grid = [
  "....KKKKKKK.......", "..HHK.......K.....", ".HGGH.......K.....", "..HH........XXX...", "...XXXXXXXXXX.FF..", "..XXXXXXXXXXXXFFF.",
  ".XXXXWPXXXXXXXFF..", "MMMMXXXXXXXXXXFFF.", "MMMMMXXXXXXXXXFF..", "MMMMMMXXXXXXXXF...", "MMMMMMXXXXXXXXF...", ".XXXXXXXXXXXXX....",
  "..XXXXXFFXXXXX....", "....XXXXXXXX......",
];
// seller_5 hermit crab: S shell, R shell spiral, M mint patch, O crab, K claw notch.
export const HERMIT: Grid = [
  "..........SSSS....", "........SSSSSSSS..", ".WW.WW.SSSSSMMSSS.", ".WP.WP.SSRRSMMSSS.", "..O..O.SSRSSSSRSS.", "..O..O.SSSRRRRSSS.",
  ".OOOOOOOOSSSSSSS..", "OOKOOOOOOOSSSSSS..", "OOOOOOOOOOSSSS....", ".OOOOOOOOO........", ".OOK.OOOO.........", "...O..O..O........",
  "...O..O..O........", "..OO.OO.OO........",
];
// seller_6 Central Comp (MIRROR): a dashed outline fish (D line, F faint fill, W and P eye) over a waterline (L) and its faint reflection (R line, G fill).
export const MIRROR_FISH: Grid = [
  ".....DD..DD.......", "...DD.FFFFFF.D..D.", "..D.FFFFFFFFFD.D..", ".D.FFDFFFFFFFFD...", "D..FFFFFFFFFFD.D..", ".D.FFFFFFFFFD..D..",
  "..D.D.D.D.D.D.....", "LLLLLLLLLLLLLLLLLL", "..R.R.R.R.R.R.....", ".R.GGGGGGGGGR..R..", "R..GGGGGGGGGGR.R..", ".R.GGRGGGGGGGGR...",
  "..R.GGGGGGGGGR.R..", ".....R.RR.R.......",
];
// shield: hammerhead shark seen from above, head to the left. H hammer, X body, L highlight, F fins, D gill slits.
export const HAMMERHEAD: Grid = [
  ".......FFF........", "WPHH...FFFF.......", "HLLLH.FFFFF.......", "HHHHXXXXXXX.......", "HHHHXXXXXXXXX...FF", "HHHHXXXXXXXXXXXFF.",
  "HHHHXXXXXXXXXXXXFF", "HHHHXDXDXXXXXXXXF.", "HHHHXDXDXXXXXXXXF.", "HHHHXXXXXXXXXXXFF.", "HHHHXXXXXXXX...FFF", "HHHHH.FFFFF....FFF",
  "WPHH...FFFF.......", ".......FFF........",
];
// advocate: pufferfish, puffed up, one raised brow (K), pursed mouth (K). S spikes, B belly, D spots, F fins.
export const PUFFER_ADVOCATE: Grid = [
  "....S..S..S.......", "....XXXXXXXX......", "..SXXXXXXXXXXS.FF.", ".SXXKKKXXXXXXXXXFF", "SXXWWXXXXDXXXXXXFF", ".XXPWXXXXXXXXXXXF.",
  ".XXXXXXXXDXXXXXXF.", "KXXXXXXXXXXXXXXFF.", "SXXBBBBBBBBBXXXXF.", ".XBBBBBBBBBBBBXXFF", "SXXBBBBBFBBBBBXX..", "..XXBBBBBBBBXX....",
  "...SXXXXXXXXS.....", "....S..S..S.......",
];

/** Which avatar a seller draws: the team's named sellers get theirs, every other or unknown seller keeps the fish. */
export function avatarFor(agent: string | undefined): AvatarKind {
  switch (agent) {
    case "seller_1": return "whale";
    case "seller_3": return "angler";
    case "seller_5": return "hermit";
    case "seller_6": return "mirror";
    default: return "fish";
  }
}

export const AVATAR_GRIDS: Record<AvatarKind, Grid> = { fish: FISH, whale: WHALE, angler: ANGLER, hermit: HERMIT, mirror: MIRROR_FISH };

const COMMON = { W: PAL.white, P: PAL.ink, K: PAL.ink };
export const AVATAR_PALETTES: Record<Exclude<AvatarKind, "fish">, Record<string, string>> = {
  whale: { ...COMMON, X: "#8fa0b2", L: "#e3e8ef", F: "#5b6b7c", B: "#e3e8ef" },
  angler: { ...COMMON, X: "#3b4d66", F: "#1f3a55", K: "#5b6b7c", M: "#b4232a", G: "#fcd34d", H: "#7a6a2a" },
  hermit: { ...COMMON, S: "#5b6b7c", R: "#8fa0b2", M: "#0f9d76", O: "#d97706" },
  mirror: { ...COMMON, D: "#8fa0b2", F: "#213f57", L: "#2c4d6b", R: "#4a6075", G: "#1a3850" },
};
export const HAMMER_COLORS: Record<string, string> = { ...COMMON, H: "#0891b2", X: "#0891b2", L: "#22d3ee", F: "#0e7490", D: "#0e7490" };
export const ADVOCATE_COLORS: Record<string, string> = { ...COMMON, X: "#0f9d76", B: "#6ee7b7", S: "#0b7a5b", F: "#0b7a5b", D: "#0b7a5b" };

const lum = (h: string) => (parseInt(h.slice(1, 3), 16) * 0.3 + parseInt(h.slice(3, 5), 16) * 0.59 + parseInt(h.slice(5, 7), 16) * 0.11) / 255;
/** Colours for a seller's avatar. Caught or out sellers turn the frightened blue (same shape, lighter and darker shades kept, blank eye). */
export function avatarColors(kind: AvatarKind, base: string, scared: boolean): Record<string, string> {
  if (kind === "fish") return fishColors(base, scared);
  const pal = AVATAR_PALETTES[kind];
  if (!scared) return { ...pal };
  const out: Record<string, string> = {};
  for (const [k, c] of Object.entries(pal)) {
    if (k === "W" || k === "P") out[k] = PAL.white;
    else if (k === "K" && kind !== "angler") out[k] = c;
    else { const l = lum(c); out[k] = l < 0.3 ? mix(PAL.scared, "#000000", 0.3) : l > 0.65 ? mix(PAL.scared, "#ffffff", 0.4) : PAL.scared; }
  }
  return out;
}
