"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useReducedMotion } from "motion/react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { SAMPLES } from "@/lib/arenaFixture";
import type { ArenaRows } from "@/lib/arenaScene";
import { FRAME, FloorHud } from "@/components/floor/FloorHud";
import { FloorAquariumPixel } from "@/components/floor/FloorAquariumPixel";
import { FloorCall } from "@/components/floor/FloorCall";
import { useChatFeed } from "@/components/floor/useChatFeed";
import { REFERENCE, floorScript, type FloorPhase, type FloorScript } from "@/components/floor/floorPhases";
import { useFloorClock } from "@/components/floor/useFloorClock";

/** The signature screen: a calm pixel-art Pac-Man aquarium where agents buy a real build. Reads the market tables, turns them into a
 * FloorScript, and plays it. `?replay=reference` is the 1920 x 1080 video frame (REFERENCE run, no chrome, loops from 0)
 * and `?sample=gpu|gpu-open|ssd` swaps the tables for a labelled SIM round. */

type SampleName = keyof typeof SAMPLES;
const MAX_STAGE = 1200;
const INK = "#0b1b2b";
const TEXT = "#eef3f8";

const subscribeResize = (cb: () => void) => {
  window.addEventListener("resize", cb);
  return () => window.removeEventListener("resize", cb);
};
const subscribeNone = () => () => {};
const windowSize = () => `${window.innerWidth}x${window.innerHeight}`;

export default function FloorPage() {
  // Read from window.location, not with useSearchParams (cacheComponents would demand a Suspense boundary for it); null while server rendering.
  const search = useSyncExternalStore(subscribeNone, () => window.location.search, () => null);
  const params = useMemo(() => {
    if (search === null) return null;
    const q = new URLSearchParams(search);
    const sample = q.get("sample");
    return {
      replay: q.get("replay") === "reference",
      t: Number.isFinite(Number(q.get("t"))) && q.get("t") !== null ? Math.max(0, Number(q.get("t"))) : 0,
      paused: q.get("paused") === "1",
      sample: sample !== null && Object.hasOwn(SAMPLES, sample) ? (sample as SampleName) : null,
    };
  }, [search]);
  if (!params) return null;
  return params.replay ? <ReplayView t={params.t} /> : <FloorView sample={params.sample} t={params.t} paused={params.paused} />;
}

/** The aquarium inside the HUD. `follow` is the small call tile: no HUD chrome, the camera follows Pac-Man. */
function Stage({ script, phase, reducedMotion, width, frame = false, follow = false }: { script: FloorScript; phase: FloorPhase; reducedMotion: boolean; width: number; frame?: boolean; follow?: boolean }) {
  const fr = frame && !follow;
  return (
    <FloorHud script={script} phase={phase} width={width} frame={fr} reducedMotion={reducedMotion} bare={follow}>
      <FloorAquariumPixel script={script} phase={phase} reducedMotion={reducedMotion} width={fr ? FRAME.stageW : width} follow={follow} />
    </FloorHud>
  );
}

/** The video frame: fixed 1920 x 1080, scaled to fit the window, nothing else on the page, REFERENCE run from 0 on a loop. */
function ReplayView({ t }: { t: number }) {
  const size = useSyncExternalStore(subscribeResize, windowSize, () => "1920x1080");
  const [w, h] = size.split("x").map(Number) as [number, number];
  const k = Math.min(w / 1920, h / 1080);
  const { phase, seconds } = useFloorClock(REFERENCE, { replay: true, reducedMotion: false, initial: t });
  const chat = useChatFeed(REFERENCE, seconds, { replay: true });
  useEffect(() => {  // the video frame: the site header and status footer must not draw over it
    document.documentElement.dataset.replay = "1";
    return () => { delete document.documentElement.dataset.replay; };
  }, []);
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 2147483000, background: INK, color: TEXT, overflow: "hidden" }}>
      <div style={{ position: "absolute", left: "50%", top: "50%", width: 1920, height: 1080, transform: `translate(-50%, -50%) scale(${k})`, transformOrigin: "50% 50%" }}>
        <FloorCall lines={chat.lines} live={chat.live} reducedMotion={false} floor={(follow) => <Stage script={REFERENCE} phase={phase} reducedMotion={false} width={1920} frame follow={follow} />} />
      </div>
    </div>
  );
}

const BTN = "inline-flex min-h-11 items-center rounded-xl border border-white/15 bg-white/5 px-4 text-[15px] font-medium text-[#eef3f8] hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#8fb0ff]";

function FloorView({ sample, t, paused }: { sample: SampleName | null; t: number; paused: boolean }) {
  const [rounds] = useTable(tables.round);
  const [needs] = useTable(tables.sellerNeeds);
  const [results] = useTable(tables.roundResult);
  const [events] = useTable(tables.floorEvent);
  const rows = useMemo<ArenaRows>(() => (sample ? SAMPLES[sample] : { rounds, needs, results, events }), [sample, rounds, needs, results, events]);
  const script = useMemo(() => floorScript(rows), [rows]);

  const reduced = !!useReducedMotion();
  const clock = useFloorClock(script, { reducedMotion: reduced, initial: t, startPaused: paused });
  const chat = useChatFeed(script, clock.seconds, { replay: false });

  // The stage fills the column up to 1200 px; the width is measured so the HUD scales with it.
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(960);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => e && setWidth(Math.max(280, Math.min(MAX_STAGE, Math.floor(e.contentRect.width)))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div className="grid w-full min-w-0 max-w-full gap-4 overflow-hidden rounded-[24px] p-4 sm:p-6" style={{ background: INK, color: TEXT }}>
      <div ref={box} className="mx-auto w-full min-w-0 max-w-full" style={{ maxWidth: MAX_STAGE }}>
        <FloorCall lines={chat.lines} live={chat.live} reducedMotion={reduced} floor={(follow) => <Stage script={script} phase={clock.phase} reducedMotion={reduced} width={width} follow={follow} />} />
      </div>
      <div className="flex min-w-0 max-w-full flex-wrap items-center justify-center gap-2">
        <button type="button" className={BTN} onClick={clock.playing ? clock.pause : clock.play} aria-pressed={!clock.playing}>{clock.playing ? "Pause" : "Play"}</button>
        <button type="button" className={BTN} onClick={clock.restart}>Restart</button>
      </div>
    </div>
  );
}
