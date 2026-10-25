"use client";

import { useMemo } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { MarketScreen } from "@/components/screens";
import { eventsFromRows, goalFromRows, latestRound, linesFromRows, originCounts, roundFromRows } from "@/lib/screens";
import * as sample from "@/lib/sample";
import { crsFor } from "@/lib/crs";

/** The referee's floor: public market state. Empty tables fall back to a sample round, labelled as a sample; each row keeps its own origin (a MIRROR store stays MIRROR, scripted sellers are SIM). */
export default function MarketPage() {
  const [rounds, roundsReady] = useTable(tables.round);
  const [results] = useTable(tables.roundResult);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [goals] = useTable(tables.myGoals); // only a paired buyer screen sees a goal; otherwise the cap is unknown here
  const [goalItems] = useTable(tables.myGoalItems);
  const [signals] = useTable(tables.supplierSignal);
  const crs = (sellerId: string) => crsFor(signals, sellerId, Date.now()); // bands only (docs/changes/0033)

  const r = latestRound(rounds);
  const round = useMemo(() => (r ? roundFromRows(r, events, results) : null), [r, events, results]);
  const lines = useMemo(() => (r ? linesFromRows(results, events, r) : []), [r, results, events]);
  const floor = useMemo(() => eventsFromRows(events), [events]);
  const cap = goalFromRows(goals, goalItems, undefined)?.cap ?? null;
  const sim = !round;
  const shownLines = sim ? sample.sellerLines : lines;
  const shownRound = sim ? sample.round : round;

  // Loss reports and the learning diff have no market table yet (Lane A owns them): SIM sample.
  return (
    <>
      <MarketScreen
        crs={crs}
        connecting={!roundsReady || !eventsReady}
        round={shownRound}
        cap={sim ? sample.goal.cap : cap}
        lines={shownLines}
        lossReports={sample.lossReports}
        learning={sample.learning}
        events={floor}
        originCounts={originCounts(shownRound?.arrivals ?? [])}
        sample={{ round: sim, lines: sim, lossReports: true, learning: true }}
      />
    </>
  );
}
