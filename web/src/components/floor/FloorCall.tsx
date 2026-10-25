"use client";

import { useEffect, useReducer, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { motion, useMotionValue, type MotionStyle } from "motion/react";
import type { ChatLine } from "@/lib/chatFeed";
import { ChatPane } from "@/components/floor/ChatPane";
import { callReducer, initialCall, type Corner } from "@/components/floor/callState";

/** The floor's frame is a video call. Big pane: the floor (default) or the ASI:One chat. Small tile: the other one, in a corner, draggable.
 * Tap the tile or press C to swap; both panes are shared-layout elements so the swap is one ~350 ms morph (instant under reduced motion).
 * The floor in the tile is a camera that follows Pac-Man: the `floor` builder is called with follow = true. */

const INSET = 16;
const PHONE = 640;
const SWAP_MS = 0.35;
const GLASS: CSSProperties = {
  background: "#112437cc",
  backdropFilter: "blur(12px)",
  WebkitBackdropFilter: "blur(12px)",
  boxShadow: "inset 0 0.5px 0 #ffffff1f, 0 0 0 0.5px #eef3f81f, 0 4px 40px 8px #00000066, 0 34px 70px -34px #00000099",
  borderRadius: 18,
};

const WHITE: CSSProperties = {
  background: "#ffffff",
  boxShadow: "0 0 0 1px #e6eaef, 0 8px 28px 2px #00000047, 0 30px 60px -30px #00000080",
  borderRadius: 18,
};
const CARD_MAX = 720;
const CARD_MIN = 260;

function cornerStyle(c: Corner): CSSProperties {
  return { [c.startsWith("t") ? "top" : "bottom"]: INSET, [c.endsWith("l") ? "left" : "right"]: INSET };
}

export function FloorCall({ floor, lines, live, reducedMotion }: { floor: (follow: boolean) => ReactNode; lines: ChatLine[]; live: boolean; reducedMotion: boolean }) {
  const [call, dispatch] = useReducer(callReducer, initialCall);
  const frame = useRef<HTMLDivElement>(null);
  const floorPane = useRef<HTMLDivElement>(null);
  const chatPane = useRef<HTMLDivElement>(null);
  const dragged = useRef(false);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const [frameW, setFrameW] = useState(960);
  const [bigH, setBigH] = useState(560);
  const { swapped, corner, unread } = call;

  const ids = lines.map((l) => l.id).join("\n");
  useEffect(() => {
    dispatch({ type: "newLines", ids: ids ? ids.split("\n") : [] });
  }, [ids]);

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => e && setFrameW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Remember the floor's natural height so the frame keeps its size while the chat is the big pane.
  useEffect(() => {
    const el = floorPane.current;
    if (!el || swapped) return;
    const ro = new ResizeObserver(([e]) => e && e.contentRect.height > 0 && setBigH(Math.round(e.contentRect.height)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [swapped]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key !== "c" && e.key !== "C") || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      dispatch({ type: "toggle" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const transition = { duration: reducedMotion ? 0 : SWAP_MS, ease: [0.32, 0.72, 0, 1] as const };
  const tileWidth = frameW < PHONE ? "34%" : "24%";
  const tileBase: MotionStyle = { position: "absolute", width: tileWidth, aspectRatio: "16 / 10", zIndex: 20, overflow: "hidden", touchAction: "none", ...cornerStyle(corner), x, y };
  const floorTile: MotionStyle = { ...tileBase, ...GLASS };
  const chatTile: MotionStyle = { ...tileBase, ...WHITE };
  const bigFloor: MotionStyle = { position: "relative", width: "100%", zIndex: 0, overflow: "hidden" };
  // The big chat is a card sized to its content: centred, at most 720 px wide, at least 260 px tall, growing with the messages up to the stage height, then it scrolls.
  // It steps out of the way of the floor tile (below it on narrow frames, beside it otherwise).
  const tileW = frameW * (frameW < PHONE ? 0.34 : 0.24);
  const cardW = Math.min(CARD_MAX, frameW);
  const clear = (frameW - cardW) / 2 >= tileW + INSET * 1.5;
  const shift = clear ? 0 : tileW * 0.625 + INSET * 2;
  const bigChat: MotionStyle = {
    position: "relative", width: cardW, minHeight: CARD_MIN, maxHeight: bigH, margin: "0 auto", zIndex: 0, overflow: "hidden", ...WHITE,
    marginTop: corner.startsWith("t") ? shift : 0, marginBottom: corner.startsWith("b") ? shift : 0,
  };

  const onDragEnd = () => {
    const f = frame.current?.getBoundingClientRect();
    const t = (swapped ? floorPane : chatPane).current?.getBoundingClientRect();
    if (f && t) dispatch({ type: "setCorner", x: t.left + t.width / 2 - f.left, y: t.top + t.height / 2 - f.top, w: f.width, h: f.height });
    x.set(0);
    y.set(0);
    setTimeout(() => { dragged.current = false; }, 0);
  };

  const swap = () => {
    if (dragged.current) return;
    dispatch({ type: "toggle" });
  };

  const swapButton = (label: string) => (
    <button
      type="button"
      aria-label={label}
      onClick={swap}
      className="absolute inset-0 z-10 cursor-pointer rounded-[inherit] bg-transparent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[#8fb0ff]"
    />
  );

  const tileProps = {
    drag: true,
    dragConstraints: frame,
    dragElastic: 0.1,
    dragMomentum: false,
    onDragStart: () => { dragged.current = true; },
    onDragEnd,
  } as const;

  return (
    <div ref={frame} className="relative w-full min-w-0 max-w-full">
      <motion.div ref={floorPane} layout layoutId="call-floor" transition={transition} style={swapped ? floorTile : bigFloor} {...(swapped ? tileProps : {})}>
        {floor(swapped)}
        {swapped && swapButton("Show floor full screen")}
      </motion.div>
      <motion.div ref={chatPane} layout layoutId="call-chat" transition={transition} style={swapped ? bigChat : chatTile} {...(swapped ? {} : { ...tileProps })}>
        <ChatPane lines={lines} live={live} mode={swapped ? "full" : "tile"} unread={unread} reducedMotion={reducedMotion} />
        {!swapped && swapButton("Show chat full screen")}
      </motion.div>
    </div>
  );
}
