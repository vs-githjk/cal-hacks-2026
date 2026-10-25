"use client";

import { AgentWire } from "@/components/AgentWire";
import { AgentAvatar, AgentProfiles, useAgents } from "@/components/useAgents";
import { Card, Code, Label, OriginChip, Tag } from "@/components/ui";
import { shortAddress } from "@/lib/agents";
import { ASI_ONE_URL, STATUS_TEXT, agentLink, ago, headline, isStale, realRows, type AgentRow, type AgentStatus } from "@/lib/agentFeed";

const DOT: Record<AgentStatus, string> = { agentverse: "bg-mint-mark", local: "bg-live", down: "bg-coral-mark" };
const RING: Record<AgentStatus, string> = { agentverse: "border-mint-mark", local: "border-live", down: "border-coral-mark" };

function AgentCard({ r, now }: { r: AgentRow; now: number }) {
  const link = agentLink(r);
  const age = ago(r.at, now);
  return (
    <li className="grid grid-cols-[36px_minmax(0,1fr)] items-start gap-x-3 gap-y-1 border-t border-line py-3 first:border-t-0 sm:grid-cols-[36px_minmax(0,1fr)_auto]">
      <span className={`rounded-full border-2 ${RING[r.status]} inline-flex`}>
        <AgentAvatar row={r} size={32} />
      </span>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px]/[20px] font-medium">
          <span className="truncate">{r.name}</span>
          <OriginChip origin={r.origin} />
        </p>
        <p className="flex items-center gap-1.5 text-[13px]/[18px] text-muted">
          <span className={`size-2 shrink-0 rounded-full ${DOT[r.status]}`} aria-hidden />
          {STATUS_TEXT[r.status]}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Tag>{r.role}</Tag>
          {r.address ? <Code>{shortAddress(r.address)}</Code> : <span className="text-[13px] text-muted">No address recorded</span>}
        </div>
        <p className="mt-2 break-words text-[13px]/[18px] text-ink-2">{r.last_message ?? <span className="text-muted">No messages recorded yet.</span>}</p>
        {link && (
          <a href={link} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center text-[14px] font-medium text-pulse underline underline-offset-4">
            Agentverse profile
          </a>
        )}
      </div>
      <p className="col-start-2 font-mono text-[12px]/[16px] text-muted sm:col-start-3 sm:row-start-1 sm:text-right">{age ? `${age}${isStale(r.at, now) ? " (stale)" : ""}` : r.last_message ? "Time not recorded" : ""}</p>
    </li>
  );
}

/** The agent directory, reached from the Fetch tile. Same feed and the same single poll as the tile. */
export default function AgentsPage() {
  const { rows, now, noFeed } = useAgents();
  const shown = rows ? realRows(rows) : [];
  return (
    <div className="grid gap-3.5">
      <Card>
        <Label>Agents</Label>
        <p className="text-[22px]/[28px] font-semibold tracking-[-0.01em] text-balance">{noFeed ? "Fetch agents on Agentverse" : headline(rows ? shown : rows, now)}</p>
        <p className="mt-2 text-[13px] text-muted">Status comes from the run log, not a live check.</p>
        <a href={ASI_ONE_URL} target="_blank" rel="noreferrer" className="mt-1 inline-flex min-h-11 items-center text-[14px] font-medium text-pulse underline underline-offset-4">
          Open in ASI:One
        </a>
      </Card>
      <AgentWire />
      {noFeed ? (
        <Card>
          <p className="text-[14px] text-muted">No live feed here. Public profiles:</p>
          <AgentProfiles className="text-[14px]" />
        </Card>
      ) : rows === undefined ? (
        <p className="text-muted">Checking the agent feed...</p>
      ) : rows === null ? (
        <p className="text-muted">The agent feed is not answering.</p>
      ) : shown.length === 0 ? (
        <p className="text-muted">No agents are running.</p>
      ) : (
        <Card>
          <ul>
            {shown.map((r) => (
              <AgentCard key={`${r.role}-${r.name}`} r={r} now={now} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
