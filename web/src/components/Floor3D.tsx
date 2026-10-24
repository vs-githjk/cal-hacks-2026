"use client";
// The arena: a bright toy diorama drawn with three.js primitives (no downloads). Every motion comes from a beat of the scene
// (web/src/lib/arenaScene.ts) and the layout for that beat comes from stageAt (arenaLayout.ts). Art direction: web/docs/3d-arena/DESIGN.md,
// "Art direction v2". Rendering is on demand: frames only while something moves, then one final frame.
import { useEffect, useMemo, useRef } from "react";
import type * as THREE from "three";
import { ANON_MAX, ENTRY_RADIUS, SELLER_COLORS, STACK_MAX, TABLE, WINNER_SEAT, looksFor, seatOf, stageAt, type CardState, type Look, type Mark, type Pose, type Seat, type StageState } from "@/lib/arenaLayout";
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
// A sunlit limestone plaza with gold trim, planters and banners; matte clay figures in neutral tones, the buyer in teal.
const C = {
  fog: 0xf3ebdf, floor: 0xece3d4, t1: 0xf1e9dc, t2: 0xf6f0e6, side: 0xe0d3bf, wall: 0xe6dbc9, wallTop: 0xf1e9dd,
  gold: 0xc9a45c, charcoal: 0x3a3a3d, leaf1: 0x5f8c57, leaf2: 0x7aa66b, leaf3: 0x4c7746, banner: 0xe8d9bf,
  buyer: 0x4f7f7c, advocate: 0xe9dfd0, eye: 0x1f1f22, knock: 0xb9b3ab, paper: 0xfbf4e6, wax: 0xb8863b, table: 0xe3d6c2,
  stone: 0xe4d9c8, anon: 0x9b958e,
};
const SUN = 2.4;
const HEMI = 1.15;
const CROWN_ZOOM = 0.06;
const SPOT = 90;
const BUYER_SCALE = 1.4;
const FIG_SCALE = 1.28;
const CHEST = 0.86; // prop height above a figure's feet
const PLINTH = 0.2;
const ANCHOR = 1.82; // nameplate anchor above a figure's feet, times its scale
const ENV_REST_Y = TABLE.y + 0.06 + 0.011;
const ENV_PITCH = 0.03;
const VIEW_LOOK: [number, number, number] = [0, 0.6, -1.5];
const VIEW_ELEV = (40 * Math.PI) / 180;
const VFOV = 30;

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

type FigKind = "buyer" | "advocate" | "shield" | "referee" | "offer" | "anon";
type ArmPose = "rest" | "hold" | "wave" | "droop";
interface Tween<T> { from: T; delay: number; dur: number; arc: number; t0: number; u: number }
interface Fig {
  key: string;
  kind: FigKind;
  sig: string;
  group: THREE.Object3D;
  mats: { mat: THREE.MeshStandardMaterial; base: THREE.Color }[]; // dimmed (desaturated) together
  scale: number;
  pad: { pivot: THREE.Group; item: THREE.Object3D } | null;
  arms: { l: THREE.Group; r: THREE.Group } | null;
  arm: ArmPose;
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

    renderer.toneMapping = T.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    const scene = new T.Scene();
    scene.fog = new T.Fog(C.fog, 20, 42);
    const camera = new T.PerspectiveCamera(VFOV, 16 / 9, 0.5, 80);
    const look = new T.Vector3(...VIEW_LOOK);
    let viewDist = 16;
    const placeCamera = () => {
      camera.position.set(look.x, look.y + viewDist * Math.sin(VIEW_ELEV), look.z + viewDist * Math.cos(VIEW_ELEV));
      camera.lookAt(look);
    };
    placeCamera();

    // Light: a warm low sun from the upper left (long soft shadows), a bright sky fill, and a warm spot that only the crown turns on.
    const hemi = new T.HemisphereLight(0xfff8ef, 0xd9cbb8, HEMI);
    const sun = new T.DirectionalLight(0xfff0dc, SUN);
    sun.position.set(-7, 11, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -9, right: 9, top: 9, bottom: -9, near: 1, far: 34 });
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.025;
    const spot = new T.SpotLight(0xffe2a8, 0, 0, 0.3, 0.7, 2);
    spot.position.set(0, 10, 6);
    scene.add(hemi, sun, spot, spot.target);
    undo.push(() => { sun.dispose(); spot.dispose(); });

    // Shared geometry and materials.
    const G = {
      torso: new T.CapsuleGeometry(0.22, 0.3, 8, 20),
      head: new T.SphereGeometry(0.29, 32, 22),
      eye: new T.SphereGeometry(0.038, 12, 10),
      leg: new T.CapsuleGeometry(0.095, 0.3, 6, 12),
      arm: new T.CapsuleGeometry(0.072, 0.32, 6, 12),
      dome: new T.SphereGeometry(0.3, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2),
      brim: new T.CylinderGeometry(0.3, 0.3, 0.025, 24),
      bun: new T.SphereGeometry(0.1, 14, 10),
      pack: new T.BoxGeometry(0.34, 0.36, 0.16),
      satchel: new T.BoxGeometry(0.22, 0.18, 0.08),
      strap: new T.TorusGeometry(0.3, 0.018, 6, 24),
      env: new T.BoxGeometry(0.42, 0.022, 0.29),
      seal: new T.CylinderGeometry(0.045, 0.045, 0.016, 16),
      tablet: new T.BoxGeometry(0.3, 0.38, 0.03),
      paperSheet: new T.BoxGeometry(0.25, 0.3, 0.01),
      table: new T.BoxGeometry(1.1, 0.16, 0.7),
      plinth: new T.CylinderGeometry(0.5, 0.56, PLINTH, 32),
      plinthRing: new T.TorusGeometry(0.52, 0.045, 10, 40),
      ring: new T.CircleGeometry(0.75, 40),
      bit: new T.PlaneGeometry(0.13, 0.08),
    };
    const std = (color: number, rough = 0.7, metal = 0) => new T.MeshStandardMaterial({ color, roughness: rough, metalness: metal });
    const M = {
      eye: std(C.eye, 0.35), paper: std(C.paper, 0.75), wax: std(C.wax, 0.45, 0.3), table: std(C.table, 0.85), gold: std(C.gold, 0.32, 0.65),
      charcoal: std(C.charcoal, 0.6), cream: std(C.advocate),
      ring: new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.5, depthWrite: false, fog: false }),
      bits: [0xc9a45c, 0xf6f0e6, 0x4f7f7c, 0xe3b9a0, 0x8a9a7b, 0x3a3a3d].map((c) => new T.MeshStandardMaterial({ color: c, roughness: 0.6, side: T.DoubleSide })),
    };
    const knock = new T.Color(C.knock);

    // ---- the plaza: limestone floor and steps with gold trim, a low stone wall, planters, banners and an arch
    const add = (m: THREE.Mesh, cast = true, receive = true) => { m.castShadow = cast; m.receiveShadow = receive; scene.add(m); return m; };
    const disc = (r: number, y0: number, y1: number, top: number) => {
      const m = add(new T.Mesh(new T.CylinderGeometry(r, r, y1 - y0, 128), [std(C.side, 0.9), std(top, 0.92), std(C.side, 0.9)]));
      m.position.y = (y0 + y1) / 2;
      return m;
    };
    const trim = (r: number, y: number, tube = 0.035) => {
      const t = add(new T.Mesh(new T.TorusGeometry(r, tube, 8, 160), M.gold), false, true);
      t.rotation.x = Math.PI / 2;
      t.position.y = y;
    };
    disc(9.5, -0.3, 0, C.floor);
    trim(4.05, 0.004, 0.025);
    disc(3.4, 0, 0.22, C.t1);
    trim(3.4, 0.22);
    disc(1.5, 0.22, 0.44, C.t2);
    trim(1.5, 0.44);
    // Paving: faint radial joints on the floor ring, drawn as thin lines just above the stone.
    const joints = new T.BufferGeometry().setFromPoints(
      Array.from({ length: 48 }, (_, i) => { const a = (i / 48) * Math.PI * 2; return [new T.Vector3(Math.sin(a) * 4.1, 0.003, Math.cos(a) * 4.1), new T.Vector3(Math.sin(a) * 7.6, 0.003, Math.cos(a) * 7.6)]; }).flat(),
    );
    scene.add(new T.LineSegments(joints, new T.LineBasicMaterial({ color: 0xd8ccb9, transparent: true, opacity: 0.6 })));

    const wallMat = std(C.wall, 0.92), capMat = std(C.wallTop, 0.9), potMat = std(0xe9dfcf, 0.9), soilMat = std(0x5e4a3a, 1);
    const leafMats = [std(C.leaf1, 0.75), std(C.leaf2, 0.75), std(C.leaf3, 0.75)];
    const blockGeo = new T.BoxGeometry(1, 0.62, 0.7), capGeo = new T.BoxGeometry(1.06, 0.08, 0.78);
    const leafGeo = new T.SphereGeometry(0.22, 12, 8);
    const plant = (x: number, z: number, y: number, s = 1) => {
      for (let i = 0; i < 7; i++) {
        const a = i * 2.4, lean = 0.35 + (i % 3) * 0.18;
        const leaf = add(new T.Mesh(leafGeo, leafMats[i % 3]!), true, false);
        leaf.scale.set(0.5 * s, 1.5 * s, 0.22 * s);
        leaf.position.set(x + Math.sin(a) * 0.16 * s, y + 0.3 * s + (i % 2) * 0.08, z + Math.cos(a) * 0.16 * s);
        leaf.rotation.set(Math.cos(a) * lean, 0, -Math.sin(a) * lean);
      }
    };
    const WALL_R = 8.2;
    for (let i = 0; i < 40; i++) {
      const a = (i / 40) * Math.PI * 2;
      if (Math.cos(a) > 0.55) continue; // open toward the camera
      const gate = Math.abs(wrapPi(a - Math.PI)) < 0.2; // the arch at the back
      if (gate) continue;
      const b = add(new T.Mesh(blockGeo, wallMat));
      b.position.set(Math.sin(a) * WALL_R, 0.31, Math.cos(a) * WALL_R);
      b.rotation.y = a;
      b.scale.x = (2 * Math.PI * WALL_R) / 40 - 0.04;
      const c = add(new T.Mesh(capGeo, capMat));
      c.position.set(b.position.x, 0.66, b.position.z);
      c.rotation.y = a;
      c.scale.x = b.scale.x;
      if (i % 5 === 2) { // a planter on the wall
        const pot = add(new T.Mesh(new T.BoxGeometry(0.75, 0.5, 0.75), potMat));
        pot.position.set(Math.sin(a) * (WALL_R - 0.05), 0.95, Math.cos(a) * (WALL_R - 0.05));
        pot.rotation.y = a;
        const soil = add(new T.Mesh(new T.BoxGeometry(0.62, 0.04, 0.62), soilMat), false, true);
        soil.position.set(pot.position.x, 1.205, pot.position.z);
        soil.rotation.y = a;
        plant(pot.position.x, pot.position.z, 1.15, 1.25);
      }
    }
    // The arch: two pillars and a lintel at the back, the market's gate.
    const archMat = std(0xeae0cf, 0.9);
    for (const sx of [-1, 1]) {
      const p = add(new T.Mesh(new T.BoxGeometry(0.7, 3.4, 0.7), archMat));
      p.position.set(sx * 1.55, 1.7, -WALL_R);
      const base = add(new T.Mesh(new T.BoxGeometry(0.9, 0.3, 0.9), capMat));
      base.position.set(sx * 1.55, 0.15, -WALL_R);
    }
    const lintel = add(new T.Mesh(new T.BoxGeometry(4.0, 0.55, 0.85), archMat));
    lintel.position.set(0, 3.65, -WALL_R);
    const band = add(new T.Mesh(new T.BoxGeometry(4.05, 0.07, 0.88), M.gold), false, false);
    band.position.set(0, 3.4, -WALL_R);
    // Banners on poles, left and right of the stage.
    const poleGeo = new T.CylinderGeometry(0.045, 0.045, 3.2, 10), clothGeo = new T.PlaneGeometry(0.8, 1.5);
    const clothMat = new T.MeshStandardMaterial({ color: C.banner, roughness: 0.95, side: T.DoubleSide });
    const markGeo = new T.CircleGeometry(0.16, 20);
    for (const [x, z] of [[-5.6, -3.6], [5.6, -3.6]] as const) {
      const pole = add(new T.Mesh(poleGeo, M.charcoal));
      pole.position.set(x, 1.6, z);
      const bar = add(new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 0.95, 8), M.charcoal));
      bar.rotation.z = Math.PI / 2;
      bar.position.set(x, 3.05, z + 0.02);
      const cloth = add(new T.Mesh(clothGeo, clothMat), true, true);
      cloth.position.set(x, 2.25, z + 0.04);
      cloth.rotation.y = x < 0 ? 0.35 : -0.35;
      for (const [dx, dy, s] of [[-0.06, 0.05, 1], [0.07, 0.12, 0.85]] as const) {
        const leafMark = add(new T.Mesh(markGeo, M.charcoal), false, false);
        leafMark.scale.set(0.45 * s, 1 * s, 1);
        leafMark.rotation.set(0, cloth.rotation.y, dx < 0 ? 0.4 : -0.4);
        leafMark.position.set(x + dx * Math.cos(cloth.rotation.y), 2.3 + dy, z + 0.05 - dx * Math.sin(cloth.rotation.y));
      }
      const ball = add(new T.Mesh(new T.SphereGeometry(0.07, 10, 8), M.gold));
      ball.position.set(x, 3.24, z);
    }
    // Big planters on the floor at the front corners frame the shot.
    for (const [x, z] of [[-6.4, 3.2], [6.4, 3.2], [-7.0, -1.0], [7.0, -1.0]] as const) {
      const pot = add(new T.Mesh(new T.BoxGeometry(0.9, 0.7, 0.9), potMat));
      pot.position.set(x, 0.35, z);
      const lip = add(new T.Mesh(new T.BoxGeometry(0.96, 0.035, 0.96), M.gold), false, true);
      lip.position.set(x, 0.715, z);
      const soil = add(new T.Mesh(new T.BoxGeometry(0.8, 0.04, 0.8), soilMat), false, true);
      soil.position.set(x, 0.725, z);
      plant(x, z, 0.62, 1.6);
    }

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
    // Clay people: a big round head, a capsule torso, capsule legs, and arms on shoulder pivots so they can hold, wave or droop.
    // Sellers get a clay tone and an accessory (cap, bun, backpack, satchel) from their look; tone is personality, never meaning.
    const CLAY = [0x4b4b4e, 0x8b8783, 0xa38c74, 0xc6b49b, 0x6f5f53, 0xa7aaa6, 0xb5917a] as const;
    const toneOf = (look: Look) => CLAY[Math.max(0, SELLER_COLORS.indexOf(look.color as (typeof SELLER_COLORS)[number])) % CLAY.length]!;
    const shade = (c: number, k: number) => new T.Color(c).multiplyScalar(k).getHex();
    const addFig = (k: string, kind: FigKind, color: number, look: Look | null): Fig => {
      const scale = kind === "buyer" ? BUYER_SCALE : FIG_SCALE;
      const mats: Fig["mats"] = [];
      const mk = (c: number, rough = 0.78) => { const mat = std(c, rough); mats.push({ mat, base: new T.Color(c) }); return mat; };
      const body = mk(color);
      const dark = mk(kind === "advocate" ? 0x4b4b4e : shade(color, 0.72));
      const group = new T.Group();
      group.rotation.order = "YXZ";
      group.scale.setScalar(scale);
      const put = (parent: THREE.Object3D, geo: THREE.BufferGeometry, mat: THREE.Material, x: number, y: number, z: number, shadow = true) => {
        const m = new T.Mesh(geo, mat);
        m.position.set(x, y, z);
        m.castShadow = shadow;
        parent.add(m);
        return m;
      };
      for (const sx of [-0.12, 0.12]) put(group, G.leg, dark, sx, 0.25, 0);
      put(group, G.torso, body, 0, 0.74, 0);
      put(group, G.head, body, 0, 1.3, 0.02);
      for (const sx of [-0.1, 0.1]) put(group, G.eye, M.eye, sx, 1.33, 0.29, false).scale.set(0.85, 1.35, 0.6);
      const arm = (sx: number) => {
        const pivot = new T.Group();
        pivot.position.set(sx * 0.27, 0.95, 0);
        put(pivot, G.arm, body, 0, -0.2, 0);
        group.add(pivot);
        return pivot;
      };
      const arms = { l: arm(-1), r: arm(1) };
      const acc = look?.hat ?? (kind === "buyer" ? "beanie" : null);
      const accMat = mk(look ? shade(color, 0.55) : shade(color, 0.6));
      if (acc === "party" || acc === "cap") { // cap with a front brim
        put(group, G.dome, accMat, 0, 1.4, 0.02).scale.set(1, 0.72, 1);
        put(group, G.brim, accMat, 0, 1.42, 0.26).scale.set(0.8, 1, 0.65);
      }
      if (acc === "top") put(group, G.bun, accMat, 0, 1.62, -0.08);
      if (acc === "beanie" || acc === "cap") put(group, G.pack, accMat, 0, 0.82, -0.25).scale.set(1, 1, 1); // backpack
      if (acc === "party" || acc === "top") { // satchel on a strap
        put(group, G.satchel, accMat, -0.27, 0.56, 0.06);
        const s = put(group, G.strap, accMat, 0, 0.82, 0, false);
        s.rotation.set(0, Math.PI / 2, 0.5);
      }
      let pad: Fig["pad"] = null;
      if (kind === "advocate") {
        put(group, G.bun, body, 0, 1.28, -0.3).scale.set(1, 1.3, 1); // ponytail
        const pivot = new T.Group();
        pivot.position.y = CHEST;
        const item = new T.Group();
        item.position.set(0.12, 0, 0.32);
        item.rotation.x = -Math.PI / 5;
        const board = new T.Mesh(G.tablet, M.charcoal); board.castShadow = true;
        const sheet = new T.Mesh(G.paperSheet, M.paper); sheet.position.z = 0.02;
        const clip = new T.Mesh(G.bun, M.gold); clip.scale.set(0.6, 0.35, 0.35); clip.position.set(0, 0.19, 0.03);
        item.add(board, sheet, clip);
        pivot.add(item);
        group.add(pivot);
        pad = { pivot, item };
      }
      group.visible = false;
      tag(group, k);
      scene.add(group);
      return { key: k, kind, sig: "", group, mats, scale, pad, arms, arm: "rest", vis: fresh(), to: fresh(), tier: 0, aimSign: 1, tw: null };
    };
    // Bazaar Shield is a stone pedestal with a gold-rimmed shield, not a person: it guards the gate.
    const addShield = (): Fig => {
      const group = new T.Group();
      group.rotation.order = "YXZ";
      const block = new T.Mesh(new T.BoxGeometry(1.0, 0.95, 0.7), std(C.stone, 0.9));
      block.position.y = 0.475;
      const slab = new T.Mesh(new T.BoxGeometry(1.12, 0.1, 0.82), std(C.wallTop, 0.9));
      slab.position.y = 1.0;
      const shape = new T.Shape();
      shape.moveTo(0, 0.42); shape.quadraticCurveTo(0.2, 0.36, 0.36, 0.38); shape.lineTo(0.34, 0.02);
      shape.quadraticCurveTo(0.3, -0.3, 0, -0.46); shape.quadraticCurveTo(-0.3, -0.3, -0.34, 0.02); shape.lineTo(-0.36, 0.38);
      shape.quadraticCurveTo(-0.2, 0.36, 0, 0.42);
      const rimGeo = new T.ExtrudeGeometry(shape, { depth: 0.08, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 2 });
      const faceGeo = new T.ExtrudeGeometry(shape, { depth: 0.02, bevelEnabled: false });
      const pivot = new T.Group();
      pivot.position.set(0, 1.62, 0);
      const item = new T.Group();
      const rim = new T.Mesh(rimGeo, M.gold);
      const face = new T.Mesh(faceGeo, M.charcoal);
      face.scale.setScalar(0.82);
      face.position.set(0, 0.015, 0.1);
      const tick = [[-0.09, -0.02, 0.17, -0.8], [0.06, 0.04, 0.3, 0.9]].map(([x, y, w, r]) => {
        const m = new T.Mesh(new T.BoxGeometry(w!, 0.06, 0.03), M.gold);
        m.position.set(x!, y!, 0.13);
        m.rotation.z = r!;
        return m;
      });
      item.add(rim, face, ...tick);
      pivot.add(item);
      for (const m of [block, slab, rim]) m.castShadow = m.receiveShadow = true;
      group.add(block, slab, pivot);
      group.visible = false;
      tag(group, "shield");
      scene.add(group);
      return { key: "shield", kind: "shield", sig: "shield", group, mats: [], scale: 1, pad: { pivot, item }, arms: null, arm: "rest", vis: fresh(), to: fresh(), tier: 1, aimSign: 1, tw: null };
    };
    figs.set("buyer", addFig("buyer", "buyer", C.buyer, null));
    figs.set("advocate", addFig("advocate", "advocate", C.advocate, null));
    figs.set("shield", addShield());
    // Anonymous sealed bidders: plain grey clay, each carrying a sealed envelope.
    for (let i = 0; i < ANON_MAX; i++) {
      const f = addFig(`anon:${i}`, "anon", C.anon, null);
      const env = mkEnvelope();
      env.visible = true;
      scene.remove(env);
      env.position.set(0, 0.78, 0.36);
      env.rotation.set(Math.PI / 2.4, 0, 0.15);
      f.group.add(env);
      figs.set(f.key, f);
    }
    const table = new T.Mesh(G.table, M.table);
    table.position.set(TABLE.x, TABLE.y, TABLE.z);
    table.castShadow = table.receiveShadow = true;
    tag(table, "referee");
    scene.add(table);
    figs.set("referee", { key: "referee", kind: "referee", sig: "referee", group: table, mats: [], scale: 1, pad: null, arms: null, arm: "rest", vis: fresh(), to: fresh(), tier: 2, aimSign: 1, tw: null });

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
      // Fit the seat ring (radius about 6, heads included) into the view; on wide boxes height decides, on phones width does.
      camera.aspect = W / H;
      const tanV = Math.tan(((VFOV / 2) * Math.PI) / 180);
      const fitW = 5.4 / (tanV * camera.aspect);
      const fitH = 3.3 / tanV;
      viewDist = Math.max(fitW, fitH);
      placeCamera();
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
        case "lifted": return { x: TABLE.x, y: 1.3, z: TABLE.z, rx: 1.1, ry: 0, vis: 0 };
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
        const yaw = f.kind === "shield" ? -0.55 : f.kind === "advocate" ? 0.7 + v.aim * 0.35 : v.yaw; // pedestal and advocate face the camera
        f.group.rotation.set(f.kind === "shield" ? 0 : Math.max(0, v.pitch), yaw, 0);
        f.group.scale.set(f.scale, f.scale * (1 - 0.1 * clamp01((v.pitch - 0.14) / 0.07)), f.scale); // knocked figures slump
        if (f.arms) {
          const [lx, lz, rx, rz] = f.arm === "hold" ? [-1.15, 0.25, -1.15, -0.25] : f.arm === "wave" ? [0, 0.12, 0, -2.6] : f.arm === "droop" ? [0.15, 0.05, 0.15, -0.05] : [0.05, 0.14, -0.05, -0.14];
          f.arms.l.rotation.set(lx, 0, lz);
          f.arms.r.rotation.set(rx, 0, rz);
        }
        for (const m of f.mats) m.mat.color.copy(desat.copy(m.base).lerp(knock, v.dim));
        if (f.pad) {
          const shield = f.kind === "shield";
          f.pad.pivot.rotation.y = f.aimSign * v.aim * ((shield ? 25 : 20) * Math.PI) / 180;
          f.pad.pivot.position.y = (shield ? 1.62 : CHEST) + v.aim * (shield ? 0.18 : 0.08);
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
        g.visible = false; // ponytail: the anonymous bidders carry the sealed envelopes now; the table pile is kept for a later view
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
      const items: { el: HTMLDivElement; w: number; h: number; px: number; py: number; vis: number; prio: number; feet: boolean }[] = [];
      for (const [k, el] of plateEls) {
        const f = figs.get(k.split("#")[0]!);
        if (!f || f.vis.vis < 0.02) { el.style.visibility = "hidden"; continue; }
        const refe = f.kind === "referee";
        const feet = el.dataset.anchor === "feet";
        const lift = f.key === plinthFor ? PLINTH * tPlinth.v : 0;
        v3.set(f.vis.x, f.vis.y + lift + (refe ? 0.4 : feet ? (f.kind === "shield" ? 0.05 : -0.05) : ANCHOR * f.scale), f.vis.z + (refe ? 0.2 : feet ? 0.25 : 0)).project(camera);
        items.push({ el, w: el.offsetWidth, h: el.offsetHeight, px: ((v3.x + 1) / 2) * W, py: ((1 - v3.y) / 2) * H, vis: f.vis.vis, prio: Number(el.dataset.prio ?? 2), feet });
      }
      items.sort((p, q) => p.prio - q.prio || p.px - q.px);
      const placed: { x: number; y: number; w: number; h: number }[] = [];
      for (const it of items) {
        const x0 = Math.max(4, Math.min(W - it.w - 4, it.px - it.w / 2));
        const step = 22;
        const home = it.feet ? it.py + 2 : it.py - it.h - 2;
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
        if (!figs.has(o.key)) { const f = addFig(o.key, "offer", toneOf(looks[o.key]!), looks[o.key]!); f.sig = sigOf(o.key); figs.set(o.key, f); }
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
      const card = f.kind === "offer" ? st.cards[f.key.slice(6)] : undefined;
      f.arm = f.kind === "anon" ? "hold"
        : f.kind === "buyer" ? (st.crown || st.focus.includes("buyer") ? "wave" : "rest")
        : card === "lifted" ? "wave" : card === "dropped" ? "droop" : card === "held" ? "hold" : "rest";
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
        const seatIdx = f.kind === "anon" ? Number(f.key.slice(5)) : live.current.scene.offers.findIndex((o) => o.key === f.key);
        if (b.kind === "arrive" && f.kind === "anon" && to.vis < 0.5) {
          delay = 110 * seatIdx; dur = 1; // the anonymous bidder steps aside the moment its seller is named
        } else if (b.kind === "arrive" && f.kind === "offer" && from.vis < 0.5 && seatIdx < ANON_MAX) {
          start = { ...to, vis: 0 }; delay = 110 * seatIdx; dur = 420; arc = 0.4; // named in place, with a little hop
        } else if (from.vis < 0.5 && to.vis >= 0.5) {
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
      else if (s.phase === "open" && prev.phase === "open" && b === prev.beat) mode = "drop";
      if (mode === "snap") snap(st);
      else if (mode === "beat") startBeat(s.beats[b - 1]!, st, now);
      else if (mode === "drop") startBeat({ kind: "arrive", name: "", focus: [], advancing: [], knocked: [], caption: "", ms: 900 }, st, now);
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
      const mats = new Set<THREE.Material>([M.eye, M.paper, M.wax, M.table, M.gold, M.charcoal, M.cream, M.ring, ...M.bits]);
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

interface Plate { key: string; name: string; origin: Origin; price: string | null; word: string | null; struck: boolean; prio: number; say?: string; sealed?: boolean }

/** The floating card over an anonymous sealed bidder: an envelope and two words, no name, no price. */
function SealedCard() {
  return (
    <div aria-hidden="true" className="pointer-events-none flex flex-col items-center gap-1 rounded-xl bg-white/95 px-3 pb-1.5 pt-2 text-[13px] font-medium text-[#2B2A33] shadow-[0_6px_18px_rgba(90,60,30,0.16)]">
      <svg viewBox="0 0 40 28" className="h-6 w-9" aria-hidden="true">
        <rect x="1" y="1" width="38" height="26" rx="3" fill="#FBF4E6" stroke="#D9C8AE" />
        <path d="M2 3 20 16 38 3" fill="none" stroke="#D9C8AE" strokeWidth="1.4" />
        <circle cx="20" cy="15.5" r="4.2" fill="#B8863B" />
      </svg>
      Offer sealed
    </div>
  );
}

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
      if (fixedOnly && !say && (f.key === "referee" || !focus.has(f.key)) && selected !== f.key) continue; // the cast steps up only while it is in focus, selected or speaking
      out.push({ ...f, origin: "SIM", price: null, word: null, struck: false, prio: say ? 0 : focus.has(f.key) || selected === f.key ? 1 : 2, say });
    }
    for (let i = 0; i < ANON_MAX; i++) {
      const k = `anon:${i}`;
      if (stage.actors[k]?.visible) out.push({ key: k, name: "Offer sealed", origin: "SIM", price: null, word: null, struck: false, prio: 1, sealed: true });
    }
    for (const o of scene.offers) {
      if (!stage.actors[o.key]?.visible) continue;
      const mark = stage.marks[o.bidId] ?? "none";
      const hard = mark === "blocked" || mark === "vetoed" || mark === "refused";
      if (stage.crown && hard && selected !== o.key) continue;
      out.push({ key: o.key, name: o.name, origin: o.origin, price: hard ? null : formatMoney(o.landed), word: WORD[mark] ?? null, struck: hard, prio: mark === "winner" || bubbles?.[o.key] ? 0 : focus.has(o.key) || selected === o.key ? 1 : 2, say: bubbles?.[o.key] || undefined });
    }
    return out;
  }, [scene, stage, selected, bubbles]);
  const setEl = (key: string) => (el: HTMLDivElement | null) => { if (el) plateEls.current.set(key, el); else plateEls.current.delete(key); };
  const HIDDEN = { transform: "translate3d(-9999px, 0, 0)", visibility: "hidden" } as const;

  return (
    <div
      ref={box}
      className="relative h-[440px] w-full overflow-hidden lg:h-[600px]"
      style={{ background: "radial-gradient(120% 90% at 50% 35%, #FBF6EE 0%, #F1E7D9 70%, #E8DCCB 100%)" }}
    >
      <div ref={host} className="absolute inset-0" aria-hidden="true" />
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-[5]" style={{ background: "radial-gradient(60% 45% at 0% 0%, rgba(251,246,238,0.92) 0%, rgba(251,246,238,0.6) 45%, rgba(251,246,238,0) 75%), radial-gradient(28% 22% at 100% 0%, rgba(251,246,238,0.9) 0%, rgba(251,246,238,0) 80%)" }} />
      {plates.map((p) =>
        p.say || p.sealed ? (
          <div key={`${p.key}#top`} data-prio={p.sealed ? 1 : 0} data-anchor="top" ref={setEl(`${p.key}#top`)} className="pointer-events-none absolute left-0 top-0 z-10 will-change-transform" style={HIDDEN}>
            {p.sealed ? <SealedCard /> : <Bubble key={p.say} text={p.say!} reducedMotion={reducedMotion} />}
          </div>
        ) : null,
      )}
      {plates.filter((p) => !p.sealed).map((p) => (
        <div key={p.key} data-prio={p.prio} data-anchor="feet" ref={setEl(p.key)} className="pointer-events-none absolute left-0 top-0 z-10 will-change-transform" style={HIDDEN}>
          <button type="button" onClick={() => onPick(p.key)} aria-pressed={selected === p.key} className="pointer-events-auto flex min-h-[44px] items-start p-1 text-left">
            <span
              className={`flex flex-col items-center whitespace-nowrap rounded-lg bg-[#FBF7F0]/95 px-2.5 py-[3px] text-[13px] font-medium leading-[17px] text-[#2B2A33] shadow-[0_3px_10px_rgba(90,60,30,0.14)] ${selected === p.key ? "ring-2 ring-[#4F7F7C]" : ""} ${p.struck ? "opacity-75" : ""} ${p.word === "Winner" ? "bg-[#FFF6DD] ring-1 ring-[#C9A45C]" : ""}`}
            >
              <span className="flex items-center gap-1.5">
                <span className={`max-w-[10rem] truncate ${p.struck ? "line-through" : ""}`}>{p.name}</span>
                <Chip origin={p.origin} />
              </span>
              {(p.price || p.word) && (
                <span className="flex items-center gap-1.5 text-[11.5px] font-medium tabular-nums text-[#2B2A33]/75">
                  {p.price && <span>{p.price}</span>}
                  {p.word && <span className={p.word === "Winner" ? "font-bold text-[#8A6A22]" : ""}>{p.word}</span>}
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
