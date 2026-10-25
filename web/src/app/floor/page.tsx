"use client";

import { useState } from "react";
import ArenaView from "@/components/floor/ArenaView";
import { RingFloor } from "@/components/floor/FloorView";

type View = "ring" | "arena";

/** /floor: the 2.5D boxing ring by default; the arena view (the board and the 3D scene) stays one tap away, and ?view=arena opens it directly. */
export default function FloorPage() {
  // Read once on mount from window.location (the page only mounts in the browser, see Providers).
  const [view, setView] = useState<View>(() => (new URLSearchParams(window.location.search).get("view") === "arena" ? "arena" : "ring"));
  const pick = (v: View) => {
    setView(v);
    const u = new URL(window.location.href);
    if (v === "arena") u.searchParams.set("view", "arena");
    else u.searchParams.delete("view");
    window.history.replaceState(null, "", u);
  };
  const tab = (v: View, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={view === v}
      onClick={() => pick(v)}
      className={`min-h-11 rounded-full px-4 text-[14px] font-medium ${view === v ? "bg-[#1e4ed8] text-white" : "text-[#5b6b7c] hover:bg-[#eef3f8]"}`}
    >
      {label}
    </button>
  );
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[18px] font-semibold tracking-[-0.01em]">
          Floor <span className="font-normal text-[#5b6b7c]">the buyer against the sellers, one part at a time</span>
        </div>
        <div role="tablist" aria-label="Floor view" className="inline-flex gap-1 rounded-full border border-[#e3e8ef] bg-white p-1">
          {tab("ring", "Ring")}
          {tab("arena", "Arena board")}
        </div>
      </div>
      {view === "ring" ? <RingFloor /> : <ArenaView />}
    </div>
  );
}
