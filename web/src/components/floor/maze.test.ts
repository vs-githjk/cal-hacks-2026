import test from "node:test";
import assert from "node:assert/strict";
import { CHECKER, MAZE, MAZE_ORIGIN, MAZE_TILE, PUFFER, REFEREE, REFEREE_UP, mazeWallPaths } from "./pixelArt.ts";
import { POCKET_IDS, adjacent, emptyBlock, findTile, heading, isWalk, loopTile, mazePath, mod, patrolLoop, sameTile, type Tile } from "./maze.ts";

const walkable: Tile[] = [];
MAZE.forEach((row, r) => [...row].forEach((_, c) => { if (isWalk(MAZE, r, c)) walkable.push([r, c]); }));

test("maze rows are one width and fully walled at the border", () => {
  assert.ok(MAZE.every((r) => r.length === MAZE[0]!.length));
  assert.ok([...MAZE[0]!].every((c) => c === "#")); // reef ceiling; the bottom row is open to the sand
  assert.ok(MAZE.every((r) => r[0] === "#" && r[r.length - 1] === "#"));
  assert.ok(findTile(MAZE, "S"));
});

test("every pocket 1-8 has a closed patrol loop of 4 to 8 adjacent corridor tiles", () => {
  for (const p of POCKET_IDS) {
    const loop = patrolLoop(MAZE, p);
    assert.ok(loop.length >= 4 && loop.length <= 8, `pocket ${p} loop length ${loop.length}`);
    loop.forEach((t, i) => {
      assert.ok(isWalk(MAZE, t[0], t[1]));
      assert.ok(adjacent(t, loop[(i + 1) % loop.length]!), `pocket ${p} step ${i}`);
    });
    assert.equal(new Set(loop.map((t) => t.join(","))).size, loop.length);
  }
});

test("patrolLoop is empty for a missing pocket and for the one-row winner pocket", () => {
  assert.deepEqual(patrolLoop(MAZE, "0"), []);
  assert.deepEqual(patrolLoop(MAZE, "9"), []);
});

test("mazePath: adjacent corridor steps, right ends, and the shortest length", () => {
  const start = findTile(MAZE, "S")!;
  for (const to of walkable) {
    const path = mazePath(MAZE, start, to);
    assert.ok(path, `reachable ${to.join(",")}`);
    assert.ok(sameTile(path[0]!, start) && sameTile(path[path.length - 1]!, to));
    path.slice(1).forEach((t, i) => { assert.ok(adjacent(path[i]!, t)); assert.ok(isWalk(MAZE, t[0], t[1])); });
    const back = mazePath(MAZE, to, start)!;
    assert.equal(back.length, path.length);
  }
});

test("mazePath: shortest equals a known Manhattan run on an open row and handles from === to", () => {
  assert.deepEqual(mazePath(MAZE, findTile(MAZE, "S")!, findTile(MAZE, "S")!), [findTile(MAZE, "S")!]);
  const [sr, sc] = findTile(MAZE, "S")!;
  assert.equal(mazePath(MAZE, [sr, sc], [sr - 2, sc])!.length, 3); // S, the tile above it, then the winner pocket
  assert.equal(mazePath(MAZE, [sr, sc], [0, 0]), null); // a wall tile
});

test("mazePath: no shorter path exists (compare with brute-force distances)", () => {
  const s0 = findTile(MAZE, "S")!;
  const dist = new Map<string, number>([[s0.join(","), 0]]);
  const q: Tile[] = [s0];
  for (let i = 0; i < q.length; i++) for (const [dr, dc] of [[0, 1], [1, 0], [0, -1], [-1, 0]]) {
    const n: Tile = [q[i]![0] + dr!, q[i]![1] + dc!];
    if (isWalk(MAZE, n[0], n[1]) && !dist.has(n.join(","))) { dist.set(n.join(","), dist.get(q[i]!.join(","))! + 1); q.push(n); }
  }
  for (const t of walkable) assert.equal(mazePath(MAZE, s0, t)!.length - 1, dist.get(t.join(",")));
});

test("mod is never negative and loopTile/heading never throw for any step, on every loop", () => {
  assert.equal(mod(-1, 6), 5);
  assert.equal(mod(7, 6), 1);
  assert.equal(loopTile([], 3), null);
  assert.equal(heading([], 3), -1);
  for (const p of POCKET_IDS) {
    const loop = patrolLoop(MAZE, p);
    for (let k = -50; k <= 50; k++) {
      assert.ok(loopTile(loop, k));
      assert.ok(heading(loop, k) === 1 || heading(loop, k) === -1);
    }
  }
});

test("the maze has 8 seller pockets and a centre pocket, none sharing tiles, all reachable from the start", () => {
  const seen = new Set<string>();
  for (const p of POCKET_IDS) {
    const loop = patrolLoop(MAZE, p);
    assert.ok(loop.length >= 4, `pocket ${p}`);
    for (const t of loop) { assert.ok(!seen.has(t.join(",")), `pocket ${p} shares ${t}`); seen.add(t.join(",")); assert.equal(MAZE[t[0]]![t[1]], p); }
    assert.ok(mazePath(MAZE, findTile(MAZE, "S")!, loop[0]!), `pocket ${p} reachable`);
  }
  assert.ok(MAZE.join("").split("9").length > 1);
  assert.ok(mazePath(MAZE, findTile(MAZE, "S")!, findTile(MAZE, "9")!));
  assert.equal(MAZE.length, 8);
  assert.equal(MAZE[0]!.length, 21);
});

test("no 4 x 4 block of the maze is all corridor (no big empty areas)", () => {
  assert.equal(emptyBlock(MAZE, 4), null);
  assert.deepEqual(emptyBlock(["....", "....", "....", "...."], 4), [0, 0]);
});

test("every corridor tile is a pellet, a pocket or the start", () => {
  for (const [r, c] of walkable) assert.ok(/[.1-9S]/.test(MAZE[r]![c]!), `tile ${r},${c}`);
});

test("pocket signs stay PiP-safe: no pocket in rows 0-1, and rows 0-2 pockets keep signs left of x 700", () => {
  for (const p of POCKET_IDS) for (const [r, c] of patrolLoop(MAZE, p)) {
    assert.ok(r >= 2, `pocket ${p} tile ${r},${c}`);
    const cx = MAZE_ORIGIN.x + c * MAZE_TILE + MAZE_TILE / 2;
    if (r <= 2) assert.ok(cx + 100 <= 700, `pocket ${p} tile ${r},${c} x ${cx}`);
  }
});

test("support agent sprites are rectangular grids of the planned size", () => {
  for (const [g, w, h] of [[PUFFER, 16, 14], [CHECKER, 10, 12], [REFEREE, 12, 14], [REFEREE_UP, 12, 14]] as const) {
    assert.equal(g.length, h);
    assert.ok(g.every((row) => row.length === w));
  }
});

test("mazeWallPaths builds ridge paths for every colour", () => {
  const w = mazeWallPaths();
  for (const k of ["coralA", "coralB", "rock", "light", "dark"] as const) assert.ok(w[k].length > 0, k);
  assert.ok(!/NaN|undefined/.test(Object.values(w).join("")));
});
