# 18:00 Lane D #345 phase 2: the build view for the hosted board (asks to Lane B market and the web), and what phase 2 changed

For Vedant (Lane B, market module), and Vedant and Abhinav (web, #343). Nothing in `market/`, `web/` or `agents/` was changed. Code: `demo/build.py`; run `python3 demo/build.py --dry-run`.

## The problem
The build board on the Vercel page cannot read `demo/out/build-view.json`, because that file is on Vidyut's Mac. The BuildView is a public object (its prices appear only after a round closes), so the market should hold the latest copy and the board should subscribe to it, the way it subscribes to `agent_event`.

## Ask 1, Lane B (Vedant): one referee reducer and one public table
Both are additive. Lane D calls the reducer only when the market module source has it (`market_has_reducer("publish_build_view")` in `demo/build.py` reads `market/spacetimedb/src/index.ts`, as `bridge.market_has_typed_approval` does), so nothing breaks before it lands.

```ts
// schema.ts
export const buildView = table(
  { name: 'build_view', public: true },
  { goalId: t.string().primaryKey(), json: t.string(), updatedAt: t.timestamp() },
);

// index.ts
export const publish_build_view = spacetimedb.reducer({ goalId: t.string(), json: t.string() }, (ctx, a) => m.publishBuildView(ctx, a));

// market.ts
export function publishBuildView(ctx: Ctx, a: { goalId: string; json: string }) {
  requireRole(ctx, 'publish_build_view', ['referee']);
  if (a.json.length > 262144) throw new SenderError('build view is over 256 KB');
  let v: any;
  try { v = JSON.parse(a.json); } catch { throw new SenderError('json must parse'); }
  if (!v || typeof v !== 'object' || v.goalId !== a.goalId) throw new SenderError('json must be a BuildView with the same goalId');
  const row = { goalId: a.goalId, json: a.json, updatedAt: ctx.timestamp };
  if (ctx.db.buildView.goalId.find(a.goalId)) ctx.db.buildView.goalId.update(row); else ctx.db.buildView.insert(row);
}
```
- One row per goal, replaced in place (an upsert), so the table stays small. No `floor_event` per call: the build sends one view about every second, and a floor event for each would flood `/floor`.
- `reset_demo` should clear `build_view` with the other demo tables.
- The Python caller is `ViewPublisher` (`demo/build.py`): the referee client calls `publish_build_view(goal_id=..., json=...)`. A failing call is noted once and dropped after three failures. It never stops a build.
- One question for you: the view holds `approval.mandates[].mandateHash` and amounts. Round results are public after the close, but mandates are buyer-private in the market. If you want them hidden on the public table, say so and Lane D drops the `mandates` array from the published copy (the local file keeps it). The board only needs the part list, checks, events and `approval.state`, `approval.total`, `approval.sellers`.
- After it merges, the module must be republished to Maincloud (Vidyut, as owner) and the bindings regenerated.

## Ask 2, web (Vedant, Abhinav): read it
- Subscribe to `SELECT * FROM build_view`; take the row for the goal (the newest `updated_at` when there is no goal id yet), `JSON.parse(row.json)` into the `BuildView` of `docs/changes/1650-D-build-board-shape.md`. It is one object per goal, always the whole view, never a diff.
- While the table is empty or the reducer is not published, keep reading `contracts/samples/build-board.sample.json` and label it SIM, as today.
- The board still never decides a fit or a price. It reads `checks[].state` and `parts[].status`.

## What phase 2 added to the view (the board gets these from the same shape)
- `checks[]` is real now: `data.fit_checker.build_check` (Anoop, #342) over the locked champions and the parts the buyer owns, one line per rule that ran. `rule` is `socket`, `ddr`, `case_room`, `power` or `cooler_height`; `state` is `ok`, `clash` or `unknown` (a rule the checker could not judge is never `ok`); `source` is the checker's rule id (`fit.cpu_socket`, `fit.ram_type`, `fit.gpu_length`, `fit.form_factor`, `fit.psu_form_factor`, `fit.psu_wattage`, `fit.gpu_connectors`, `fit.cooler_socket`, `fit.cooler_height`); `detail` is its reason. Recomputed every time a part locks.
- A clash on a part's pick makes ONE re-plan: the log shows `clash` (red), `replan` (swap) and a `locked` line with "fit re-check green" for the same parts. The part has a second need and round (`need-<goal>-<part>-2`, `round-<goal>-<part>-2`) and ends `replanned`, with `reason` set to the replan line. If the second pick still clashes, the build is denied with "No call: the picked parts do not fit (...). Nothing was paid." (reason code `fit_clash`).
- In the replay file (`build-view.steps.jsonl`) the red state is visible: a line where the board is `locked` and its `socket` check is `clash`, then the next lines where the board is `bidding` for the second round, then `replanned` with the check `ok`.
- The default demo's cheapest SIM board is an LGA1700 board (labelled SIM). No other part is trapped.
- Part label for the board is now "ATX motherboard" (the first need names no socket); the second need says "ATX motherboard for AM5".
- Pacing: part rounds open `--stagger` seconds apart (default 2 s, so six parts open within 10 s) and close in part order, at least 1 s apart. A six-part build with the real GPU cast and one re-plan is scheduled over about 77 s from the first round. `--sequential` restores one round at a time.

## Planner (#358) and knockout (#363): used when they are on the branch
- `planned_build()` uses `agents.buyer.planner.plan(cap_cents, owned)` when it imports, else the default plan, and says which. The adapter `plan_from_planner` reads #358's documented output (`cap_cents`, `owned`, `parts[].budget_cents`, `steps[0].line`); the planner's own line becomes the plan event, its `owned` specs feed the fit checks. The demo cap is $2,100 (cap_cents 210000) so the planner's GPU share is about $1,329, above the real GPU listings at $1,300.
- Knockout: `--knockout auto` uses `open_knockout_round` / `close_stage` (docs/changes/1633-B-knockout-rounds.md, max 3 stages) when the market module source has `open_knockout_round`; each surviving seller makes one improved sealed offer a stage (3 percent under its own last one, never under its floor), and only the market's `champion` row is mandated. Without it, every round is one sealed stage. Tested on the in-memory market (`demo/build_sim.py`) built from the #363 contract, not on the real module.
