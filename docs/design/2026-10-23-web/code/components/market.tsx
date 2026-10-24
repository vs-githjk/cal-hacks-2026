// web/src/components/market.tsx
// The referee's floor: sealed round timeline, bids per seller line, loss reports, learning diff, events feed.
import type { FloorEventView, LearningView, LossReport, RoundView, SellerLine } from "@/lib/screens";
import { Card, Label, OriginChip, Stat, Tag, Verdict, clock, money } from "./ui";

/** Horizontal track from 0 to close. Labels rotate over three rows so eleven arrivals never collide. */
export function RoundTimeline({ round }: { round: RoundView }) {
  const total = Math.max(round.closedMs, round.windowMs);
  const pct = (ms: number) => `${(ms / total) * 100}%`;
  const rows = ["bottom-5", "top-5", "top-9"]; // label offsets, cycling
  return (
    <Card>
      <Label>
        Sealed round · {round.sealedCount} bids · opened {clock(round.openedAt)} ·{" "}
        {round.state === "closed" ? `closed at ${(round.closedMs / 1000).toFixed(1)} s${round.extensions ? ` after ${round.extensions} extension${round.extensions > 1 ? "s" : ""}` : ""}` : "open"}
      </Label>
      {round.arrivals.length === 0 ? (
        <p className="text-muted">Round open. Bids arrive sealed; the track fills as they land.</p>
      ) : (
        <div className="relative my-3 h-[104px]">
          <div className="absolute inset-x-0 top-10 h-1 rounded-sm bg-line" />
          {round.closedMs > round.windowMs && <div className="absolute top-10 h-1 rounded-sm bg-amber opacity-50" style={{ left: pct(round.windowMs), right: 0 }} />}
          {round.arrivals.map((a, i) => (
            <div
              key={a.label + a.atMs}
              className={`absolute top-[34px] h-4 w-4 -translate-x-1/2 rounded-full border-[3px] bg-panel ${a.refused ? "border-coral" : a.origin === "SIM" ? "border-amber" : a.origin === "LIVE" ? "border-mint" : "border-sky"}`}
              style={{ left: pct(a.atMs) }}
              title={`${a.label} at ${(a.atMs / 1000).toFixed(1)} s (${a.origin}${a.refused ? ", refused" : ""})`}
            >
              <span className={`absolute left-1/2 -translate-x-1/2 whitespace-nowrap font-mono text-[11px] text-muted ${rows[i % 3]}`}>{a.label}</span>
            </div>
          ))}
          <div className="absolute top-[22px] h-10 w-0.5 -translate-x-1/2 bg-ink" style={{ left: pct(round.windowMs) }}>
            <span className="absolute -top-5 left-1 whitespace-nowrap text-[11px] font-semibold tracking-[0.04em]">deadline {round.windowMs / 1000} s</span>
          </div>
          {round.state === "closed" && (
            <div className="absolute top-[22px] h-10 w-0.5 -translate-x-1/2 bg-ink" style={{ left: "100%" }}>
              <span className="absolute -top-5 right-1 whitespace-nowrap text-[11px] font-semibold tracking-[0.04em]">close {(round.closedMs / 1000).toFixed(0)} s</span>
            </div>
          )}
          {[0, total / 2, round.windowMs].map((ms) => (
            <span key={ms} className="absolute -bottom-1.5 -translate-x-1/2 font-mono text-[11px] text-muted" style={{ left: pct(ms) }}>{(ms / 1000).toFixed(0)} s</span>
          ))}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-3.5 text-[12px] text-muted">
        <span><Dot className="border-sky" /> MIRROR bid</span>
        <span><Dot className="border-amber" /> SIM bid</span>
        <span><Dot className="border-mint" /> LIVE bid</span>
        <span><Dot className="border-coral" /> refused by referee</span>
        <span>Nobody saw a bid before close: buyer {round.seenBeforeClose.buyer}, public {round.seenBeforeClose.public}, each seller its own</span>
      </div>
    </Card>
  );
}

function Dot({ className }: { className: string }) {
  return <i className={`mr-1 inline-block h-2.5 w-2.5 rounded-full border-2 align-[-1px] ${className}`} aria-hidden />;
}

export function RefereeCard({ round, lines }: { round: RoundView; lines: SellerLine[] }) {
  const passed = lines.filter((l) => l.referee === "passed").length;
  const winner = lines.find((l) => l.outcome.kind === "won");
  const vetoes = lines.filter((l) => l.outcome.kind === "veto").length;
  return (
    <Card>
      <Label>Referee</Label>
      <dl className="grid grid-cols-2 gap-2.5">
        <Stat label="Sealed" value={String(round.sealedCount)} />
        <Stat label="Passed floor" value={String(passed)} />
        <Stat label="Lines refused" value={String(lines.length - passed)} />
        <Stat label="Winner" value={winner?.outcome.rank ? `#${winner.outcome.rank}` : "none"} sub={winner && vetoes ? `after ${vetoes} veto${vetoes > 1 ? "es" : ""}` : undefined} />
      </dl>
      <p className="mt-2.5 text-[13px] text-muted">One flat fee for everyone. No pay for rank. The advocate never sees the fee.</p>
    </Card>
  );
}

/** Bar is landed price against the cap, so a judge sees "cheap but vetoed" and "over cap" at a glance. */
export function SellerLines({ lines, cap }: { lines: SellerLine[]; cap: number }) {
  return (
    <Card>
      <Label>Bids per seller line · bar is landed price against the {money(cap)} cap</Label>
      {lines.length === 0 ? (
        <p className="text-muted">No lines yet. Each seller may bid several condition lines (new, open-box) for the same SKU.</p>
      ) : (
        <div className="-mx-[18px] overflow-x-auto px-[18px]">
          <table className="w-full border-collapse text-[14px] tabular-nums">
            <thead>
              <tr>
                <Th>Seller</Th><Th>Line</Th><Th right>Landed</Th><Th className="w-[28%]">vs cap</Th><Th>Referee</Th><Th>Advocate</Th><Th>#</Th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => {
                const o = l.outcome;
                const dim = o.kind === "ineligible" || o.kind === "refused" || o.kind === "alt";
                const fill = o.kind === "won" ? "bg-mint" : dim ? "bg-slate opacity-50" : l.origin === "SIM" ? "bg-amber" : l.origin === "LIVE" ? "bg-mint" : "bg-sky";
                return (
                  <tr key={i} className={o.kind === "won" ? "bg-mint-soft" : dim ? "text-muted" : ""}>
                    <Td><span className="font-semibold text-ink">{l.seller}</span> <OriginChip origin={l.origin} /></Td>
                    <Td><Tag>{l.condition}</Tag>{o.kind === "alt" && <span className="ml-1.5 text-[13px] text-muted">alt</span>}</Td>
                    <Td right>{o.kind === "won" ? <b>{money(l.landed)}</b> : money(l.landed)}</Td>
                    <Td>
                      <div className="relative h-2.5 min-w-[120px] rounded-[5px] bg-soft">
                        <b className={`absolute inset-y-0 left-0 rounded-[5px] ${fill}`} style={{ width: `${Math.min(100, (l.landed / cap) * 100)}%` }} />
                        {l.landed > cap && <i className="absolute -top-[3px] h-4 w-0.5 bg-ink" style={{ left: "100%" }} title="over cap" />}
                      </div>
                    </Td>
                    <Td>{l.referee === "passed" ? "passed" : <><Verdict kind="veto">refused</Verdict> <span className="text-[13px] text-muted">{l.refereeReason}</span></>}</Td>
                    <Td>
                      {o.kind === "won" && <Verdict kind="caution">caution</Verdict>}
                      {o.kind === "ranked" && <Verdict kind="buy">buy</Verdict>}
                      {o.kind === "veto" && <><Verdict kind="veto">veto</Verdict> <span className="text-[13px] text-muted">{o.note}</span></>}
                      {(o.kind === "ineligible" || o.kind === "alt") && <span className="text-[13px] text-muted">{o.kind === "alt" ? o.note : `ineligible, ${o.note}`}</span>}
                      {o.kind === "refused" && <span className="text-[13px] text-muted">never seen</span>}
                    </Td>
                    <Td className="font-mono font-semibold text-muted">{o.rank ? `${o.rank}${o.kind === "won" ? ", won" : ""}` : o.kind === "ineligible" ? "out" : "·"}</Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Th({ children, right, className = "" }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <th className={`whitespace-nowrap border-b border-line px-2.5 pb-2 pt-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-muted ${right ? "text-right" : "text-left"} ${className}`}>{children}</th>;
}
function Td({ children, right, className = "" }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={`border-b border-line p-2.5 align-top ${right ? "whitespace-nowrap text-right" : ""} ${className}`}>{children}</td>;
}

const BAND: Record<string, string> = { within5: "within 5%", within10: "within 10%", within20: "within 20%" };

export function LossReports({ reports, note }: { reports: LossReport[]; note?: string }) {
  return (
    <Card>
      <Label>Loss reports · round 1 · {reports.length} sellers</Label>
      {reports.length === 0 ? (
        <p className="text-muted">Sent to every losing seller when the round closes: the gap in bands, the reason, the source.</p>
      ) : (
        <div className="-mx-[18px] overflow-x-auto px-[18px]">
          <table className="w-full border-collapse text-[14px]">
            <thead><tr><Th>Seller</Th><Th>Gap</Th><Th>Reason</Th><Th>Source</Th></tr></thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.seller}>
                  <Td><span className="font-semibold">{r.seller}</span> <OriginChip origin={r.origin} /></Td>
                  <Td><span className="rounded-md bg-slate-soft px-1.5 py-0.5 font-mono text-[11px] text-slate">{BAND[r.gapBand] ?? r.gapBand}</span></Td>
                  <Td>{r.reason.replaceAll("_", " ")}</Td>
                  <Td className="text-[13px] text-muted [overflow-wrap:anywhere]">{r.sourceUrl.replace(/^https?:\/\/(www\.)?/, "").split("?")[0]}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {note && <p className="mt-2.5 text-[13px] text-muted">{note}</p>}
    </Card>
  );
}

export function SellerLearns({ learning }: { learning: LearningView | null }) {
  if (!learning) return <Card><Label>Seller learns</Label><p className="text-muted">After the round, one losing seller updates its strategy. The diff shows here.</p></Card>;
  return (
    <Card>
      <Label>Seller learns · {learning.seller} <OriginChip origin={learning.origin} /></Label>
      <div className="rounded-xl border-l-[3px] border-accent bg-soft px-3.5 py-3 text-[15px]">
        "{learning.whatToChange}"
        <small className="mt-1 block text-[12px] text-muted">Claude's one line to the owner ({learning.whatToChangeOrigin} in this run)</small>
      </div>
      <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 font-mono text-[13px]">
        {learning.diff.map((d) => (
          <div key={d.key} className="contents">
            <dt className="text-muted">{d.key}</dt>
            <dd><span className="text-coral line-through">{d.from}</span> → <span className="font-semibold text-mint">{d.to}</span>{d.note && <span className="ml-2 font-sans text-muted">{d.note}</span>}</dd>
          </div>
        ))}
        <dt className="text-muted">control</dt><dd className="font-sans">{learning.control}</dd>
      </dl>
      <p className="mt-2.5 text-[13px] text-muted">One deterministic, replayable diff. No trend claim.</p>
    </Card>
  );
}

const KIND_STYLE: Record<string, string> = {
  payment_recorded: "text-mint", auction_closed: "text-mint", bid_sealed: "text-sky", bid_rejected: "text-sky", verdict: "text-coral",
};

export function FloorEvents({ events, max = 60 }: { events: FloorEventView[]; max?: number }) {
  return (
    <Card>
      <Label>Floor events</Label>
      {events.length === 0 ? (
        <p className="text-muted">No events yet. Every reducer that moves the round writes one line here.</p>
      ) : (
        <ol className="grid">
          {events.slice(0, max).map((e) => (
            <li key={e.key} className="grid grid-cols-[72px_1fr] items-baseline gap-2.5 border-b border-line py-2 text-[14px] last:border-b-0">
              <span className="font-mono text-[12px] text-muted">{clock(e.at)}</span>
              <span>
                <span className={`mb-px block text-[11px] font-bold uppercase tracking-[0.06em] ${KIND_STYLE[e.kind] ?? "text-muted"}`}>{e.kind}</span>
                {e.label} <OriginChip origin={e.origin} /> <span className="font-mono text-[11px] text-muted">{e.ref}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
