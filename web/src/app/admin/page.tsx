"use client";

import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { SIM_AGENT_EVENTS, SIM_TELEMETRY, canSeeAdmin, parseAgentEvents, parseTelemetry } from "@/lib/admin";

/** Operator only: telemetry counts, no money, price, phone or name. Telemetry is not mounted (nothing fetched) unless the role allows it. */
export default function AdminPage() {
  const conn = useSpacetimeDB();
  const [roles, rolesReady] = useTable(tables.myRole);
  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      {!conn.isActive || !rolesReady ? (
        <p className="text-sm text-muted">Checking access</p>
      ) : !canSeeAdmin(roles) ? (
        <section className="card p-[18px]">
          <h1 className="text-lg font-semibold">Not authorized</h1>
          <p className="mt-1 text-sm text-muted">This page is for the market operator.</p>
        </section>
      ) : (
        <Telemetry />
      )}
    </main>
  );
}

const KPIS = [
  ["Accounts", "accounts_created"], ["Goals", "goals_posted"], ["Rounds opened", "rounds_opened"], ["Rounds closed", "rounds_closed"],
  ["Bids", "bids"], ["Shield catches", "shield_catches"], ["Calls", "calls_placed"], ["Approvals", "approvals"],
  ["Denials", "denials"], ["Errors", "errors"],
] as const;

const secs = (ms: number) => (ms / 1000).toFixed(1);

function Telemetry() {
  // Rows only reach the screen through the whitelist parser, so a money field added to the view never renders.
  const [telemetryRows] = useTable(tables.telemetry);
  const [agentRows] = useTable(tables.telemetryAgent);
  const live = parseTelemetry(telemetryRows[0]);
  const sim = !live;
  const t = live ?? parseTelemetry(SIM_TELEMETRY);
  const agents = parseAgentEvents(sim ? SIM_AGENT_EVENTS : agentRows);
  if (!t) return <p className="text-sm text-muted">Telemetry is unavailable.</p>;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Telemetry</h1>
        <p className="text-sm text-muted">as of {new Date().toLocaleTimeString()}</p>
        {sim && <p className="text-sm text-muted">SIM. Sample counts until the market telemetry view is published.</p>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {KPIS.map(([label, key]) => (
          <div key={key} className="card min-w-0 p-[18px]">
            <div className="text-sm text-muted">{label}</div>
            <div className="text-3xl font-bold tabular-nums">{t[key]}</div>
          </div>
        ))}
      </div>
      <div className="card p-[18px]">
        <div className="text-sm text-muted">Round time p50 / p95</div>
        <div className="text-3xl font-bold tabular-nums">{secs(t.round_p50_ms)} s / {secs(t.round_p95_ms)} s</div>
      </div>
      <div className="card p-[18px]">
        <div className="mb-2 text-sm text-muted">Events per agent</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted"><th className="text-left font-normal">Agent</th><th className="text-right font-normal">Events</th></tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.agent}><td className="break-all py-1">{a.agent}</td><td className="py-1 text-right tabular-nums">{a.events}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
