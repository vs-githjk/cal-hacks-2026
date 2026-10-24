// Live-sync check without a browser: two independent clients, each with its own identity and
// buyer session, subscribe the way /buyer does and print every goal and floor event they receive.
// Run: npx tsx scripts/two_clients.ts, then post_goal from Python within 15 seconds.
import { DbConnection } from "../src/module_bindings";

const URI = process.env.NEXT_PUBLIC_SPACETIMEDB_URI || "ws://127.0.0.1:3000";
const DB = process.env.NEXT_PUBLIC_SPACETIMEDB_DB || "tech-bazaar";

for (const name of ["client-1", "client-2"]) {
  DbConnection.builder()
    .withUri(URI)
    .withDatabaseName(DB)
    .onConnect((conn) => {
      conn.reducers.openBuyerSession({ buyerId: "joe" });
      conn.db.myGoals.onInsert((_ctx, g) => console.log(`${name} ${Date.now()} goal ${g.id} ${g.state}`));
      conn.db.floorEvent.onInsert((_ctx, e) => console.log(`${name} ${Date.now()} event ${e.kind}: ${e.label}`));
      conn
        .subscriptionBuilder()
        .onApplied(() => console.log(`${name} subscribed`))
        .subscribe(["SELECT * FROM my_goals", "SELECT * FROM floor_event"]);
    })
    .build();
}
setTimeout(() => process.exit(0), 15_000);
