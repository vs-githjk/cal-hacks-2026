"use client";
// Four scoreboard tiles from data/scoreboard.json (via /api/scoreboard). A tile with no trustworthy number shows its status.
import { useEffect, useState } from "react";
import { scoreboardTiles, type TileView } from "@/lib/scoreboard";
import { OriginChip } from "./ui";

export function ScoreboardTiles() {
  const [tiles, setTiles] = useState<TileView[] | null>(null);
  useEffect(() => {
    let live = true;
    fetch("/api/scoreboard")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => live && setTiles(scoreboardTiles(j)))
      .catch(() => live && setTiles([]));
    return () => { live = false; };
  }, []);
  if (tiles === null) return <p className="text-[13px] text-muted">Loading the scoreboard...</p>;
  if (tiles.length === 0) return <p className="text-[13px] text-muted">No scoreboard yet. Lane C writes data/scoreboard.json from its source runs.</p>;
  return (
    <section aria-label="Scoreboard" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map((t) => (
        <article key={t.id} className="card grid min-w-0 content-start gap-2 p-[18px]">
          <header className="flex items-start justify-between gap-2">
            <h2 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">{t.title}</h2>
            <OriginChip origin={t.origin} />
          </header>
          {t.value !== null ? (
            <p className="text-[28px] font-semibold leading-none tracking-[-0.01em] tabular-nums">{t.value}</p>
          ) : (
            <p className="text-[18px] font-semibold leading-tight text-muted">{t.statusText}</p>
          )}
          <p className="text-[13px] leading-[1.45]">{t.display}</p>
          <p className="font-mono text-[11px] text-muted">n = {t.count} · {t.range}</p>
        </article>
      ))}
    </section>
  );
}
