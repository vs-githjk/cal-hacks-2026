// Run with: npm test --prefix web (node --test, no extra dependency).
// #398 item 3: every nav link resolves to a real page, so a stranger never lands on a 404 from the app's own links.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";

const APP = new URL("../app/", import.meta.url);
const read = (rel: string) => readFileSync(new URL(rel, new URL("../", import.meta.url)), "utf8");

/** True when src/app has a page for this path; a [segment] folder matches any one segment. */
function routeExists(path: string): boolean {
  let dir = APP;
  for (const seg of path.split("/").filter(Boolean)) {
    const exact = new URL(`${seg}/`, dir);
    if (existsSync(exact)) {
      dir = exact;
      continue;
    }
    const dynamic = readdirSync(dir, { withFileTypes: true }).find((d) => d.isDirectory() && /^\[[^\].]+\]$/.test(d.name));
    if (!dynamic) return false;
    dir = new URL(`${dynamic.name}/`, dir);
  }
  return existsSync(new URL("page.tsx", dir));
}

const hrefs = (src: string) => [...src.matchAll(/href:\s*"(\/[^"#?]*)"/g)].map((m) => m[1]!);

test("routeExists knows a real page, a dynamic segment and a missing page", () => {
  assert.ok(routeExists("/"));
  assert.ok(routeExists("/seller/seller-a"));
  assert.ok(!routeExists("/build-board"));
});

test("every header and buyer nav link resolves to a page", () => {
  const links = [...hrefs(read("components/shell.tsx")), ...hrefs(read("components/BuyerAppShell.tsx")), ...hrefs(read("app/not-found.tsx"))];
  assert.ok(links.length >= 8);
  for (const h of links) assert.ok(routeExists(h), h);
});

test("the home screen tiles resolve to a page", () => {
  const links = hrefs(read("app/page.tsx"));
  assert.ok(links.length >= 4);
  for (const h of links) assert.ok(routeExists(h), h);
});

test("/seller on its own is a page, not a 404, and the app has its own not-found page", () => {
  assert.ok(routeExists("/seller"));
  assert.ok(existsSync(new URL("not-found.tsx", APP)));
});
