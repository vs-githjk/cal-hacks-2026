import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

// User-facing copy says "the buyer", never a person's name. Comments and internal data keys
// (the pairing user id and the sample need id) are not shown on screen, so they are exempt.
const ROOT = join(process.cwd(), "src");
const INTERNAL_KEY = /DEMO_BUYER|needId|buyerId/;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === "module_bindings" || name === "fixtures") continue;
      walk(p, out);
    } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.ts$/.test(name)) out.push(p);
  }
  return out;
}

test("no on-screen copy names a person (vidyut)", () => {
  const hits: string[] = [];
  for (const f of walk(ROOT)) {
    const src = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ""));
    src.split(/\r?\n/).forEach((line, i) => {
      const code = line.replace(/(^|\s)\/\/.*$/, "$1").replace(/^\s*\*.*$/, "");
      if (/vidyut/i.test(code) && !INTERNAL_KEY.test(code)) hits.push(`${f}:${i + 1}: ${line.trim()}`);
    });
  }
  assert.deepEqual(hits, []);
});

// Bundled JSON under public/ is shown on screen too (the lot wall reads lot.json). Scan its values; keys and
// internal id fields (id, buyer_id, need_id, needId, buyerId, ...) are never displayed, so they are exempt.
const ID_KEY = /^(id|[a-z]+(_id|Id))$/;

function jsonFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) jsonFiles(p, out);
    else if (name.endsWith(".json")) out.push(p);
  }
  return out;
}

function nameHits(v: unknown, path: string, hits: string[]): void {
  if (typeof v === "string") {
    if (/vidyut/i.test(v)) hits.push(`${path}: ${v}`);
  } else if (Array.isArray(v)) v.forEach((x, i) => nameHits(x, `${path}[${i}]`, hits));
  else if (v && typeof v === "object") {
    for (const [k, x] of Object.entries(v)) if (!ID_KEY.test(k)) nameHits(x, `${path}.${k}`, hits);
  }
}

test("no bundled JSON value names a person (vidyut)", () => {
  const hits: string[] = [];
  for (const f of jsonFiles(join(process.cwd(), "public"))) nameHits(JSON.parse(readFileSync(f, "utf8")), f, hits);
  assert.deepEqual(hits, []);
});
