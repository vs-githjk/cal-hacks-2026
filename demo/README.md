# demo/: the end-to-end demo runner (Lane D)

One command walks the five stage beats through the real code that exists. Where a lane is not merged yet, a
clearly labelled stand-in runs instead. Offline by default: no network, no keys, nothing installed.

```
python3 demo/run_demo.py              # all five beats; writes demo/out/run-<timestamp>.json
python3 demo/run_demo.py --beat 3     # one beat (beats it needs run silently first)
python3 demo/run_demo.py --json       # run JSON on stdout, the story on stderr
python3 demo/run_demo.py --stripe     # Stripe TEST charge, only if STRIPE_SECRET_KEY is an sk_test_ key
python3 -m pytest demo/tests          # 34 tests, under a second
```
Exit code is 1 if any of the demo's own checks fails (cheapest eligible bid vetoed with a source, injected listing
blocked, approval only on the third try, can_charge only after approval, replay fails, learner closes the gap).
Optional env: `APPROVAL_SECRET` (else a random throwaway), `VISA_TAP_PRIVATE_KEY_PATH` (else a throwaway Ed25519 key
in a temp dir that is deleted), `STRIPE_SECRET_KEY` (only read with `--stripe`). Nothing prints a key or the approval code.

## Tags
Every line that shows data carries one: **LIVE** (a real outside party right now; offline there is none, Stripe's test
API with `--stripe` is the only one), **MIRROR** (our agent acting on a real, dated listing from `data/mirror/snapshots`),
**SIM** (anything we generated). Real code that runs on SIM data is still tagged SIM; each beat header says which
code is real. SIM and MIRROR numbers are never added together.

## Real vs stand-in, per beat
| Beat | REAL code and data | Stand-in (SIM) | Honest notes |
|---|---|---|---|
| 1 Goal | PSU need read from `data.fit_checker.tables.GPU_POWER` (750 W for an RTX 5070 Ti); contracts Goal, OwnedPart, Need, Allowance validated | `demo/goal.py` mirrors Lane A `agents/buyer/goal.py` (goal parsing, ownership memory, skipped line citing the OwnedPart); Joe and his parts are a SIM persona | Goal and OwnedPart schemas are pending copies in `demo/contracts_pending/` |
| 2 Sealed round | `data.fit_checker.check_fit` (fit is code); `shield.screen` on every seller's text; MIRROR bids from real snapshots (listing URL, snapshot id on every line); Honest Hal and Shady Sam read from Lane C's hosted pages; claim check is Lane C's c3 when it is on the branch, else the stand-in | `demo/sellers.py` (Lane A seller policy, LOCKED seller model: one agent per seller of record, several condition lines); `demo/standins/market.py` (Lane B sealing, floor, scoring); `demo/standins/advocate.py` (Lane A advocate card and closed-schema call reason); `demo/standins/claim_check.py` | Every MIRROR bid is over Joe's $900 cap (the real in-stock RTX 5070 Ti listings in the snapshots are $1,199.99 to $1,489.00), so only SIM sellers can win. The runner says so. B&H and one Amazon listing are out of stock in the snapshot and do not bid. Where a real seller has no open-box listing the agent adds a derived open-box line (10 percent under its new price), labelled SIM-derived. MIRROR claims stay `unverified` offline (pages are not re-fetched) |
| 3 Shield | `shield.screen` on Lane C's `shady-sam-gpu-5070ti-injected.html`; blocked, rule ids and evidence spans printed; clean page as control; verdict also validated as the v0 `ShieldVerdict` contract | none (the page is SIM, the screening is real) | Beat 2's screen passes only the payee of record; the price rule is left to the claim check so Sam's bid reaches the advocate. Beat 3 passes the price history too |
| 4 Approval | all of `pay/`: `new_mandate`, `script_for` (closed-schema reason), `ApprovalService` (wrong code denied, code without approve denied, code plus approve approved), `can_charge` (refused before, passes after), `sign_request` and `verify_request` (RFC 9421 Ed25519, TAP-style), `mark_used`, replay and an edited amount both fail | the call transport (transcripts typed by the runner, no Cartesia); the sim clock (advances 31 s per retry instead of sleeping); the merchant (the runner calls `verify_request` the way Lane C's merchant simulator will); the Stripe charge is a SIM stub | Not Visa settlement: a Stripe test charge on a Visa test card under a TAP-style signed mandate. `--stripe` with an `sk_test_` key makes one test-mode PaymentIntent (`pm_card_visa`, idempotent on the mandate hash); that path is tested with a fake HTTP layer only, never against Stripe, because no key was available |
| 5 Learning | LossReport contract (pending copy from Lane B); round 2 runs the same pipeline as beat 2, so the real fit checker and Shield run again | loss reports and the strategy update (`demo/learning.py`, deterministic price step by gap band, never below the floor); "what to change" is a fixed template, Claude writes it in the product | Reports carry a band, a reason and a source, never a threshold or a rival price. One seller, one round, SIM sellers: shows the mechanism, no trend claim |

## What to swap when Lane A (agents) merges
Needs `uagents` installed (`agents/common.py` imports it); that install is Vidyut's call, the runner does not need it today.
1. `demo/goal.py`: replace `parse_goal`, `build_goal`, `joe_owned_parts`, `need_from_goal`, `skip_lines` with
   `agents.buyer.goal` (`parse_goal`, `remember`, `apply_owned`, `need_from_goal`, `skip_lines`, `owned_attrs`). Lane A's `SKUS` only knows
   `rtx 4070 super 12gb`; it needs an `rtx 5070 ti` entry, and the allowed-condition list (`new or open-box`) that this runner adds to the goal item
   (`allowed_conditions`) is not in Lane A's Goal yet.
2. `demo/sellers.py` `make_bid` and `line_price`: call `agents.sellers.policy.make_bid(need, seller)`. Keep `load_offers` and `mirror_sellers`
   (they build the catalog from the MIRROR snapshots). Lane A's catalog has one condition per listing; the LOCKED seller model needs several condition lines per bid.
3. `demo/standins/advocate.py`: replace `advise` with `agents.advocate.checks.advise(need, bids, baseline, records, recalls, owned)`. Gaps to close
   on their side: it does not read claim-check results (the false "was" price veto here comes from the claim check), and its `CALL_SUMMARIES`
   lacks `advocate.claim_price`. Its `call_reason` already has the same closed `{rule_id, summary, source_url}` shape; `pay.callscript` accepted every summary here.

## What to swap when Lane B (market) merges
Lane B's rules are TypeScript in SpacetimeDB, so this runner keeps a Python golden model (`demo/standins/market.py`). Once reducers are live:
1. In `demo/round.py` replace step 1 (sealing), step 2 (floor) and step 5 (ranking) with calls to the reducers over the Python bridge
   (submit bid, close round, rank). Keep steps 3, 4 and 6 (Shield, claims, advocate): they belong to other lanes.
2. Differences to settle with Vedant: Lane B's `checkLineSpec` allows one condition per need line; the LOCKED seller model has several condition lines per bid,
   so this runner keys floors by SKU and condition and scores per line. Bid contract: Lane B's version has `seller_id`, `origin` and a URL string in `source`;
   this runner emits `supplier_id` and `seller_id` both, `origin`, and the lower-case `source` enum that `contracts/Bid.schema.json` still has. When Lane B's
   Bid merges, change `source` in `demo/sellers.py make_bid` to the listing URL.
3. Delete `demo/contracts_pending/LossReport.schema.json` and Goal/OwnedPart once those schemas are in `contracts/` (`demo/common.py validate` prefers `contracts/`).
4. Lane B's screens replay `demo/out/run-*.json` (layout below); a committed sample is `demo/out/sample-run.json`.

## What to swap when Lane C (data) merges
1. `data.claim_check`: nothing. `demo/adapters.py claim_checker()` uses the real `check_claim` as soon as it accepts `fetch` (Lane C's c3 does). Then delete
   `demo/standins/claim_check.py`. The runner passes `fetch=demo.pages.fixture_fetch`, which serves `data/liar_pages/site` from disk (same bytes as
   `python3 -m http.server 8765 --directory data/liar_pages/site`) and refuses every other URL.
2. Merchant simulator: replace the direct `verify_request` call in `demo/approval_flow.py` with a POST to it. It must pass `expected_mandate_hash`.
3. Real MIRROR fit data: Lane C's cards only carry `chipset`, so fit on MIRROR bids is `uncertain` (a caution, never a veto) until card length and
   connectors are on the SpecCard.

## JSON layout (`demo/out/run-<timestamp>.json`)
`schema`, `run_id`, `generated_at`, `provenance` (what is real, what is a stand-in), `beats` (`"1"` to `"5"`, full detail), `checks` (the pass/fail list),
and `artifacts`, a flat index for replay: `goal`, `owned_parts`, `need`, `allowance`, `seller_agents` (origin, listing URL, floor per line),
`bids`, `claims`, `verdicts` (`referee`, `shield`, `ranking`, `advocate_cards`, `winner`, `injected_listing`, `control_listing`), `mandate_at_approval`,
`mandate` (final, status `used`, signature attached), `approval_record` (VoiceApproval), `approval_attempts`, `call_script`, `signatures`, `signature_checks`,
`charge`, `loss_reports` (round 1 and round 2), `strategy_diff`, `what_to_change`. Bids, claims, cards, verdicts, mandates, approval records and loss
reports validate against `contracts/` (Goal, OwnedPart and LossReport against the pending copies); the tests check all of them.

## Limits (checked and not checked)
- Checked: the 34 tests, two mutations (approval on the second try, Shield fed a harmless page) fail them as they should, and the full run completes with sockets disabled.
- Not checked: the live Stripe path, a real Cartesia call, a real merchant simulator, and any Lane A or Lane B code (neither is merged; their shapes were read from
  `origin/agents` and `origin/lane-b-market-floor`, not imported).
- The Shield, fit and claim wording is the real code's output; the advocate's quality-adjustment weights (open-box +4 percent, no returns +2, caution record +3) are SIM.
