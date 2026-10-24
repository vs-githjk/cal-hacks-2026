"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useReducedMotion } from "motion/react";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { Floor3D, hasWebGL } from "@/components/Floor3D";
import { Card, Code, Label, OriginChip, SourceLink } from "@/components/ui";
import { AGENTVERSE_URL, shortAddress, type AgentInfo } from "@/lib/agents";
import { POLL_MS, fetchAgents, type AgentStatus } from "@/lib/agentFeed";
import { agentFor, bubbleText, bubblesFrom, type AgentEventLike } from "@/lib/arenaAgents";
import { SAMPLES, SAMPLE_AGENT_LINES } from "@/lib/arenaFixture";
import { IDLE, playback, projectArenaScene, storyFor, type ActorKey, type ArenaRows, type ArenaScene, type Playback, type PlaybackAction, type SceneOffer, type Story } from "@/lib/arenaScene";
import type { ReasonCode } from "@/lib/bracket";
import { FIXED_ACTORS, actorFor } from "@/lib/floor";
import { formatMoney } from "@/lib/money";

type SampleName = keyof typeof SAMPLES;
const LEAD_MS = 1200; // the sealed table holds this long before a close starts to play
const SAMPLE_OPEN_LEFT_MS = 62_000; // a sample's open round counts down from here, since its recorded deadline is long past
const NO_SELLERS: ReadonlySet<string> = new Set();

/** The sealed-room scene: one round told as a short piece of theater. Every motion is a market row (see web/docs/3d-arena/DESIGN.md).
 * `?sample=gpu|gpu-open|ssd` shows a labelled SIM round instead of the market, and `&beat=N` stops it at beat N. */
export default function FloorPage() {
  // Read once on mount from window.location, not with useSearchParams (cacheComponents would demand a Suspense boundary for it).
  // The page only mounts in the browser (Providers renders no children on the server), so window is there.
  const [params] = useState(() => {
    const q = new URLSearchParams(window.location.search);
    const name = q.get("sample");
    const beat = q.get("beat");
    return {
      sample: name !== null && Object.hasOwn(SAMPLES, name) ? (name as SampleName) : null,
      beat: beat !== null && /^\d+$/.test(beat) ? Number(beat) : null,
    };
  });
  return <FloorView sample={params.sample} sampleBeat={params.beat} />;
}

const subscribeNever = () => () => {};
let webglCache: boolean | undefined;
/** null on the server and during hydration, then whether this browser can make a WebGL context (asked once). */
function useWebGL(): boolean | null {
  return useSyncExternalStore(subscribeNever, () => (webglCache ??= hasWebGL()), () => null);
}

function FloorView({ sample, sampleBeat }: { sample: SampleName | null; sampleBeat: number | null }) {
  const conn = useSpacetimeDB();
  const [rounds] = useTable(tables.round);
  const [needs] = useTable(tables.sellerNeeds);
  const [results] = useTable(tables.roundResult);
  const [agentRows] = useTable(tables.agentEvent);
  const [events] = useTable(tables.floorEvent);

  // A sample replaces the tables outright; nothing ever falls back to one on its own.
  const rows = useMemo<ArenaRows>(() => (sample ? SAMPLES[sample] : { rounds, needs, results, events }), [sample, rounds, needs, results, events]);
  const scene = useMemo(() => projectArenaScene(rows, { sample: sample !== null }), [rows, sample]);

  // ---- playback: display only
  // A sample is known at mount, so it starts in the state it should show: stopped at ?beat=N, or replaying from the sealed table.
  const [pb, setPb] = useState<Playback>(() => {
    if (!sample) return IDLE;
    const first = projectArenaScene(SAMPLES[sample], { sample: true });
    const there = playback(IDLE, { type: "scene" }, first);
    return playback(there, sampleBeat === null ? { type: "replay" } : { type: "seek", beat: sampleBeat }, first);
  });
  const act = useCallback((a: PlaybackAction) => setPb((s) => playback(s, a, scene)), [scene]);
  const reduced = useReducedMotion();
  // The new scene reaches playback in the same render (never a frame with the old round's beat), and reduced motion never plays.
  let view = playback(pb, { type: "scene" }, scene);
  if (reduced && view.playing) view = playback(view, { type: "skip" }, scene);
  if (view !== pb) setPb(view);

  const frozen = !sample && !conn.isActive;
  useEffect(() => {
    if (!view.playing || frozen) return;
    // Beat n plays for its own ms after it is applied; the sealed table holds a moment before the first one.
    const wait = view.beat === 0 ? LEAD_MS : (scene.beats[view.beat - 1]?.ms ?? 0);
    const t = setTimeout(() => act({ type: "tick" }), wait);
    return () => clearTimeout(t);
  }, [view.playing, view.beat, frozen, scene, act]);

  // ---- selection, WebGL, connection
  const [pickedState, setPickedState] = useState<{ roundId: string | null; key: string } | null>(null);
  const picked = pickedState && pickedState.roundId === scene.roundId ? pickedState.key : null;
  const setPicked = useCallback((key: string) => setPickedState({ roundId: scene.roundId, key }), [scene.roundId]);
  const webgl = useWebGL();
  const [unavailable, setUnavailable] = useState(false);
  const flat = webgl === false || unavailable;
  const [everActive, setEverActive] = useState(false);
  if (conn.isActive && !everActive) setEverActive(true);
  const disconnected = !sample && !conn.isActive;

  // Speech bubbles: the real agents' newest agent_event rows (live), or a sample's scripted SIM lines for whoever the current beat lights.
  const nowSec = useSyncExternalStore(sample || agentRows.length === 0 ? subscribeNever : subscribeSecond, nowSecond, nowSecond);
  const bubbleKey = JSON.stringify(
    sample
      ? Object.fromEntries(
          (scene.beats[view.beat - 1]?.focus ?? []).flatMap((k) => {
            const line = SAMPLE_AGENT_LINES[sample === "ssd" ? "ssd" : "gpu"][k]?.[0];
            return sample === "gpu-open" || !line ? [] : [[k, line]];
          }),
        )
      : bubblesFrom(agentRows, nowSec * 1000, scene),
  );
  const bubbles = useMemo(() => JSON.parse(bubbleKey) as Partial<Record<string, string>>, [bubbleKey]);

  const story = storyFor(scene, view);
  const reveal = revealAt(scene, view.beat);
  const total = scene.beats.length;

  const top = <StoryTop story={story} sample={sample !== null} deadline={scene.phase === "open" ? scene.deadline : null} />;
  const controls = total > 0 ? <Controls pb={view} total={total} story={story} act={act} /> : null;

  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="text-[18px] font-bold tracking-[-0.01em]">
          Floor <span className="font-medium text-muted">every motion is a market row</span>
        </div>
        <div className="text-[14px] text-muted">{sample ? "Sample run" : scene.roundId ? `Round ${scene.roundId}` : "No round"}</div>
      </div>
      <div className="grid gap-3.5 lg:grid-cols-[8fr_4fr]">
        {flat ? (
          <div className="grid min-w-0 content-start gap-3.5">
            {top}
            {controls}
            <ActorList scene={scene} reveal={reveal} picked={picked} onPick={setPicked} />
          </div>
        ) : (
          <div className="relative min-w-0">
            <div className="z-20 pointer-events-none pb-3 sm:absolute sm:inset-x-0 sm:top-0 sm:p-4">{top}</div>
            {webgl ? (
              <Floor3D scene={scene} beat={view.beat} frozen={frozen} reducedMotion={!!reduced} selected={picked} onPick={setPicked} bubbles={bubbles} onUnavailable={() => setUnavailable(true)} />
            ) : (
              <div className="grid h-[420px] place-items-center rounded-[var(--radius)] bg-canvas text-muted sm:h-[560px]">Loading the floor...</div>
            )}
            {controls && <div className="z-20 pointer-events-none pt-3 sm:absolute sm:inset-x-0 sm:bottom-0 sm:p-4">{controls}</div>}
            {disconnected && (
              <div className="absolute inset-0 z-30 grid place-items-center rounded-[var(--radius)] bg-canvas/70">
                {everActive ? (
                  <span className="rounded-lg bg-coral-soft px-3 py-2 font-semibold text-coral">market disconnected · the floor is still</span>
                ) : (
                  <span className="rounded-lg bg-soft px-3 py-2 font-semibold text-muted">Connecting...</span>
                )}
              </div>
            )}
          </div>
        )}
        <Card className="content-start">
          <Label>Offers</Label>
          <OffersList scene={scene} reveal={reveal} picked={picked} onPick={setPicked} />
          <Details scene={scene} reveal={reveal} events={rows.events} agentRows={agentRows} sample={sample} picked={picked} />
        </Card>
      </div>
    </div>
  );
}

const subscribeSecond = (cb: () => void) => {
  const id = setInterval(cb, 1000);
  return () => clearInterval(id);
};
const nowSecond = () => Math.floor(Date.now() / 1000);

const PILL = "shrink-0 rounded-full bg-white/95 px-3 py-1.5 text-[13px] font-medium tabular-nums text-[#2B2A33] shadow-[0_2px_8px_rgba(60,40,30,0.15)]";

/** "Closes in m:ss". Mounted only while a round is open, so the once-a-second tick runs only then. A sample counts down from a fixed 1:02,
 * because its recorded deadline is long past. */
function ClosesIn({ deadline, sample }: { deadline: Date; sample: boolean }) {
  const [mountedAt] = useState(() => Date.now());
  const now = useSyncExternalStore(subscribeSecond, nowSecond, nowSecond) * 1000;
  const left = Math.max(0, Math.ceil((sample ? SAMPLE_OPEN_LEFT_MS - Math.max(0, now - mountedAt) : deadline.getTime() - now) / 1000));
  return <p className={PILL}>Closes in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</p>;
}

/** Top left: the status line, the hero, the one-sentence caption and the quiet knockout note. Top right: the countdown while open. */
function StoryTop({ story, sample, deadline }: { story: Story; sample: boolean; deadline: Date | null }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 rounded-2xl bg-white p-4 sm:bg-white/90 text-[#2B2A33] shadow-[0_6px_24px_rgba(90,60,40,0.18)]">
        <p className="flex items-center gap-2 text-[13px] text-[#2B2A33]/70">
          {story.status}
          {sample && <span className="rounded-md border border-dashed border-[#2B2A33]/50 px-1.5 py-0.5 font-mono text-[11px] font-semibold leading-[1.5] tracking-[0.06em]">SIM</span>}
        </p>
        {story.hero && <p className="font-display text-[24px] leading-[1.1] sm:text-[30px]">{story.hero}</p>}
        <p role="status" className="mt-1 max-w-[52ch] text-[16px] leading-snug">{story.caption}</p>
        {story.note && <p className="mt-1.5 max-w-[52ch] text-[13px] leading-snug text-[#2B2A33]/70">{story.note}</p>}
      </div>
      {deadline && <ClosesIn deadline={deadline} sample={sample} />}
    </div>
  );
}

const BUTTON =
  "pointer-events-auto inline-flex min-h-11 items-center rounded-full bg-white/95 px-4 text-[14px] font-medium text-[#2B2A33] shadow-[0_2px_8px_rgba(60,40,30,0.15)] hover:bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2F3E66] disabled:cursor-not-allowed disabled:opacity-50";

/** Bottom left: Pause or Play, Replay, Skip to result. Bottom right: where the close is. */
function Controls({ pb, total, story, act }: { pb: Playback; total: number; story: Story; act: (a: PlaybackAction) => void }) {
  const done = pb.beat >= total;
  const place = [story.stage, story.step].filter(Boolean).join(", ");
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <div className="flex flex-wrap gap-2">
        {pb.playing ? (
          <button type="button" className={BUTTON} onClick={() => act({ type: "pause" })}>Pause</button>
        ) : (
          <button type="button" className={BUTTON} disabled={done} onClick={() => act({ type: "resume" })}>Play</button>
        )}
        <button type="button" className={BUTTON} onClick={() => act({ type: "replay" })}>Replay</button>
        <button type="button" className={BUTTON} disabled={done} onClick={() => act({ type: "skip" })}>Skip to result</button>
      </div>
      {place && <p className={PILL}>{place}</p>}
    </div>
  );
}

/** The word for how an offer ended: from the referee's reason, never from color. */
function outcomeWord(o: SceneOffer): string {
  if (o.outcome === "winner") return "Winner";
  if (o.outcome === "ranked") return `Ranked #${o.rank}`;
  const code: ReasonCode | undefined = o.knock?.reasonCode;
  return code === "shield_block" ? "Blocked" : code === "advocate_veto" || code === "claim_false" ? "Vetoed" : "Refused";
}

/** How much of a closing round the side card may show at this beat, so it never gets ahead of the story: prices open with the offers,
 * a refusal shows at its own beat, and ranks and the winner wait for the final frame. Open and closing rounds show nothing. */
interface Reveal { opened: boolean; shown: (o: SceneOffer) => boolean }
function revealAt(scene: ArenaScene, beat: number): Reveal {
  const done = scene.phase === "closed" || scene.phase === "inconsistent";
  const final = done && beat >= scene.beats.length;
  const applied = scene.beats.slice(0, beat);
  return {
    opened: done && (final || beat >= 1),
    shown: (o) => final || (o.outcome === "knocked" && applied.some((b) => b.knocked.some((k) => k.id === o.bidId))),
  };
}

const sealedLine = (n: number) => `${n === 0 ? "No sealed offers yet" : `${n} sealed offer${n === 1 ? "" : "s"}`}. Prices stay sealed until the round closes.`;

/** The Offers card body: sealed envelopes before close, the referee's order after. */
function OffersList({ scene, reveal, picked, onPick }: { scene: ArenaScene; reveal: Reveal; picked: string | null; onPick: (key: string) => void }) {
  if (scene.phase === "waiting") return <p className="text-muted">No round yet.</p>;
  if (scene.phase === "open" || scene.phase === "closing") return <p className="text-muted">{sealedLine(scene.sealedCount)}</p>;
  if (!reveal.opened) return <p className="text-muted">{scene.sealedCount} sealed offer{scene.sealedCount === 1 ? "" : "s"}. Prices appear as the referee opens them.</p>;
  if (scene.offers.length === 0) {
    return <p className="text-muted">{scene.phase === "inconsistent" ? "The result rows disagree, so no winner is shown." : "No offer passed the checks, so nobody won this round."}</p>;
  }
  return (
    <>
      {scene.phase === "inconsistent" && <p className="mb-2 text-muted">The result rows disagree, so no winner is shown.</p>}
      <p className="mb-1 text-[12px] text-muted">Prices are before sales tax.</p>
      <ul className="grid gap-1">
        {scene.offers.map((o) => {
          const shown = reveal.shown(o);
          const out = shown && o.outcome === "knocked";
          return (
            <li key={o.key}>
              <button
                type="button"
                onClick={() => onPick(o.key)}
                aria-pressed={picked === o.key}
                className={`grid min-h-11 w-full grid-cols-[3.25rem_minmax(0,1fr)_auto] items-start gap-x-2 rounded-lg px-2 py-2 text-left hover:bg-soft ${shown && o.outcome === "winner" ? "bg-mint-soft" : ""} ${picked === o.key ? "ring-1 ring-ink" : ""}`}
              >
                <span className="pt-0.5 text-[12px] tabular-nums text-muted">{shown ? (o.rank ? `#${o.rank}` : "No rank") : ""}</span>
                <span className="min-w-0">
                  <span className={`font-semibold ${out ? "line-through" : ""}`}>{o.name}</span> <OriginChip origin={o.origin} />
                  {o.condition && <span className="block text-[12px] text-muted">{o.condition}</span>}
                  {out && o.knock && <span className="block text-[13px] text-muted [overflow-wrap:anywhere]">{o.knock.reasonText}</span>}
                </span>
                <span className="text-right">
                  <span className="block tabular-nums">{formatMoney(o.landed)}</span>
                  {shown && <span className="block text-[12px] text-muted">{outcomeWord(o)}</span>}
                </span>
              </button>
              {out && o.sourceUrl && <div className="px-2 pb-1.5 pl-[3.75rem]"><SourceLink href={o.sourceUrl} /></div>}
            </li>
          );
        })}
      </ul>
    </>
  );
}

const ROLE: Record<string, string> = { buyer: "Buyer agent", advocate: "Advocate", shield: "Bazaar Shield", referee: "Referee" };

/** The selected actor: its name and kind, its round_result row (offers), and the floor_event rows behind it. */
const STATUS_WORD: Record<AgentStatus, string> = { agentverse: "On Agentverse", local: "Running locally", down: "Down" };

/** Live status from the agent feed, polled only while `address` is set (an agent is selected, not a sample). null until the first answer; "Status unknown" when the feed is unreachable. */
function useAgentStatus(address: string | null): string | null {
  const [seen, setSeen] = useState<{ address: string; text: string } | null>(null);
  useEffect(() => {
    if (!address) return;
    let live = true;
    const ctl = new AbortController();
    const poll = async () => {
      const feed = await fetchAgents(ctl.signal);
      const mine = feed?.find((r) => r.address === address);
      if (live) setSeen({ address, text: mine ? STATUS_WORD[mine.status] : "Status unknown" });
    };
    void poll();
    const id = setInterval(poll, POLL_MS);
    return () => { live = false; ctl.abort(); clearInterval(id); };
  }, [address]);
  return address && seen?.address === address ? seen.text : null;
}

/** The Fetch.ai agent behind the selected actor: who it is, where to see it, whether it is up, and what it said last. */
function AgentPanel({ info, pending, sample, agentRows, line }: { info: AgentInfo | null; pending: boolean; sample: boolean; agentRows: readonly AgentEventLike[]; line: string | undefined }) {
  const status = useAgentStatus(info && !sample ? info.address : null);
  if (!info) return pending ? <p className="mt-3 text-[14px] text-muted">Fetch.ai seller agent, no Agentverse address on file.</p> : null;
  const last = agentRows
    .filter((r) => r.address === info.address)
    .reduce<AgentEventLike | null>((a, r) => (!a || r.ts.microsSinceUnixEpoch > a.ts.microsSinceUnixEpoch ? r : a), null);
  return (
    <div className="mt-3 rounded-lg bg-soft p-3 text-[14px]">
      <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">Fetch.ai agent</p>
      <p className="mt-1 font-semibold">{info.name} <span className="font-normal text-muted">{info.handle}</span></p>
      <p className="font-mono text-[12px] text-muted">{shortAddress(info.address)}</p>
      <p className="mt-1"><SourceLink href={AGENTVERSE_URL(info.address)}>View on Agentverse</SourceLink></p>
      {!sample && <p className="mt-1.5">{status ?? "Checking status..."}</p>}
      {sample ? (
        line && <p className="mt-1.5 [overflow-wrap:anywhere]">{line} <OriginChip origin="SIM" /></p>
      ) : (
        last && <p className="mt-1.5 [overflow-wrap:anywhere]">{bubbleText(last.text)}</p>
      )}
    </div>
  );
}

function Details({ scene, reveal, events, agentRows, sample, picked }: { scene: ArenaScene; reveal: Reveal; events: ArenaRows["events"]; agentRows: readonly AgentEventLike[]; sample: SampleName | null; picked: string | null }) {
  const agent = picked ? agentFor(picked as ActorKey, scene) : null;
  const pending = !agent && !!picked && /^seller_\d+$/.test(scene.offers.find((o) => o.key === picked)?.sellerId ?? "");
  const sampleLine = sample && sample !== "gpu-open" ? SAMPLE_AGENT_LINES[sample === "ssd" ? "ssd" : "gpu"][picked ?? ""]?.[0] : undefined;
  const offer = picked && reveal.opened ? scene.offers.find((o) => o.key === picked) : undefined;
  const fixed = picked ? FIXED_ACTORS.find((a) => a.key === picked) : undefined;
  const linked = useMemo(() => {
    if (!fixed) return [];
    const mine = new Set([scene.roundId ?? "", ...scene.offers.map((o) => o.bidId)]);
    return events
      .filter((e) => mine.has(e.refId) && actorFor(e, NO_SELLERS) === fixed.key)
      .sort((a, b) => (a.id < b.id ? 1 : -1))
      .slice(0, 4)
      .map((e) => ({ id: String(e.id), kind: e.kind, label: e.label, origin: e.origin }));
  }, [fixed, events, scene]);

  return (
    <div className="mt-4 border-t border-line pt-3">
      {!offer && !fixed ? (
        <p className="text-[14px] text-muted">Pick a character or an offer to see the market rows behind it.</p>
      ) : (
        <>
          <p className="mb-1.5 font-semibold">{offer ? offer.name : fixed!.name}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[14px]">
            <dt className="text-muted">Kind</dt><dd>{offer ? "Seller offer" : ROLE[fixed!.key]}</dd>
            {offer && (
              <>
                <dt className="text-muted">Row</dt><dd><Code>{offer.rowRef}</Code></dd>
                <dt className="text-muted">Product</dt><dd>{offer.product || "not stated"}</dd>
                {reveal.shown(offer) && <><dt className="text-muted">Outcome</dt><dd>{outcomeWord(offer)}</dd></>}
              </>
            )}
          </dl>
          <AgentPanel info={agent} pending={pending} sample={sample !== null} agentRows={agentRows} line={sampleLine} />
          <EventRows rows={offer ? offer.events : linked} />
        </>
      )}
    </div>
  );
}

function EventRows({ rows }: { rows: { id: string; kind: string; label: string; origin: string }[] }) {
  if (rows.length === 0) return <p className="mt-2 text-[14px] text-muted">No floor_event rows are linked to it yet.</p>;
  return (
    <ul className="mt-2 grid gap-1.5 text-[14px]">
      {rows.map((e) => (
        <li key={e.id} className="grid gap-0.5">
          <span><Code>floor_event/{e.id}</Code> <span className="font-mono text-[12px] text-muted">{e.kind}</span></span>
          <span className="[overflow-wrap:anywhere]">{e.label} <OriginChip origin={e.origin} /></span>
        </li>
      ))}
    </ul>
  );
}

/** The flat view when WebGL is missing or fails: the four fixed characters and every offer, each with what it did. */
function ActorList({ scene, reveal, picked, onPick }: { scene: ArenaScene; reveal: Reveal; picked: string | null; onPick: (key: string) => void }) {
  const sealed = reveal.opened ? 0 : Math.min(scene.sealedCount, 12); // until the referee opens them, an offer is only an envelope
  const row = "grid min-h-11 w-full grid-cols-[1fr_auto] items-baseline gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-soft";
  return (
    <Card>
      <Label>Characters (flat view, no WebGL)</Label>
      <ul className="grid gap-1 sm:grid-cols-2">
        {FIXED_ACTORS.map((a) => (
          <li key={a.key}>
            <button type="button" onClick={() => onPick(a.key)} aria-pressed={picked === a.key} className={`${row} ${picked === a.key ? "ring-1 ring-ink" : ""}`}>
              <span className="min-w-0"><b className="font-semibold">{a.name}</b> <OriginChip origin={a.origin} /></span>
              <span className="text-[12px] text-muted">{ROLE[a.key]}</span>
            </button>
          </li>
        ))}
        {reveal.opened && scene.offers.map((o) => (
          <li key={o.key}>
            <button type="button" onClick={() => onPick(o.key)} aria-pressed={picked === o.key} className={`${row} ${reveal.shown(o) && o.outcome === "winner" ? "bg-mint-soft" : ""} ${picked === o.key ? "ring-1 ring-ink" : ""}`}>
              <span className="min-w-0">
                <b className={`font-semibold ${reveal.shown(o) && o.outcome === "knocked" ? "line-through" : ""}`}>{o.name}</b> <OriginChip origin={o.origin} />
                {agentFor(o.key, scene) && <span className="ml-1.5 text-[12px] text-muted">Fetch.ai</span>}
              </span>
              <span className="text-right text-[13px] tabular-nums">{formatMoney(o.landed)} {reveal.shown(o) && <span className="text-muted">{outcomeWord(o)}</span>}</span>
            </button>
          </li>
        ))}
        {Array.from({ length: sealed }, (_, i) => (
          <li key={`sealed-${i}`} className={`${row} cursor-default`}>
            <span className="min-w-0 font-semibold">Offer {i + 1}</span>
            <span className="text-[13px] text-muted">Sealed</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
