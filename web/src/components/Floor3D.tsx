"use client";
// The arena: a bright toy diorama drawn with three.js primitives (no downloads). Every motion comes from a beat of the scene
// (web/src/lib/arenaScene.ts) and the layout for that beat comes from stageAt (arenaLayout.ts). Art direction: web/docs/3d-arena/DESIGN.md,
// "Art direction v2". Rendering is on demand: frames only while something moves, then one final frame.
import { useEffect, useMemo, useRef } from "react";
import type * as THREE from "three";
import { ENTRY_RADIUS, STACK_MAX, TABLE, WINNER_SEAT, looksFor, seatOf, stageAt, type CardState, type Look, type Mark, type Pose, type Seat, type StageState } from "@/lib/arenaLayout";
import type { ArenaScene, Beat } from "@/lib/arenaScene";
import { formatMoney } from "@/lib/money";
import type { Origin } from "@/lib/screens";

type Three = typeof THREE;

export interface Floor3DProps {
  scene: ArenaScene;
  beat: number; // beats applied; when it rises by exactly 1, animate beats[beat-1] over its ms; any other change snaps
  frozen: boolean; // market disconnected: start no tweens and run no frames; when unfrozen, snap to the target
  reducedMotion: boolean; // snap every change
  selected: string | null; // actor key whose nameplate gets the ring
  onPick: (key: string) => void;
  onUnavailable: () => void; // three import failed, renderer threw, or webglcontextlost
  bubbles?: Partial<Record<string, string>>; // ActorKey to speech text, drawn above that actor's nameplate
}

interface Live { scene: ArenaScene; beat: number; frozen: boolean; reducedMotion: boolean; onPick: (key: string) => void; onUnavailable: () => void }
interface Api { sync: () => void }

// ---- art direction -------------------------------------------------------------------------------------------------
const C = {
  fog: 0xf1e3e4, sage: 0xa9c9a4, sageLip: 0x8fb08a, clay: 0xe4a587, cream: 0xf5ebdc, side: 0xe8d6c0, earth: 0xc9a98a,
  buyer: 0xfff8ee, navy: 0x2f3e66, steel: 0x5b7fa6, eye: 0x2b2a33, knock: 0xbdb3a9, paper: 0xfff4e2, wax: 0xc8553d, table: 0xd9c3a5, gold: 0xe9b949,
};
const SUN = 2.6;
const HEMI = 1.0;
const CROWN_ZOOM = 0.12;
const SPOT = 150;
const BUYER_SCALE = 1.1;
const CHEST = 0.78; // prop height above a figure's feet
const PLINTH = 0.2;
const ANCHOR = 2.0; // nameplate anchor above a figure's feet, times its scale
const ENV_REST_Y = TABLE.y + 0.06 + 0.011;
const ENV_PITCH = 0.03;
const VIEW_LOOK: [number, number, number] = [0, 0.4, -0.3];
const VIEW_DIST = 13;
const VIEW_ELEV = (35 * Math.PI) / 180;

// ---- small math ----------------------------------------------------------------------------------------------------
const clamp01 = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t);
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const wrapPi = (a: number) => { const t = (a + Math.PI) % (2 * Math.PI); return (t < 0 ? t + 2 * Math.PI : t) - Math.PI; };
const jitter = (i: number) => (((i * 37) % 11) - 5) * (Math.PI / 180);

/** A figure's drawn state; `vis`, `dim` and `aim` are 0 to 1 so they can tween. */
interface Vis { x: number; y: number; z: number; yaw: number; pitch: number; dim: number; vis: number; aim: number }
const visOf = (p: Pose, aim: number): Vis => ({ x: p.x, y: p.y, z: p.z, yaw: p.yaw, pitch: p.pitch, dim: p.dim ? 1 : 0, vis: p.visible ? 1 : 0, aim });
const lerpVis = (a: Vis, b: Vis, e: number): Vis => ({
  x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e, z: a.z + (b.z - a.z) * e, yaw: a.yaw + wrapPi(b.yaw - a.yaw) * e,
  pitch: a.pitch + (b.pitch - a.pitch) * e, dim: a.dim + (b.dim - a.dim) * e, vis: a.vis + (b.vis - a.vis) * e, aim: a.aim + (b.aim - a.aim) * e,
});
const sameVis = (a: Vis, b: Vis) => (Object.keys(a) as (keyof Vis)[]).every((k) => Math.abs(a[k] - b[k]) < 1e-6);

/** An envelope's drawn transform: Euler order YXZ (yaw, then tip up). */
interface Xf { x: number; y: number; z: number; rx: number; ry: number; vis: number }
const lerpXf = (a: Xf, b: Xf, e: number): Xf => ({ x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e, z: a.z + (b.z - a.z) * e, rx: a.rx + (b.rx - a.rx) * e, ry: a.ry + (b.ry - a.ry) * e, vis: Math.max(a.vis, b.vis) });
const stackXf = (slot: number): Xf => ({ x: 0, y: ENV_REST_Y + slot * ENV_PITCH, z: TABLE.z, rx: 0, ry: jitter(slot), vis: 1 });

/** A number that eases to a goal. dur 0 means it is already there. */
interface Track { v: number; from: number; to: number; t0: number; dur: number }
const track = (v: number): Track => ({ v, from: v, to: v, t0: 0, dur: 0 });
const goTo = (tr: Track, to: number, now: number, dur: number, delay = 0) => { tr.from = tr.v; tr.to = to; tr.t0 = now + delay; tr.dur = dur; if (dur <= 0) tr.v = to; };
const stepTrack = (tr: Track, now: number) => {
  if (tr.dur <= 0) { tr.v = tr.to; return false; }
  const u = clamp01((now - tr.t0) / tr.dur);
  tr.v = tr.from + (tr.to - tr.from) * ease(u);
  return u < 1;
};

type FigKind = "buyer" | "advocate" | "shield" | "referee" | "offer";
interface Tween<T> { from: T; delay: number; dur: number; arc: number; t0: number; u: number }
interface Fig {
  key: string;
  kind: FigKind;
  sig: string;
  group: THREE.Object3D;
  mats: { mat: THREE.MeshStandardMaterial; base: THREE.Color }[]; // dimmed (desaturated) together
  scale: number;
  pad: { pivot: THREE.Group; item: THREE.Object3D } | null;
  vis: Vis;
  to: Vis;
  tier: number;
  aimSign: number;
  tw: Tween<Vis> | null;
}
interface Card { bidId: string; owner: string; index: number; seat: Seat; group: THREE.Group; state: CardState; xf: Xf; tw: Tween<Xf> | null }
interface Leg { t0: number; dur: number; from: THREE.Vector3; to: THREE.Vector3 }
interface Bit { mesh: THREE.Mesh; vx: number; vy: number; vz: number; sx: number; sy: number; t0: number }

// ---- the renderer --------------------------------------------------------------------------------------------------
function build(T: Three, box: HTMLElement, host: HTMLElement, plateEls: Map<string, HTMLDivElement>, live: { current: Live }): { api: Api; dispose: () => void } {
  const undo: (() => void)[] = [];
  const dispose = () => { for (const f of undo.splice(0).reverse()) { try { f(); } catch { /* keep tearing down */ } } };
  try {
    return make();
  } catch (err) {
    dispose();
    throw err;
  }

  function make(): { api: Api; dispose: () => void } {
    const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
    undo.push(() => { renderer.dispose(); renderer.domElement.remove(); });
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = T.PCFSoftShadowMap;
    const canvas = renderer.domElement;
    canvas.className = "absolute inset-0 block h-full w-full";
    host.appendChild(canvas);

    const scene = new T.Scene();
    scene.fog = new T.Fog(C.fog, 14, 30);
    const camera = new T.OrthographicCamera(-7, 7, 4, -4, 0.1, 60);
    const look = new T.Vector3(...VIEW_LOOK);
    camera.position.set(look.x, look.y + VIEW_DIST * Math.sin(VIEW_ELEV), look.z + VIEW_DIST * Math.cos(VIEW_ELEV));
    camera.lookAt(look);

    // Light: warm sun from the upper left, soft sky and ground fill, and a warm spot that only the crown turns on.
    const hemi = new T.HemisphereLight(0xfff6ea, 0xcdb8dc, HEMI);
    const sun = new T.DirectionalLight(0xffe9cc, SUN);
    sun.position.set(-6, 10, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.radius = 4;
    Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8, near: 1, far: 30 });
    sun.shadow.bias = -0.0005;
    sun.shadow.normalBias = 0.03;
    const spot = new T.SpotLight(0xffd98a, 0, 0, 0.32, 0.7, 2);
    spot.position.set(0, 9, 6);
    scene.add(hemi, sun, spot, spot.target);
    undo.push(() => { sun.dispose(); spot.dispose(); });

    // Shared geometry and materials.
    const G = {
      body: new T.CapsuleGeometry(0.34, 0.46, 8, 20),
      head: new T.SphereGeometry(0.3, 32, 20),
      eye: new T.SphereGeometry(0.035, 12, 8),
      foot: new T.CylinderGeometry(0.32, 0.32, 0.04, 24),
      cone: new T.ConeGeometry(0.2, 0.42, 20),
      dome: new T.SphereGeometry(0.31, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2),
      brim: new T.CylinderGeometry(0.4, 0.4, 0.03, 24),
      topHat: new T.CylinderGeometry(0.2, 0.2, 0.34, 20),
      pom: new T.SphereGeometry(0.08, 12, 8),
      beret: new T.SphereGeometry(0.34, 24, 12),
      env: new T.BoxGeometry(0.4, 0.022, 0.27),
      seal: new T.CylinderGeometry(0.04, 0.04, 0.014, 16),
      tablet: new T.BoxGeometry(0.34, 0.24, 0.03),
      hex: new T.CylinderGeometry(0.26, 0.26, 0.04, 6),
      hexRim: new T.CylinderGeometry(0.31, 0.31, 0.03, 6),
      table: new T.BoxGeometry(1.25, 0.12, 0.8),
      plinth: new T.CylinderGeometry(0.5, 0.56, PLINTH, 32),
      plinthRing: new T.TorusGeometry(0.52, 0.045, 10, 40),
      ring: new T.CircleGeometry(0.8, 40),
      bit: new T.PlaneGeometry(0.13, 0.08),
    };
    const std = (color: number, rough = 0.6) => new T.MeshStandardMaterial({ color, roughness: rough, metalness: 0 });
    const M = {
      eye: std(C.eye, 0.3), paper: std(C.paper, 0.7), wax: std(C.wax, 0.5), table: std(C.table, 0.8), gold: std(C.gold, 0.35),
      navy: std(C.navy), cream: std(C.buyer),
      ring: new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55, depthWrite: false, fog: false }),
      bits: [0xf28482, 0xf6bd60, 0x7fb7be, 0xb79ced, 0x90be6d, 0xf7a072, 0x6d9dc5].map((c) => new T.MeshStandardMaterial({ color: c, roughness: 0.7, side: T.DoubleSide })),
    };
    const knock = new T.Color(C.knock);

    // The island: cake layers with a thick side and a darker lip, floating on a cone of earth.
    const layer = (r: number, y0: number, y1: number, top: number, lip: number | null) => {
      const h = y1 - y0;
      const mats = [std(C.side, 0.85), std(top, 0.85), std(C.side, 0.85)];
      const m = new T.Mesh(new T.CylinderGeometry(r, r, h, 96), mats);
      m.position.y = (y0 + y1) / 2;
      m.castShadow = m.receiveShadow = true;
      scene.add(m);
      if (lip !== null) {
        const l = new T.Mesh(new T.CylinderGeometry(r + 0.07, r + 0.07, 0.05, 96), std(lip, 0.85));
        l.position.y = y1 - 0.06;
        l.receiveShadow = true;
        scene.add(l);
      }
    };
    layer(5.6, -0.1, 0, C.sage, C.sageLip);
    layer(3.4, 0, 0.22, C.clay, 0xc98c6f);
    layer(1.5, 0.22, 0.44, C.cream, 0xd9c8b0);
    const earth = new T.Mesh(new T.ConeGeometry(5.6, 2.4, 64), std(C.earth, 0.9));
    earth.rotation.x = Math.PI;
    earth.position.y = -0.1 - 1.2;
    earth.castShadow = true;
    scene.add(earth);

    const mkEnvelope = (): THREE.Group => {
      const g = new T.Group();
      g.rotation.order = "YXZ";
      const paper = new T.Mesh(G.env, M.paper);
      const seal = new T.Mesh(G.seal, M.wax);
      seal.position.y = 0.02;
      paper.castShadow = seal.castShadow = true;
      g.add(paper, seal);
      g.visible = false;
      scene.add(g);
      return g;
    };

    // ---- figures
    const figs = new Map<string, Fig>();
    const tag = (root: THREE.Object3D, k: string) => { root.userData.key = k; root.traverse((o) => { o.userData.key = k; }); };
    const fresh = (): Vis => ({ x: 0, y: 0, z: 0, yaw: 0, pitch: 0, dim: 0, vis: 0, aim: 0 });
    const addFig = (k: string, kind: FigKind, color: number, look: Look | null): Fig => {
      const scale = kind === "buyer" ? BUYER_SCALE : 1;
      const mats: Fig["mats"] = [];
      const mk = (c: number, rough = 0.6) => { const mat = std(c, rough); mats.push({ mat, base: new T.Color(c) }); return mat; };
      const body = mk(color);
      const group = new T.Group();
      group.rotation.order = "YXZ";
      group.scale.setScalar(scale);
      const add = (geo: THREE.BufferGeometry, mat: THREE.Material, x: number, y: number, z: number, shadow = true) => {
        const m = new T.Mesh(geo, mat);
        m.position.set(x, y, z);
        m.castShadow = shadow;
        group.add(m);
        return m;
      };
      add(G.body, body, 0, 0.57, 0);
      add(G.head, body, 0, 1.34, 0);
      add(G.foot, body, 0, 0.02, 0, false);
      for (const sx of [-0.11, 0.11]) add(G.eye, M.eye, sx, 1.38, 0.275, false);
      if (look) {
        const hat = mk(look.hatColor);
        if (look.hat === "party") add(G.cone, hat, 0, 1.78, 0);
        else if (look.hat === "cap") { add(G.dome, hat, 0, 1.55, 0); add(G.brim, hat, 0, 1.56, 0.22).scale.set(0.8, 1, 0.55); }
        else if (look.hat === "top") { add(G.topHat, hat, 0, 1.78, 0); add(G.brim, hat, 0, 1.62, 0).scale.set(0.75, 1, 0.75); }
        else { add(G.dome, hat, 0, 1.56, 0); add(G.pom, hat, 0, 1.9, 0); }
      } else if (kind === "buyer") add(G.beret, M.navy, 0, 1.58, 0).scale.set(0.9, 0.3, 0.9);
      let pad: Fig["pad"] = null;
      if (kind === "advocate" || kind === "shield") {
        const pivot = new T.Group();
        pivot.position.y = CHEST;
        const item = new T.Group();
        item.position.z = 0.46;
        if (kind === "advocate") {
          item.rotation.x = -Math.PI / 6;
          const c = new T.Mesh(G.tablet, M.cream); c.castShadow = true; item.add(c);
          const clip = new T.Mesh(G.pom, M.navy); clip.position.set(0, 0.12, 0.03); item.add(clip);
        } else {
          item.rotation.x = Math.PI / 2;
          const rim = new T.Mesh(G.hexRim, M.navy); rim.castShadow = true;
          const face = new T.Mesh(G.hex, M.cream); face.position.y = 0.02;
          item.add(rim, face);
        }
        pivot.add(item);
        group.add(pivot);
        pad = { pivot, item };
      }
      group.visible = false;
      tag(group, k);
      scene.add(group);
      return { key: k, kind, sig: "", group, mats, scale, pad, vis: fresh(), to: fresh(), tier: 0, aimSign: 1, tw: null };
    };
    for (const [k, kind, c] of [["buyer", "buyer", C.buyer], ["advocate", "advocate", C.navy], ["shield", "shield", C.steel]] as const) figs.set(k, addFig(k, kind, c, null));
    const table = new T.Mesh(G.table, M.table);
    table.position.set(TABLE.x, TABLE.y, TABLE.z);
    table.castShadow = table.receiveShadow = true;
    tag(table, "referee");
    scene.add(table);
    figs.set("referee", { key: "referee", kind: "referee", sig: "referee", group: table, mats: [], scale: 1, pad: null, vis: fresh(), to: fresh(), tier: 2, aimSign: 1, tw: null });

    // The winner's gold plinth, the focus ring, and the confetti.
    const plinth = new T.Group();
    const plinthBase = new T.Mesh(G.plinth, M.gold);
    const plinthRing = new T.Mesh(G.plinthRing, M.gold);
    plinthRing.rotation.x = Math.PI / 2;
    plinthRing.position.y = PLINTH / 2;
    plinthBase.castShadow = plinthRing.castShadow = true;
    plinth.add(plinthBase, plinthRing);
    plinth.position.set(WINNER_SEAT.x, WINNER_SEAT.y, WINNER_SEAT.z);
    plinth.visible = false;
    scene.add(plinth);
    const ringMesh = new T.Mesh(G.ring, M.ring);
    ringMesh.rotation.x = -Math.PI / 2;
    ringMesh.renderOrder = 2;
    scene.add(ringMesh);
    let bits: Bit[] = [];
    const clearBits = () => { for (const b of bits) scene.remove(b.mesh); bits = []; };

    // ---- envelopes: a pool for the stack on the ledger table, and one card per offer
    const pool = Array.from({ length: STACK_MAX }, mkEnvelope);
    const poolDrop: ({ t0: number; dur: number } | null)[] = pool.map(() => null);
    let shown = 0;
    const cards = new Map<string, Card>();

    // ---- rig: zoom, spot, plinth, ring and the focus ring's path
    const tPush = track(0), tSpot = track(0), tPlinth = track(0), tRing = track(1), tSun = track(1);
    const ringAt = new T.Vector3(0, 0.45, 0);
    let legs: Leg[] = [];
    let legsStart = new T.Vector3();
    let plinthFor: string | null = null;
    const crownMid = new T.Vector3(0.4, 1.0, -0.275); // between the buyer and the winner's seat, at chest height

    const v3 = new T.Vector3();
    const pointFor = (k: string, st: StageState, out: THREE.Vector3) => {
      const p = st.actors[k];
      return p ? out.set(p.x, k === "referee" ? 0.455 : p.y + 0.015, p.z) : out.set(0, 0.015, 0);
    };
    const restPoint = (st: StageState, out: THREE.Vector3) => {
      out.set(0, 0, 0);
      const ks = st.rest.length ? st.rest : ["buyer"];
      for (const k of ks) out.add(pointFor(k, st, v3));
      return out.multiplyScalar(1 / ks.length);
    };

    // ---- size and camera
    let W = 0, H = 0;
    const resize = () => {
      W = box.clientWidth;
      H = box.clientHeight;
      if (!W || !H) return;
      renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
      renderer.setSize(W, H, false);
      // Frame the island clear of the page's HUD: the caption card (top left, about 400 x 130) and the controls (bottom 70).
      // Wide boxes push it right and size it by height; phones center it below the card.
      let sc: number, cx: number, cy: number;
      if (W >= 640) { sc = (H - 90) / 9.2; cx = Math.max(W / 2 + 40, 410 + 5.8 * sc); cy = (20 + H - 70) / 2; }
      else { sc = Math.min((W - 8) / 12.4, (H - 210) / 9.2); cx = W / 2; cy = (136 + H - 70) / 2; }
      camera.left = -cx / sc; camera.right = (W - cx) / sc; camera.top = cy / sc; camera.bottom = -(H - cy) / sc;
      camera.updateProjectionMatrix();
    };

    // ---- stepping and drawing
    let broken = false;
    let raf = 0;
    let painted = false;
    const desat = new T.Color();

    const step = (now: number): boolean => {
      let active = false;
      for (const f of figs.values()) {
        const tw = f.tw;
        if (!tw) continue;
        const u = clamp01((now - tw.t0 - tw.delay) / tw.dur);
        tw.u = u;
        f.vis = lerpVis(tw.from, f.to, ease(u));
        f.vis.y += tw.arc * 4 * u * (1 - u);
        if (u >= 1) { f.vis = { ...f.to }; f.tw = null; } else active = true;
      }
      for (const c of cards.values()) {
        const tw = c.tw;
        if (!tw) continue;
        tw.u = clamp01((now - tw.t0 - tw.delay) / tw.dur);
        if (tw.u >= 1) c.tw = null; else active = true;
      }
      poolDrop.forEach((d, i) => { if (d && now - d.t0 >= d.dur) poolDrop[i] = null; else if (d) active = true; });
      for (const tr of [tPush, tSpot, tPlinth, tRing, tSun]) if (stepTrack(tr, now)) active = true;
      if (legs.length) {
        let p = legsStart;
        for (const l of legs) {
          if (now < l.t0) break;
          p = v3.copy(l.from).lerp(l.to, ease(clamp01((now - l.t0) / l.dur)));
        }
        ringAt.copy(p);
        const end = legs[legs.length - 1]!;
        if (now >= end.t0 + end.dur) { ringAt.copy(end.to); legs = []; } else active = true;
      }
      if (bits.length) {
        bits = bits.filter((b) => {
          const t = (now - b.t0) / 1000;
          if (t >= 1.6) { scene.remove(b.mesh); return false; }
          if (t < 0) return true;
          b.mesh.position.set(WINNER_SEAT.x + b.vx * t, 2.1 + b.vy * t - 4.5 * t * t, WINNER_SEAT.z + b.vz * t);
          b.mesh.rotation.set(b.sx * t, b.sy * t, 0);
          return true;
        });
        if (bits.length) active = true;
      }
      return active;
    };

    const cardTarget = (c: Card): Xf => {
      const f = figs.get(c.owner);
      switch (c.state) {
        case "held": {
          const v = f?.vis ?? fresh();
          return { x: v.x + Math.sin(v.yaw) * 0.6, y: v.y + 0.9, z: v.z + Math.cos(v.yaw) * 0.6, rx: Math.PI / 2, ry: 0, vis: 1 };
        }
        case "dropped": { // flat at the seller's feet, a step toward the center
          const t = f?.to ?? fresh();
          return { x: t.x + Math.sin(t.yaw) * 0.35, y: t.y + 0.012, z: t.z + Math.cos(t.yaw) * 0.35, rx: 0, ry: t.yaw, vis: 1 };
        }
        case "lifted": return { x: TABLE.x, y: 1.3, z: TABLE.z, rx: 1.1, ry: 0, vis: 1 };
        case "stack": return { ...stackXf(0), vis: 0 };
        default: return { ...c.xf, vis: 0 };
      }
    };

    const draw = (now: number) => {
      for (const f of figs.values()) {
        if (f.kind === "referee") continue;
        const v = f.vis;
        f.group.visible = v.vis > 0.001;
        const lift = f.key === plinthFor ? PLINTH * tPlinth.v : 0;
        f.group.position.set(v.x, v.y + lift, v.z);
        f.group.rotation.set(Math.max(0, v.pitch), v.yaw, 0);
        f.group.scale.set(f.scale, f.scale * (1 - 0.18 * clamp01((v.pitch - 0.14) / 0.07)), f.scale); // knocked figures sit down
        for (const m of f.mats) m.mat.color.copy(desat.copy(m.base).lerp(knock, v.dim));
        if (f.pad) {
          const shield = f.kind === "shield";
          f.pad.pivot.rotation.y = f.aimSign * v.aim * ((shield ? 15 : 20) * Math.PI) / 180;
          f.pad.pivot.position.y = CHEST + v.aim * (shield ? 0.1 : 0.08);
          if (!shield) f.pad.item.rotation.x = -(Math.PI / 6 + v.aim * 0.44);
        }
      }
      for (const c of cards.values()) {
        let xf = cardTarget(c);
        if (c.tw) {
          xf = lerpXf(c.tw.from, xf, ease(c.tw.u));
          xf.y += c.tw.arc * 4 * c.tw.u * (1 - c.tw.u);
        }
        c.xf = xf;
        c.group.visible = xf.vis > 0.001;
        c.group.position.set(xf.x, xf.y, xf.z);
        c.group.rotation.set(xf.rx, xf.ry, 0);
      }
      pool.forEach((g, i) => {
        const d = poolDrop[i];
        const waiting = !!d && now < d.t0;
        g.visible = i < shown && !waiting;
        const fall = d && !waiting ? 1.2 * (1 - clamp01((now - d.t0) / d.dur) ** 2) : 0;
        const s = stackXf(i);
        g.position.set(s.x, s.y + fall, s.z);
        g.rotation.set(0, s.ry, 0);
      });
      plinth.visible = tPlinth.v > 0.01;
      plinth.scale.y = Math.max(0.01, tPlinth.v);
      plinth.position.y = WINNER_SEAT.y + (PLINTH / 2) * tPlinth.v;
      ringMesh.visible = tRing.v > 0.02;
      M.ring.opacity = 0.55 * tRing.v;
      ringMesh.position.copy(ringAt);
      sun.intensity = SUN * (0.65 + 0.35 * tSun.v);
      spot.intensity = SPOT * tSpot.v;
      spot.target.position.copy(crownMid);
      spot.target.updateMatrixWorld();
      camera.zoom = 1 + CROWN_ZOOM * tPush.v;
      camera.updateProjectionMatrix();
      camera.updateMatrixWorld();
    };

    // Nameplates (a speech bubble rides inside its plate's box, above the pill): HTML over the canvas, moved by writing style.transform.
    // No React state per frame. Priority (data-prio): the winner or a speaker 0, whoever the light is on 1, the rest 2. Each box takes the
    // free spot nearest its default, preferring to be nudged down; with none free it takes the least overlap. Boxes stay inside the container
    // minus the HUD zones (top left card, bottom controls).
    const layoutPlates = () => {
      if (!W || !H) return;
      const items: { el: HTMLDivElement; w: number; h: number; px: number; py: number; vis: number; prio: number }[] = [];
      for (const [k, el] of plateEls) {
        const f = figs.get(k);
        if (!f || f.vis.vis < 0.02) { el.style.visibility = "hidden"; continue; }
        const refe = f.kind === "referee";
        v3.set(f.vis.x, f.vis.y + (refe ? 0.4 : ANCHOR * f.scale), f.vis.z + (refe ? 0.2 : 0)).project(camera);
        items.push({ el, w: el.offsetWidth, h: el.offsetHeight, px: ((v3.x + 1) / 2) * W, py: ((1 - v3.y) / 2) * H, vis: f.vis.vis, prio: Number(el.dataset.prio ?? 2) });
      }
      items.sort((p, q) => p.prio - q.prio || p.px - q.px);
      const placed: { x: number; y: number; w: number; h: number }[] = [];
      for (const it of items) {
        const x0 = Math.max(4, Math.min(W - it.w - 4, it.px - it.w / 2));
        const step = 22;
        const home = it.py - it.h + 4;
        const ok = (x: number, y: number) => y >= 4 && y + it.h <= H - 70 && !(x < 0.4 * W && y < 140 && W >= 640); // page overlays
        const over = (x: number, y: number) => placed.reduce((n, r) => n + Math.max(0, Math.min(x + it.w, r.x + r.w) - Math.max(x, r.x) - 4) * Math.max(0, Math.min(y + it.h, r.y + r.h) - Math.max(y, r.y) - 4), 0);
        const tries: { x: number; y: number; c: number }[] = [];
        for (const dx of [0, -(it.w / 2 + 2), it.w / 2 + 2, -(it.w + 2), it.w + 2]) {
          const x = Math.max(4, Math.min(W - it.w - 4, x0 + dx));
          for (let k = -4; k <= 14; k++) tries.push({ x, y: home + k * step, c: (k > 0 ? k : -k * 1.6) * step + Math.abs(dx) * 0.9 });
        }
        tries.sort((m, n) => m.c - n.c);
        const legal = tries.filter((t) => ok(t.x, t.y));
        let best = legal.find((t) => over(t.x, t.y) === 0);
        if (!best) best = legal.sort((m, n) => over(m.x, m.y) - over(n.x, n.y) || m.c - n.c)[0];
        if (!best) best = { x: x0, y: Math.max(4, Math.min(H - 70 - it.h, home)), c: 0 };
        placed.push({ x: best.x, y: best.y, w: it.w, h: it.h });
        it.el.style.transform = `translate3d(${Math.round(best.x)}px, ${Math.round(best.y)}px, 0)`;
        it.el.style.opacity = String(it.vis);
        it.el.style.visibility = "visible";
      }
    };

    const renderNow = (now = performance.now()) => {
      if (broken || !W || !H) return;
      try {
        draw(now);
        renderer.render(scene, camera);
        layoutPlates();
      } catch {
        broken = true;
        live.current.onUnavailable();
      }
    };
    const frame = () => {
      raf = 0;
      if (broken || live.current.frozen) return;
      const now = performance.now();
      const active = step(now);
      renderNow(now);
      if (active) raf = requestAnimationFrame(frame);
    };
    const kick = () => { if (!raf && !broken && !live.current.frozen && W && H) raf = requestAnimationFrame(frame); };

    // ---- applying a target
    const offerSig = (s: ArenaScene) => s.offers.map((o) => `${o.key}:${o.sellerId}`).join("|");
    const ensureOffers = (s: ArenaScene) => {
      const looks = looksFor(s.offers);
      const sigOf = (k: string) => { const l = looks[k]!; return `${l.color}:${l.hat}:${l.hatColor}`; };
      for (const [k, f] of figs) {
        if (f.kind !== "offer") continue;
        if (looks[k] && f.sig === sigOf(k)) continue;
        scene.remove(f.group);
        f.mats.forEach((m) => m.mat.dispose());
        figs.delete(k);
      }
      for (const [id, c] of cards) {
        if (s.offers.some((o) => o.bidId === id)) continue;
        scene.remove(c.group);
        cards.delete(id);
      }
      s.offers.forEach((o, i) => {
        if (!figs.has(o.key)) { const f = addFig(o.key, "offer", looks[o.key]!.color, looks[o.key]!); f.sig = sigOf(o.key); figs.set(o.key, f); }
        let c = cards.get(o.bidId);
        if (!c) {
          c = { bidId: o.bidId, owner: o.key, index: i, seat: seatOf(s.offers.length, i), group: mkEnvelope(), state: "hidden", xf: { x: 0, y: 0, z: 0, rx: 0, ry: 0, vis: 0 }, tw: null };
          cards.set(o.bidId, c);
        }
        c.index = i;
        c.owner = o.key;
        c.seat = seatOf(s.offers.length, i);
      });
    };
    const targetOf = (f: Fig, st: StageState): Vis => {
      const p = st.actors[f.key]!;
      const at = f.kind === "shield" ? st.aim.shield : f.kind === "advocate" ? st.aim.advocate : null;
      const q = at ? st.actors[at] : undefined;
      if (q) f.aimSign = (q.x - p.x) * Math.cos(p.yaw) - (q.z - p.z) * Math.sin(p.yaw) >= 0 ? 1 : -1;
      return visOf(p, q ? 1 : 0);
    };

    const snap = (st: StageState) => {
      for (const f of figs.values()) { f.tw = null; f.to = targetOf(f, st); f.vis = { ...f.to }; f.tier = st.actors[f.key]!.tier; }
      for (const c of cards.values()) { c.state = st.cards[c.bidId] ?? "hidden"; c.tw = null; }
      shown = st.stackCount;
      poolDrop.fill(null);
      clearBits();
      legs = [];
      restPoint(st, ringAt);
      const crown = st.crown;
      plinthFor = crown ? st.rest[0] ?? null : null;
      goTo(tPush, crown ? 1 : 0, 0, 0);
      goTo(tSpot, crown ? 1 : 0, 0, 0);
      goTo(tPlinth, crown ? 1 : 0, 0, 0);
      goTo(tRing, crown ? 0 : 1, 0, 0);
      goTo(tSun, st.lightOn, 0, 0);
    };

    let seed = 7;
    const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };

    const startBeat = (b: Beat, st: StageState, now: number) => {
      const ms = Math.max(1, b.ms);
      const arriving = [...figs.values()].filter((f) => f.vis.vis < 0.5 && f.kind === "offer" && st.actors[f.key]!.visible).length;
      let hop = 0, arrive = 0;
      const pts = b.focus.map((k) => pointFor(k, st, new T.Vector3()));
      const rest = restPoint(st, new T.Vector3());
      if (!pts.length || pts[pts.length - 1]!.distanceTo(rest) > 1e-6) pts.push(rest);
      const slot = ms / pts.length;
      for (const f of figs.values()) {
        const to = targetOf(f, st);
        const pose = st.actors[f.key]!;
        const from = { ...f.vis };
        f.to = to;
        if (sameVis(from, to)) { f.tw = null; f.tier = pose.tier; continue; }
        let delay = 0, dur = 450, arc = 0, start = from;
        const fi = (b.focus as string[]).indexOf(f.key);
        if (from.vis < 0.5 && to.vis >= 0.5) {
          // walks in from the edge of the island
          const k = ENTRY_RADIUS / (Math.hypot(to.x, to.z) || 1);
          start = { ...to, x: to.x * k, z: to.z * k, y: 0, pitch: 0, dim: 0, vis: 0 };
          delay = 80 * arrive++;
          dur = Math.min(1600, Math.max(400, ms - 80 * (arriving - 1)));
        } else if (pose.tier !== f.tier) {
          arc = 0.5; dur = 500; delay = (b.kind === "crown" ? 150 : 0) + 80 * hop++;
        } else if (fi >= 0 && (b.kind === "gate" || b.kind === "advocate")) {
          delay = fi * slot + 120; dur = 600;
        }
        dur = Math.min(dur, Math.max(200, ms - delay));
        f.tw = { from: start, delay, dur, arc, t0: now, u: 0 };
        f.tier = pose.tier;
      }
      for (const c of cards.values()) {
        const next = st.cards[c.bidId] ?? "hidden";
        if (next === c.state) continue;
        const owner = figs.get(c.owner);
        const from: Xf = c.state === "stack" ? stackXf(Math.max(0, shown - 1 - c.index)) : { ...c.xf };
        const t = owner?.tw;
        c.state = next;
        c.tw = { from, delay: t?.delay ?? 0, dur: Math.min(t?.dur ?? 450, 800), arc: from.vis && next === "held" ? 0.6 : next === "lifted" ? 0.3 : 0, t0: now, u: 0 };
      }
      shown = st.stackCount; // the offers' own envelopes cover the slots they left
      legs = [];
      legsStart = ringAt.clone();
      let prev = legsStart;
      pts.forEach((p, i) => {
        legs.push({ t0: now + i * slot, dur: Math.min(350, slot), from: prev, to: p });
        prev = p;
      });
      const crown = st.crown;
      plinthFor = crown ? st.rest[0] ?? null : null;
      goTo(tPush, crown ? 1 : 0, now, crown ? 1200 : 0);
      goTo(tSpot, crown ? 1 : 0, now, crown ? 1200 : 0);
      goTo(tPlinth, crown ? 1 : 0, now, crown ? 700 : 0, crown ? 350 : 0);
      goTo(tRing, crown ? 0 : 1, now, 350);
      goTo(tSun, st.lightOn, now, 350);
      if (crown) {
        // one confetti burst, then gone
        clearBits();
        for (let i = 0; i < 60; i++) {
          const mesh = new T.Mesh(G.bit, M.bits[i % M.bits.length]!);
          mesh.castShadow = true;
          scene.add(mesh);
          bits.push({ mesh, vx: (rnd() - 0.5) * 5, vy: 3 + rnd() * 3, vz: (rnd() - 0.3) * 3, sx: (rnd() - 0.5) * 14, sy: (rnd() - 0.5) * 14, t0: now + 500 });
          mesh.position.set(WINNER_SEAT.x, -10, WINNER_SEAT.z);
        }
      }
    };

    let prev: { roundId: string | null; beat: number; phase: string; offers: string; sig: string } | null = null;
    let needSnap = true;
    const sync = () => {
      if (broken) return;
      const L = live.current;
      if (L.frozen) {
        // Nothing moves while the market is away: stop the loop, keep the last frame. The first paint still happens once.
        if (raf) { cancelAnimationFrame(raf); raf = 0; }
        for (const f of figs.values()) f.tw = null;
        for (const c of cards.values()) c.tw = null;
        if (painted) { needSnap = true; return; }
      }
      const now = performance.now();
      const s = L.scene;
      const b = Math.min(Math.max(0, Math.trunc(L.beat) || 0), s.beats.length);
      const st = stageAt(s, b);
      const offers = offerSig(s);
      ensureOffers(s);
      const sig = JSON.stringify(st);
      const same = !!prev && prev.roundId === s.roundId && prev.offers === offers;
      let mode: "snap" | "beat" | "drop" | "none" = "snap";
      if (!painted || needSnap || L.frozen || L.reducedMotion || !same || !prev) mode = "snap";
      else if (sig === prev.sig) mode = "none";
      else if (s.phase === "closed" && prev.phase === "closed" && b === prev.beat + 1 && s.beats[b - 1]) mode = "beat";
      else if (s.phase === "open" && prev.phase === "open" && b === prev.beat && st.stackCount > shown) mode = "drop";
      if (mode === "snap") snap(st);
      else if (mode === "beat") startBeat(s.beats[b - 1]!, st, now);
      else if (mode === "drop") {
        for (let i = shown; i < st.stackCount; i++) poolDrop[i] = { t0: now + 80 * (i - shown), dur: 450 };
        shown = st.stackCount;
      }
      prev = { roundId: s.roundId, beat: b, phase: s.phase, offers, sig };
      needSnap = false;
      if (L.frozen) { painted = true; renderNow(now); return; }
      painted = true;
      kick(); // even when nothing tweens, one frame places the nameplates React just committed
    };

    // ---- input
    const ray = new T.Raycaster();
    const ndc = new T.Vector2();
    const pick = (ev: PointerEvent): string | null => {
      const r = canvas.getBoundingClientRect();
      if (!r.width || !r.height) return null;
      ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      const roots = [...figs.values()].filter((f) => f.group.visible).map((f) => f.group);
      const hit = ray.intersectObjects(roots, true)[0];
      const k = hit?.object.userData.key;
      return typeof k === "string" ? k : null;
    };
    const onDown = (ev: PointerEvent) => { const k = pick(ev); if (k) live.current.onPick(k); };
    const onMove = (ev: PointerEvent) => { canvas.style.cursor = pick(ev) ? "pointer" : ""; };
    const onLost = () => { broken = true; if (raf) { cancelAnimationFrame(raf); raf = 0; } live.current.onUnavailable(); };
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("webglcontextlost", onLost);
    undo.push(() => {
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("webglcontextlost", onLost);
    });

    const ro = new ResizeObserver(() => {
      resize();
      if (!W || !H) return; // zero size: wait for a real one
      if (painted) renderNow(); // setSize clears the canvas; repaint the same frame
      kick();
    });
    ro.observe(box);
    undo.push(() => ro.disconnect());
    undo.push(() => { if (raf) cancelAnimationFrame(raf); raf = 0; });
    resize();

    // Teardown: every geometry and material in the scene, plus the shared ones, then the renderer (pushed first, so it runs last).
    undo.push(() => {
      const geos = new Set<THREE.BufferGeometry>(Object.values(G));
      const mats = new Set<THREE.Material>([M.eye, M.paper, M.wax, M.table, M.gold, M.navy, M.cream, M.ring, ...M.bits]);
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.geometry) geos.add(m.geometry);
        if (Array.isArray(m.material)) m.material.forEach((x) => mats.add(x)); else if (m.material) mats.add(m.material);
      });
      geos.forEach((g) => g.dispose());
      mats.forEach((x) => x.dispose());
      scene.clear();
    });

    return { api: { sync }, dispose };
  }
}

// ---- the component -------------------------------------------------------------------------------------------------
const FIXED: { key: string; name: string }[] = [
  { key: "buyer", name: "Buyer agent" },
  { key: "advocate", name: "Advocate" },
  { key: "shield", name: "Bazaar Shield" },
  { key: "referee", name: "Referee" },
];
const WORD: Partial<Record<Mark, string>> = { blocked: "Blocked", vetoed: "Vetoed", refused: "Refused", winner: "Winner" };

interface Plate { key: string; name: string; origin: Origin; price: string | null; word: string | null; struck: boolean; prio: number; say?: string }

function Chip({ origin }: { origin: Origin }) {
  const cls = origin === "LIVE" ? "bg-[#2B2A33] text-white" : origin === "MIRROR" ? "border border-[#2B2A33]/60" : "border border-dashed border-[#2B2A33]/40 text-[#2B2A33]/70";
  return <span className={`rounded-full px-1.5 font-mono text-[10px] font-semibold leading-[16px] tracking-[0.05em] ${cls}`}>{origin}</span>;
}

/** The speech bubble: pops in over 180 ms (not under reduced motion), and swaps when the text changes. */
function Bubble({ text, reducedMotion }: { text: string; reducedMotion: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (reducedMotion || !el.current || typeof el.current.animate !== "function") return;
    el.current.animate([{ opacity: 0, transform: "scale(0.9)" }, { opacity: 1, transform: "scale(1)" }], { duration: 180, easing: "ease-out" });
  }, [text, reducedMotion]);
  return (
    <div ref={el} aria-hidden="true" className="pointer-events-none relative origin-bottom pb-2">
      <div className="line-clamp-2 max-w-[26ch] rounded-2xl bg-white px-3 py-1.5 text-[13px] font-medium leading-[17px] text-[#2B2A33] shadow-[0_4px_14px_rgba(60,40,30,0.18)]">{text}</div>
      <span className="absolute bottom-[3px] left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 rounded-[2px] bg-white shadow-[2px_2px_4px_rgba(60,40,30,0.08)]" />
    </div>
  );
}

export function Floor3D({ scene, beat, frozen, reducedMotion, selected, onPick, onUnavailable, bubbles }: Floor3DProps) {
  const box = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const plateEls = useRef(new Map<string, HTMLDivElement>());
  const live = useRef<Live>({ scene, beat, frozen, reducedMotion, onPick, onUnavailable });
  const api = useRef<Api | null>(null);

  // The renderer reads the newest props from this ref, so state that arrives before three has loaded still applies.
  useEffect(() => { live.current = { scene, beat, frozen, reducedMotion, onPick, onUnavailable }; });
  useEffect(() => { api.current?.sync(); }, [scene, beat, frozen, reducedMotion]);

  useEffect(() => {
    const b = box.current, h = host.current;
    if (!b || !h) return;
    let disposed = false;
    let dispose = () => {};
    import("three").then(
      (T) => {
        if (disposed) return;
        try {
          const built = build(T, b, h, plateEls.current, live);
          dispose = built.dispose;
          api.current = built.api;
          built.api.sync();
        } catch {
          live.current.onUnavailable();
        }
      },
      () => { if (!disposed) live.current.onUnavailable(); },
    );
    return () => {
      disposed = true;
      api.current = null;
      dispose();
    };
  }, []);

  const stage = useMemo(() => stageAt(scene, beat), [scene, beat]);
  const plates = useMemo<Plate[]>(() => {
    const out: Plate[] = [];
    const focus = new Set<string>(stage.focus);
    for (const f of FIXED) {
      const fixedOnly = f.key !== "buyer";
      const say = bubbles?.[f.key] || undefined;
      if (fixedOnly && !say && !focus.has(f.key) && selected !== f.key) continue; // the cast steps up only while it is in focus, selected or speaking
      out.push({ ...f, origin: "SIM", price: null, word: null, struck: false, prio: say ? 0 : focus.has(f.key) || selected === f.key ? 1 : 2, say });
    }
    for (const o of scene.offers) {
      if (!stage.actors[o.key]?.visible) continue;
      const mark = stage.marks[o.bidId] ?? "none";
      const hard = mark === "blocked" || mark === "vetoed" || mark === "refused";
      out.push({ key: o.key, name: o.name, origin: o.origin, price: hard ? null : formatMoney(o.landed), word: WORD[mark] ?? null, struck: hard, prio: mark === "winner" || bubbles?.[o.key] ? 0 : focus.has(o.key) || selected === o.key ? 1 : 2, say: bubbles?.[o.key] || undefined });
    }
    return out;
  }, [scene, stage, selected, bubbles]);
  const setEl = (key: string) => (el: HTMLDivElement | null) => { if (el) plateEls.current.set(key, el); else plateEls.current.delete(key); };
  const HIDDEN = { transform: "translate3d(-9999px, 0, 0)", visibility: "hidden" } as const;

  return (
    <div
      ref={box}
      className="relative h-[420px] w-full overflow-hidden rounded-[20px] sm:h-[560px]"
      style={{ background: "linear-gradient(180deg, #F8EBDD 0%, #EEDCEB 100%)" }}
    >
      <div ref={host} className="absolute inset-0" aria-hidden="true" />
      {plates.map((p) => (
        <div key={p.key} data-prio={p.prio} ref={setEl(p.key)} className="pointer-events-none absolute left-0 top-0 z-10 flex flex-col items-center will-change-transform" style={HIDDEN}>
          {p.say && <Bubble key={p.say} text={p.say} reducedMotion={reducedMotion} />}
          <button
            type="button"
            onClick={() => onPick(p.key)}
            aria-pressed={selected === p.key}
            className="pointer-events-auto flex min-h-[44px] items-center p-1 text-left"
          >
            <span
              className={`flex flex-col items-start whitespace-nowrap rounded-full bg-white/[0.94] px-2.5 py-[3px] text-[12px] font-semibold leading-[16px] text-[#2B2A33] shadow-[0_2px_8px_rgba(60,40,30,0.15)] ${selected === p.key ? "ring-1 ring-[#2B2A33]" : ""} ${p.struck ? "opacity-60" : ""}`}
            >
              <span className="flex items-center gap-1.5">
                <span className={`max-w-[10rem] truncate ${p.struck ? "line-through" : ""}`}>{p.name}</span>
                <Chip origin={p.origin} />
              </span>
              {(p.price || p.word) && (
                <span className="flex items-center gap-1.5 text-[11px] font-medium tabular-nums text-[#2B2A33]/75">
                  {p.price && <span>{p.price}</span>}
                  {p.word && <span className={p.word === "Winner" ? "font-bold text-[#2B2A33]" : ""}>{p.word}</span>}
                </span>
              )}
            </span>
          </button>
        </div>
      ))}
    </div>
  );
}

export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}
