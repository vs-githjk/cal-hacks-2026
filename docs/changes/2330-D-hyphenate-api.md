# Lane D: Hyphenate API and engine (new module, no existing contract changed)

New module `hyphenate/` with its own FastAPI app `hyphenate.api:app` (routes under `/v1/hyphenate/*`). Nothing in `contracts/`, `pay/`, `shield/`, `data/` or `demo/` was edited; `hyphenate/` imports `pay.mandate`, `pay.replay` and `shield.api.BodyLimit`.

For Lane B (pages): JSON shapes, the route list and the response envelope are in `hyphenate/README.md`. `POST /v1/hyphenate/demo/reset` loads the seeded story so a page has data; `GET /v1/hyphenate/audit/{id}/explain` is the audit page's source; `GET /v1/hyphenate/pos/{id}` is the PO page (route, approvals, decisions, memos, invoices); `GET /v1/hyphenate/reconciliation` is the disagreeing-sources view.

For Lane C: `three_way_match` is implemented in `hyphenate/matching.py` (pure function) and `hyphenate/payables.py`; it accepts an embedded claim-check result on the invoice (`claim: {"result": "verified"|"unverified"|"false", "reason": ...}`, the shape `data.claim_check.check_claim` returns) and holds on `false`.

Possible new use of existing contracts (nothing breaks, nothing required): `ReceivingEvent` and `LedgerEntry` are not used as-is because the ledger here is double-entry in integer cents (`contracts/LedgerEntry.schema.json` is a single-sided float row); a future adapter can map `Entry.lines` to it.

CI note for the conductor: `.github/workflows/python-tests.yml` path filters do not list `hyphenate/**`, so a PR touching only this folder will not trigger it; `python -m pytest -q` at the root does collect the hyphenate tests (61).
