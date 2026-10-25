"use client";

import { useMemo } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { MarketScreen } from "@/components/screens";
import { eventsFromRows, goalFromRows, latestRound, linesFromRows, marketKpis, originCounts, roundFromRows, roundHistory } from "@/lib/screens";

/** The referee's floor: public market state. Only real rows are shown (no sample fallback); each row keeps its own origin (a MIRROR store stays MIRROR, scripted sellers are SIM). */
export default function MarketPage() {
  const [rounds, roundsReady] = useTable(tables.round);
  const [results] = useTable(tables.roundResult);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [goals] = useTable(tables.myGoals); // only a paired buyer screen sees a goal; otherwise the cap is unknown here
  const [goalItems] = useTable(tables.myGoalItems);

  const r = latestRound(rounds);
  const round = useMemo(() => (r ? roundFromRows(r, events, results) : null), [r, events, results]);
  const lines = useMemo(() => (r ? linesFromRows(results, events, r) : []), [r, results, events]);
  const floor = useMemo(() => eventsFromRows(events), [events]);
  const cap = goalFromRows(goals, goalItems, undefined)?.cap ?? null;
  const kpis = useMemo(() => marketKpis(rounds, results), [rounds, results]);
  const history = useMemo(() => roundHistory(rounds, results), [rounds, results]);

  return (
    <MarketScreen
      connecting={!roundsReady || !eventsReady}
      round={round}
      cap={cap}
      lines={lines}
      kpis={kpis}
      history={history}
      events={floor}
      originCounts={originCounts(round?.arrivals ?? [])}
    />
  );
}
