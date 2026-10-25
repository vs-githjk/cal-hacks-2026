"use client";

import { AgentAvatar, AgentProfiles, useAgents } from "@/components/useAgents";
import { Card, Code, Label, OriginChip, Tag } from "@/components/ui";
import { shortAddress } from "@/lib/agents";
import { ASI_ONE_URL, STATUS_TEXT, agentLink, ago, headline, isStale, realRows, type AgentRow, type AgentStatus } from "@/lib/agentFeed";

const DOT: Record<AgentStatus, string> = { agentverse: "bg-mint", local: "bg-sky", down: "bg-coral" };

function AgentCard({ r, now }: { r: AgentRow; now: number }) {
  const link = agentLink(r);
  const age = ago(r.at, now);
  return (
    <li>
      <Card className="h-full">
        <div className="flex items-center gap-3">
          <AgentAvatar row={r} size={40} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[16px] font-semibold">{r.name}</p>
            <p className="flex items-center gap-1.5 text-[13px] text-muted">
              <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[r.status]}`} aria-hidden />
              {STATUS_TEXT[r.status]}
            </p>
          </div>
          <OriginChip origin={r.origin} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Tag>{r.role}</Tag>
          {r.address ? <Code>{shortAddress(r.address)}</Code> : <span className="text-[13px] text-muted">No address recorded</span>}
        </div>
        <p className="mt-3 break-words text-[14px]">{r.last_message ?? <span className="text-muted">No messages recorded yet.</span>}</p>
        <p className="mt-1 text-[13px] text-muted">{age ? `${age}${isStale(r.at, now) ? " (stale)" : ""}` : r.last_message ? "Time not recorded" : ""}</p>
        {link && (
          <a href={link} target="_blank" rel="noreferrer" className="mt-1 inline-flex min-h-11 items-center text-[14px] text-sky underline underline-offset-4">
            Agentverse profile
          </a>
        )}
      </Card>
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
        <Label>Fetch agents</Label>
        <p className="text-[22px] font-medium text-balance">{noFeed ? "Fetch agents on Agentverse" : headline(rows ? shown : rows, now)}</p>
        <p className="mt-2 text-[13px] text-muted">
          Status is read from the launcher run log, not checked live from this page. An address or a published profile alone does not mean an agent is online.
        </p>
        <a href={ASI_ONE_URL} target="_blank" rel="noreferrer" className="mt-1 inline-flex min-h-11 items-center text-[14px] text-sky underline underline-offset-4">
          Open in ASI:One
        </a>
      </Card>
      {noFeed ? (
        <Card>
          <p className="text-[14px] text-muted">No live agent feed on this site. Each agent's public Agentverse profile:</p>
          <AgentProfiles className="text-[14px]" />
        </Card>
      ) : rows === undefined ? (
        <p className="text-muted">Checking the agent feed...</p>
      ) : rows === null ? (
        <p className="text-muted">The agent feed is not answering, so no agent rows are shown. Start it with python3 scripts/launch.py up.</p>
      ) : shown.length === 0 ? (
        <p className="text-muted">No agents are running. Start them with python3 scripts/launch.py up.</p>
      ) : (
        <ul className="grid gap-3.5 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((r) => (
            <AgentCard key={`${r.role}-${r.name}`} r={r} now={now} />
          ))}
        </ul>
      )}
    </div>
  );
}
