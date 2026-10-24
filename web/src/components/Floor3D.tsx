"use client";
// Minimal 3D floor: simple shapes, no model downloads. A character moves only when a new floor_event row names it;
// with the market disconnected nothing moves. Click a character to see the row that last moved it.
import { useEffect, useRef, useState } from "react";
import type { Actor } from "@/lib/floor";

export interface FloorRow { id: string; actor: string; kind: string; label: string; origin: string; at: Date; ref: string }

const COLOR: Record<Actor["kind"], number> = { buyer: 0xf5f5f5, advocate: 0xbdbdbd, shield: 0x3a3a3a, referee: 0x8c8c8c, seller: 0x6b6b6b };
const SELLER_BY_ORIGIN: Record<string, number> = { LIVE: 0xffffff, MIRROR: 0xa8a8a8, SIM: 0x5e5e5e };
const HOP_MS = 700;

export function Floor3D({ actors, rows, frozen, onPick }: { actors: Actor[]; rows: FloorRow[]; frozen: boolean; onPick: (key: string) => void }) {
  const mount = useRef<HTMLDivElement>(null);
  const api = useRef<{ hop: (key: string) => void; freeze: (f: boolean) => void } | null>(null);
  const seen = useRef<string | null>(null);
  const [labels, setLabels] = useState<{ key: string; name: string; x: number; y: number }[]>([]);
  const actorKeys = actors.map((a) => a.key).join("|");

  useEffect(() => {
    const el = mount.current;
    if (!el) return;
    let disposed = false;
    let cleanup = () => {};
    import("three").then((THREE) => {
      if (disposed) return;
      const w = el.clientWidth, h = el.clientHeight;
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
      renderer.setSize(w, h);
      el.appendChild(renderer.domElement);
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 100);
      camera.position.set(0, 7, 10);
      camera.lookAt(0, 0.5, 0);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x888888, 2.2));
      const sun = new THREE.DirectionalLight(0xffffff, 1.2);
      sun.position.set(3, 8, 5);
      scene.add(sun);
      const floor = new THREE.Mesh(new THREE.CylinderGeometry(5.2, 5.2, 0.1, 64), new THREE.MeshStandardMaterial({ color: 0x1a1a1a }));
      floor.position.y = -0.05;
      scene.add(floor);
      const ring = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 0.3, 48), new THREE.MeshStandardMaterial({ color: 0x2c2c2c }));
      ring.position.y = 0.15;
      scene.add(ring);

      const bodies = new Map<string, InstanceType<typeof THREE.Group>>();
      actors.forEach((a, i) => {
        const angle = (i / actors.length) * Math.PI * 2;
        const g = new THREE.Group();
        const color = a.kind === "seller" ? SELLER_BY_ORIGIN[a.origin] ?? SELLER_BY_ORIGIN.SIM : COLOR[a.kind];
        const mat = new THREE.MeshStandardMaterial({ color });
        const body = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.4, 1, 24), mat);
        body.position.y = 0.5;
        const head = new THREE.Mesh(new THREE.SphereGeometry(0.3, 24, 16), mat);
        head.position.y = 1.3;
        g.add(body, head);
        g.position.set(Math.sin(angle) * 3.6, 0, Math.cos(angle) * 3.6);
        g.lookAt(0, 0, 0);
        g.userData.key = a.key;
        body.userData.key = a.key;
        head.userData.key = a.key;
        scene.add(g);
        bodies.set(a.key, g);
      });

      const project = () => {
        const out: { key: string; name: string; x: number; y: number }[] = [];
        for (const a of actors) {
          const g = bodies.get(a.key)!;
          const v = new THREE.Vector3(g.position.x, 1.9, g.position.z).project(camera);
          out.push({ key: a.key, name: a.name, x: ((v.x + 1) / 2) * el.clientWidth, y: ((1 - v.y) / 2) * el.clientHeight });
        }
        setLabels(out);
      };

      // Render on demand: frames run only while a row's hop is playing.
      const hops = new Map<string, number>();
      let raf = 0;
      let isFrozen = false;
      const frame = (now: number) => {
        raf = 0;
        if (isFrozen) return;
        for (const [key, start] of hops) {
          const t = (now - start) / HOP_MS;
          const g = bodies.get(key);
          if (!g) continue;
          if (t >= 1) {
            g.position.y = 0;
            hops.delete(key);
          } else g.position.y = Math.sin(t * Math.PI) * 0.8;
        }
        renderer.render(scene, camera);
        if (hops.size) raf = requestAnimationFrame(frame);
      };
      const kick = () => {
        if (!raf && !isFrozen) raf = requestAnimationFrame(frame);
      };
      api.current = {
        hop: (key) => {
          if (!bodies.has(key) || isFrozen) return;
          hops.set(key, performance.now());
          kick();
        },
        freeze: (f) => {
          isFrozen = f;
          if (f && raf) cancelAnimationFrame(raf), (raf = 0);
          if (!f) kick();
        },
      };

      const ray = new THREE.Raycaster();
      const click = (ev: PointerEvent) => {
        const r = renderer.domElement.getBoundingClientRect();
        ray.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
        const hit = ray.intersectObjects([...bodies.values()], true)[0];
        if (hit?.object.userData.key) onPick(hit.object.userData.key);
      };
      renderer.domElement.addEventListener("pointerdown", click);
      const resize = () => {
        renderer.setSize(el.clientWidth, el.clientHeight);
        camera.aspect = el.clientWidth / el.clientHeight;
        camera.updateProjectionMatrix();
        renderer.render(scene, camera);
        project();
      };
      window.addEventListener("resize", resize);
      renderer.render(scene, camera);
      project();

      cleanup = () => {
        if (raf) cancelAnimationFrame(raf);
        window.removeEventListener("resize", resize);
        renderer.domElement.removeEventListener("pointerdown", click);
        renderer.dispose();
        renderer.domElement.remove();
        api.current = null;
      };
    });
    return () => {
      disposed = true;
      cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actorKeys]);

  useEffect(() => api.current?.freeze(frozen), [frozen]);

  // New rows (after the first load) make their actor hop. History on load does not animate.
  useEffect(() => {
    if (frozen || rows.length === 0) return;
    const newest = rows[0].id;
    if (seen.current !== null) {
      for (const r of rows) {
        if (r.id === seen.current) break;
        api.current?.hop(r.actor);
      }
    }
    seen.current = newest;
  }, [rows, frozen]);

  return (
    <div ref={mount} className="relative h-[420px] w-full overflow-hidden rounded-[var(--radius)] bg-soft sm:h-[520px]">
      {labels.map((l) => (
        <button
          key={l.key}
          onClick={() => onPick(l.key)}
          className="absolute -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md bg-panel/90 px-1.5 py-0.5 text-[11px] font-semibold text-ink"
          style={{ left: l.x, top: l.y }}
        >
          {l.name}
        </button>
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
