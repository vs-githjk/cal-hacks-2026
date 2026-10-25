import test from "node:test";
import assert from "node:assert/strict";
import { MAZE, mazeWallPaths } from "./pixelArt.ts";
import { adjacent, findTile, heading, isWalk, loopTile, mazePath, mod, patrolLoop, sameTile, type Tile } from "./maze.ts";

const walkable: Tile[] = [];
MAZE.forEach((row, r) => [...row].forEach((_, c) => { if (isWalk(MAZE, r, c)) walkable.push([r, c]); }));

test("maze rows are one width and fully walled at the border", () => {
  assert.ok(MAZE.every((r) => r.length === MAZE[0]!.length));
  assert.ok([...MAZE[0]!].every((c) => c === "#")); // reef ceiling; the bottom row is open to the sand
  assert.ok(MAZE.every((r) => r[0] === "#" && r[r.length - 1] === "#"));
  assert.ok(findTile(MAZE, "S"));
});

test("every pocket 1-5 has a closed patrol loop of 4 to 8 adjacent corridor tiles", () => {
  for (const p of ["1", "2", "3", "4", "5"]) {
    const loop = patrolLoop(MAZE, p);
    assert.ok(loop.length >= 4 && loop.length <= 8, `pocket ${p} loop length ${loop.length}`);
    loop.forEach((t, i) => {
      assert.ok(isWalk(MAZE, t[0], t[1]));
      assert.ok(adjacent(t, loop[(i + 1) % loop.length]!), `pocket ${p} step ${i}`);
    });
    assert.equal(new Set(loop.map((t) => t.join(","))).size, loop.length);
  }
});

test("patrolLoop is empty for a missing pocket", () => assert.deepEqual(patrolLoop(MAZE, "9"), []));

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
  assert.equal(mazePath(MAZE, [sr, sc], [sr, sc + 3])!.length, 4); // S then three open tiles along the bottom corridor
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
  for (const p of ["1", "2", "3", "4", "5"]) {
    const loop = patrolLoop(MAZE, p);
    for (let k = -50; k <= 50; k++) {
      assert.ok(loopTile(loop, k));
      assert.ok(heading(loop, k) === 1 || heading(loop, k) === -1);
    }
  }
});

test("the maze has 4 seller pockets, a centre pocket and a PiP-safe layout", () => {
  for (const p of ["1", "2", "3", "4", "5"]) assert.ok(patrolLoop(MAZE, p).length >= 4, `pocket ${p}`);
  assert.equal(MAZE.length, 5);
  assert.equal(MAZE[0]!.length, 13);
  // the right-hand seller pockets keep fish out of the top-right corner: no fish tile in row 1 at col >= 9
  for (const p of ["1", "2", "3", "4"]) for (const [r, c] of patrolLoop(MAZE, p)) assert.ok(!(r === 1 && c >= 9), `pocket ${p} tile ${r},${c}`);
});

test("mazeWallPaths builds ridge paths for every colour", () => {
  const w = mazeWallPaths();
  for (const k of ["coralA", "coralB", "rock", "light", "dark"] as const) assert.ok(w[k].length > 0, k);
  assert.ok(!/NaN|undefined/.test(Object.values(w).join("")));
});
