# 12:03 Lane D: new contract MemoryEntry (#189)

`contracts/MemoryEntry.schema.json`: one row of the buyer's memory panel (#123). Each row is a past goal, a purchase,
a veto or a seller lesson.

- Common fields:
  - `id`, `kind` (goal | purchase | veto | lesson), `at` (ISO, empty when unknown)
  - `origin` (LIVE | MIRROR | SIM)
  - `source` (demo_run | market), `source_ref`
  - `buyer_id`, `seller_id`
  - `summary` (one plain sentence)
  - `detail` (per kind)
- Purchase detail:
  - `amount_before_tax` (the mandate amount; the market adds no tax)
  - `approval_method` (voice_code, allowance, sim_script or none)
  - `payment_mode` (sim | stripe_test | none)
  - `listing_origin`
  - Purchases are always `origin: SIM` this weekend.
- Lesson detail: bands only (`gap_band`), never a raw gap.

Served by `GET /v1/memory` on the agent feed (scripts/agent_feed.py, port 8790):

```
{"entries": [MemoryEntry, ...], "sources": [{"ref", "kind", "state": "ok|empty|error", "sample", "rows"}], "note": ""}
```

Query parameters: `?kind=veto`, `?limit=20`, `?sample=1`. `sample=1` includes the committed demo/out/sample-run.json, which is left out by default. With nothing recorded, `entries` and `sources` are empty and `note` says so.

Rows come from demo/out/run-*.json and the newest demo/out/market-memory-*.json. demo/rehearse.py writes that file from owner SQL at the end of every rehearsal (`python3 -m demo.memory snapshot` does the same by hand).

For Lane A (data adapter) and Lane B (panel): build against this shape. Newest first.
