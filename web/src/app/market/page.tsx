"use client";

import { useMemo } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { MarketScreen } from "@/components/screens";
import { Bracket } from "@/components/Bracket";
import { asSim, eventsFromRows, goalFromRows, latestRound, linesFromRows, originCounts, roundFromRows } from "@/lib/screens";
import * as sample from "@/lib/sample";

/** The referee's floor: public market state. Empty tables fall back to the recorded sample run, labelled SIM. */
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
  const sim = !round;
  const shownLines = sim ? asSim(sample.sellerLines) : lines;
  const shownRound = sim ? asSim(sample.round) : round;

  // Loss reports and the learning diff have no market table yet (Lane A owns them): SIM sample.
  return (
    <>
      <MarketScreen
        connecting={!roundsReady || !eventsReady}
        round={shownRound}
        cap={sim ? sample.goal.cap : cap}
        lines={shownLines}
        lossReports={asSim(sample.lossReports)}
        learning={asSim(sample.learning)}
        events={floor}
        originCounts={originCounts(shownRound?.arrivals ?? [])}
        sample={{ round: sim, lines: sim, lossReports: true, learning: true }}
      />
      <Bracket />
    </>
  );
}
