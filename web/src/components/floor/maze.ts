// web/src/components/floor/maze.ts
// Pure grid helpers for the reef maze: pocket patrol loops and shortest paths. Tiles are [row, col].
export type Tile = readonly [number, number];

export const isWalk = (grid: readonly string[], r: number, c: number): boolean => (grid[r]?.[c] ?? "#") !== "#";
export const sameTile = (a: Tile, b: Tile): boolean => a[0] === b[0] && a[1] === b[1];
export const adjacent = (a: Tile, b: Tile): boolean => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) === 1;

export function findTile(grid: readonly string[], ch: string): Tile | null {
  for (let r = 0; r < grid.length; r++) { const c = grid[r]!.indexOf(ch); if (c >= 0) return [r, c]; }
  return null;
}

/** Bounding rectangle of the tiles marked `ch`, or null. */
export function pocketRect(grid: readonly string[], ch: string): { r0: number; c0: number; r1: number; c1: number } | null {
  let rect: { r0: number; c0: number; r1: number; c1: number } | null = null;
  grid.forEach((row, r) => [...row].forEach((x, c) => {
    if (x !== ch) return;
    rect = rect ? { r0: Math.min(rect.r0, r), c0: Math.min(rect.c0, c), r1: Math.max(rect.r1, r), c1: Math.max(rect.c1, c) } : { r0: r, c0: c, r1: r, c1: c };
  }));
  return rect;
}

/** Closed clockwise loop around a pocket room (at least 2 x 2, all open): every step, and last back to first, is to an adjacent corridor tile. [] when the pocket is not such a room. */
export function patrolLoop(grid: readonly string[], pocket: string): Tile[] {
  const rc = pocketRect(grid, pocket);
  if (!rc || rc.r1 - rc.r0 < 1 || rc.c1 - rc.c0 < 1) return [];
  const loop: Tile[] = [];
  for (let c = rc.c0; c <= rc.c1; c++) loop.push([rc.r0, c]);
  for (let r = rc.r0 + 1; r <= rc.r1; r++) loop.push([r, rc.c1]);
  for (let c = rc.c1 - 1; c >= rc.c0; c--) loop.push([rc.r1, c]);
  for (let r = rc.r1 - 1; r > rc.r0; r--) loop.push([r, rc.c0]);
  return loop.every(([r, c]) => isWalk(grid, r, c)) ? loop : [];
}

/** Shortest path of corridor tiles from `from` to `to`, both included (BFS, 4-neighbour), or null when unreachable. */
export function mazePath(grid: readonly string[], from: Tile, to: Tile): Tile[] | null {
  if (!isWalk(grid, from[0], from[1]) || !isWalk(grid, to[0], to[1])) return null;
  const key = (t: Tile) => t[0] * 1000 + t[1];
  const prev = new Map<number, Tile | null>([[key(from), null]]);
  const queue: Tile[] = [from];
  for (let i = 0; i < queue.length; i++) {
    const cur = queue[i]!;
    if (sameTile(cur, to)) {
      const path: Tile[] = [];
      for (let t: Tile | null = cur; t; t = prev.get(key(t)) ?? null) path.unshift(t);
      return path;
    }
    for (const [dr, dc] of [[0, 1], [1, 0], [0, -1], [-1, 0]] as const) {
      const n: Tile = [cur[0] + dr, cur[1] + dc];
      if (isWalk(grid, n[0], n[1]) && !prev.has(key(n))) { prev.set(key(n), cur); queue.push(n); }
    }
  }
  return null;
}

/** Non-negative modulo (JS % keeps the sign of the dividend). */
export const mod = (a: number, n: number): number => (n > 0 ? ((a % n) + n) % n : 0);

/** The loop tile at step k (any integer), or null for an empty loop. */
export function loopTile(loop: readonly Tile[], k: number): Tile | null {
  return loop.length ? loop[mod(k, loop.length)]! : null;
}

/** +1 when a walker on `loop` at step k last moved right, -1 left; it looks back past vertical steps. -1 for an empty or straight-vertical loop. */
export function heading(loop: readonly Tile[], k: number): number {
  const n = loop.length;
  for (let s = 0; s < n; s++) {
    const dc = loop[mod(k - s, n)]![1] - loop[mod(k - s - 1, n)]![1];
    if (dc !== 0) return dc > 0 ? 1 : -1;
  }
  return -1;
}

/** Seller pocket characters, in seller order: seller i uses POCKET_IDS[i]. With 4 or fewer sellers only 1 to 4 are used (spread out). */
export const POCKET_IDS = ["1", "2", "3", "4", "5", "6", "7", "8"] as const;

/** Top-left tile of the first n x n block that has no wall in it, or null (a maze with no big empty areas). */
export function emptyBlock(grid: readonly string[], n: number): Tile | null {
  for (let r = 0; r + n <= grid.length; r++) for (let c = 0; c + n <= (grid[0]?.length ?? 0); c++) {
    let open = true;
    for (let i = 0; i < n && open; i++) for (let j = 0; j < n; j++) if (!isWalk(grid, r + i, c + j)) { open = false; break; }
    if (open) return [r, c];
  }
  return null;
}
