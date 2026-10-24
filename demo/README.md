# demo/: the end-to-end demo runner (Lane D)

One command walks the five stage beats through the real code on main. Where a lane's code cannot run here (node and
the uagents runtime are not installed), a clearly labelled Python stand-in runs instead. Offline by default: no network,
no keys, nothing installed.

```
python3 demo/run_demo.py              # all five beats; writes demo/out/run-<timestamp>.json
python3 demo/run_demo.py --beat 3     # one beat (beats it needs run silently first)
python3 demo/run_demo.py --json       # run JSON on stdout, the story on stderr
python3 demo/run_demo.py --stripe     # ONE Stripe TEST PaymentIntent, only if STRIPE_SECRET_KEY is an sk_test_ key
python3 -m pytest demo/tests          # 45 tests, about a second
```
Exit code is 1 if any of the demo's own checks fails (cheapest eligible bid vetoed with a source, a real MIRROR seller
wins, one seller shows new and open-box lines, injected listing blocked, approval only on the third try, can_charge only
after approval, replay fails, learner closes the gap). Optional env: `APPROVAL_SECRET` (else a random throwaway),
`VISA_TAP_PRIVATE_KEY_PATH` (else a throwaway Ed25519 key in a temp dir that is deleted). Nothing prints a key or the approval code.

## Stripe test charge (`--stripe`)
`STRIPE_SECRET_KEY` is read from the environment, else from the lane-d `.env` (`../lane-d/.env` next to this checkout, or `--env-file PATH`); only that
one name is read, the value is never printed or written to the JSON. It must start with `sk_test_`, otherwise the SIM stub runs and the console says so.
The charge happens after `can_charge` passes at charge time, never before: one `POST /v1/payment_intents` (stdlib `urllib`, certificate checking on) with
`payment_method=pm_card_visa`, `confirm=true`, `Idempotency-Key = mandate:<mandate hash>`, amount from the approved mandate. The console and JSON show only
the PaymentIntent id and status. A refused call prints Stripe's error type and code, not the request. Without `--stripe` the charge is a SIM stub.
This is not Visa settlement: it is a Stripe test charge on a Visa test card under a TAP-style signed mandate.

## Screen bridge (`demo/bridge.py`): watch the run on /buyer and /market
```
python3 demo/bridge.py --step-delay 2 --reset   # about 90 s; --reset calls reset_demo first (keeps roles and pair codes)
python3 demo/bridge.py --dry-run                # the reducer calls, nothing written
python3 -m pytest demo/tests/test_bridge.py     # mapping with a fake client, no network
```
It runs `run_all` (this folder's real lane code), then writes each supported step through the market's EXISTING reducers with the role token each one demands
(buyer: `post_goal`, `post_need`; referee: `open_round`, `attach_verdict`, `attach_claim_check`, `attach_advocate_card`, `close_round`, `create_mandate`;
one seller identity per demo seller: `set_floor`, `place_bid`). Needs `referee.json` and `buyer-vidyut.json` from `market/scripts/setup_roles.py` (auto-found in `.tokens/` or the launcher's) and the
local DB on 127.0.0.1:3000. Seller identities get tokens in `.tokens/bridge-<seller>.json` (gitignored) and an owner `assign_role` (the setup_roles call). Pair /buyer as `vidyut` with
`spacetime sql -s local tech-bazaar "SELECT code FROM pair_code"`. The buyer is Vidyut; the goal, owned parts and payment data are labelled SIM; the DB buyer id is `vidyut`, the only id /buyer pairs with.
The advocate's cards are bridged: `attach_advocate_card` carries Lane A's real card for each bid (a veto cites its source and disqualifies the bid at the close), the need carries
`allowed_conditions` (open-box lines rank), a bid carries all its condition lines as alternatives (the market picks the cheapest allowed one), the market drops bids over the goal cap
(`over_cap`). Only claims mapped to the selected line are published, and each has a matching bound review check. Shared listing URLs use the seller fixture's original line order; unsupported mappings are omitted.
The console ends with the market's ranking, every bid it put out with its reason, and a DIVERGENCE line if its #1 is not the demo's winner. Mandate creation is gated on an exact authoritative winner readback.
Approval and payment are not bridged: this adapter has no verified checkout evidence path, and it never writes the demo's local approval or payment result as market proof. `--stripe` is rejected before the local demo runs.
Not bridged, so it is printed as NOT BRIDGED at the end of every run and is the Lane B gap list: loss reports (the market has `record_loss_report`, but this bridge does not call it), buyer allowance, denied approval attempts, personas and the
buyer name, and a floor per seller, SKU and condition (the market keeps one floor per SKU).

## Tags
Every line that shows data carries one: **LIVE** (a real outside party right now; offline there is none, Stripe's test API with `--stripe` is the only one),
**MIRROR** (our agent acting on a real, dated listing from `data/mirror/snapshots`), **SIM** (anything we generated). Real code that runs on SIM data is still
tagged SIM; each beat header says which code is real. SIM and MIRROR numbers are never added together.

## The story the numbers tell (round 1)
Vidyut's goal: an RTX 5070 Ti that fits the case, **under $1,300**, by Friday, new or open-box. The cap matches the real market: the in-stock real
listings in the snapshots run $1,239.99 to $1,489.00. One or two bids are real, the rest are labelled simulated:
- **Best Buy (MIRROR) wins at $1,249.99**, its real new listing. The advocate marks it CAUTION: the snapshot has no card length, so fit is "not confirmed", said and not guessed.
- One more real bid is inside the cap (an eBay seller, open-box $1,239.99, ranked last). The other real listings are over the cap or state no condition (Micro Center, Amazon), and are out.
- **Shady Sam (SIM) bids $757.44**, far under the market, and is vetoed by Lane A's real advocate: his page shows open-box while he claims new, and his "was $1,099" does not match the price history (highest recorded $829.00). Both cite his page.
- **Bargain Bin (SIM)** is vetoed by the real fit checker (336 mm card, 305 mm case). **Lowball (SIM)** bids under its floor and the referee rejects it before anyone sees it.
- **Gadget Grove (Vedant)** (a SIM seller, Vedant is the learner seller) is one seller with two condition lines, new and open-box. **Fair Price PC (SIM)** is the static control.
- Honest Hal's page is used by beat 3 only (the clean control). At $789 his honest listing would undercut every real seller, so he does not bid in the market round.
SIM listing prices (Bargain Bin, Lowball, Gadget Grove (Vedant), Fair Price PC) sit inside the real $1,200 to $1,300 band by construction; Sam's price is Lane C's page price ($789).
Real merchants are never contacted or paid: the payee on a MIRROR seller is a SIM test address (`best-buy@pay.example.test`).

## Seller model (LOCKED Fri 22:36)
One seller agent per seller of record (Amazon direct is one agent, each eBay listing is its own because the snapshot has no seller handle). The lines of a bid are
**alternatives** for the same SKU. The market picks the **cheapest line whose condition is in the goal's `allowed_conditions`** (`new`, `open-box`), never a sum.
The bid then ranks on that line's **quality-adjusted landed price**, and the advocate judges that same line. A real seller never gets an invented line: MIRROR
agents bid only the conditions their real listings show (an earlier version derived open-box lines; they are gone). Gadget Grove (Vedant) shows the model: new $1,315.27 and
open-box $1,247.02, open-box is picked ("picked of 2 lines"), the fit check runs once on that line, and an allowed open-box line is not flagged as "you asked for new".
Quality-adjustment weights (open-box +4 percent, no returns +2, caution record +3) are SIM; real MIRROR sellers get the no-returns +2 because return terms were not captured.

## Real vs stand-in, per beat
| Beat | REAL code and data | Stand-in (SIM) | Honest notes |
|---|---|---|---|
| 1 Goal | PSU need read from `data.fit_checker.tables.GPU_POWER`; contracts **Goal, OwnedPart, Need, Allowance** from `contracts/` (all on main, `demo/contracts_pending/` is deleted) | `demo/goal.py`: Vidyut's goal and owned parts (SIM data) and goal parsing with `allowed_conditions` | `agents/buyer/goal.py` is real and pure (it loads without uagents through the same shim as the advocate) but is hardcoded to `rtx 4070 super 12gb` and one condition, so it cannot parse this goal; not used |
| 2 Sealed round | **`agents/advocate/checks.py` (Lane A) `advise`, `call_reason`, `CALL_SUMMARIES`**; `data.fit_checker`; **`data.claim_check.check_claim` (Lane C), offline via a fixture fetch of `data/liar_pages/site`**; `shield.screen` on every seller's text; MIRROR bids from real snapshots; Shady Sam read from Lane C's hosted page | `demo/sellers.py` bid policy (MIRROR agents bid from real listings; Lane A's `agents/sellers/policy.py` uses its own catalog); `demo/standins/market.py` (sealing, floor, scoring: Python mirror of `market/rules`); glue in `demo/advice.py` | See "How the real advocate is loaded" below. The glue feeds the advocate only the picked line, and turns false claim-check results into warnings (the advocate does not read them yet). Price-history baseline, seller records and CPSC recalls are empty here (no data for this SKU, feed needs network) |
| 3 Shield | `shield.screen` on Lane C's `shady-sam-gpu-5070ti-injected.html`; blocked, rule ids and evidence spans printed; clean page as control; verdict validated as the `ShieldVerdict` contract | none (the page is SIM, the screening is real) | Beat 2's screen passes only the payee of record; beat 3 also passes the price history |
| 4 Approval | all of `pay/`: `new_mandate`, `script_for` (closed-schema reason), `ApprovalService`, `can_charge`, `sign_request` and `verify_request` (RFC 9421 Ed25519, TAP-style), `mark_used`, replay and an edited amount both fail; **Stripe test mode with `--stripe`** (see above) | call transport (transcripts typed by the runner, no Cartesia); the sim clock (+31 s per retry, no sleeping); the merchant (the runner calls `verify_request` directly) | The charge is a SIM stub unless `--stripe` and an `sk_test_` key |
| 5 Learning | `contracts/LossReport.schema.json`; round 2 runs the same pipeline as beat 2 | loss reports and the strategy update (`demo/learning.py`, a deterministic price step by gap band, never below the floor); "what to change" is a fixed template, Claude writes it in the product | Reports carry a band, a reason and a source, never a threshold or a rival price. One seller, one round, SIM sellers: shows the mechanism, not a trend. The learner lowers its picked open-box line and wins round 2 over the real Best Buy bid |

### How the real advocate is loaded (`demo/adapters.py`)
`agents/advocate/checks.py` starts with `import common`, and `agents/common.py` imports the `uagents` runtime, which is not installed here. `checks.py` uses `common`
for one thing: putting the repo root on `sys.path`. `advocate_checks()` loads the file by path; when that import fails on `uagents` or `common` it satisfies the
single name `common` with an empty module for the duration of the import. No function is copied or edited, `advise`, `call_reason` and `CALL_SUMMARIES` are Lane A's
own, and a test asserts they are called. If `uagents` gets installed, the same loader just works. Every `CALL_SUMMARIES` entry passes `pay.callscript.clean_advocate_reason`.
Gaps for Lane A, seen while wiring: `advise` compares one condition per need item (not `allowed_conditions`), does not read claim-check results, and has no
quality-adjusted price (`best_bid` takes the lowest landed price), so the runner does the quality-adjusted ranking in the market stand-in.

### Lane B parity (`demo/tests/test_market_parity.py`)
node is not installed, so `market/rules/scoring.test.ts` cannot run, but its fixtures are plain literals. The parity test reads that file and extracts five `rankBids`
cases (rank by landed price minus perks value, open-box trap disqualified, rejections applied, ties by verified claims then sealed time, landed price from the lines
not a stated total), then asserts the Python stand-in yields the same ranking the TypeScript test expects. If the file changes shape the test fails by case name.
**Not covered:** the quantity 0/-1/NaN cases (the stand-in's referee `check_floor` handles those; tested in `test_run_demo.py`), the fast-check "fee never ranks"
property (the stand-in never reads a fee), and `checkLineSpec` alone: it assumes one condition per need line, while this runner implements the LOCKED alternatives
model (@lane-b: `checkLineSpec` and `rankBids` need allowed_conditions and cheapest-allowed-line, per the reviewer's note). Sealing and floor rules are Python mirrors, read from `sealing.ts` and `floor.ts`, with no executable parity.

## What to swap when Lane A or Lane B change
- Lane A: `demo/goal.py` once `agents/buyer/goal.py` knows `rtx 5070 ti` and allowed conditions; `demo/sellers.py make_bid` once Lane A's seller policy can bid from
  MIRROR listings with several condition lines. Nothing to do for the advocate except deleting `demo/advice.py` glue lines as Lane A absorbs them.
- Lane B: replace round steps 1, 2 and 5 in `demo/round.py` with the reducers once they accept alternatives per SKU. Bid contract: `source` is the lower-case enum
  on `contracts/Bid.schema.json`; the runner emits `supplier_id` and `seller_id`, `origin`, per-line `origin`, `listing_url`, `page_condition`.
- Lane C: replace the direct `verify_request` call in `demo/approval_flow.py` with a POST to the merchant simulator; it must pass `expected_mandate_hash`.
  MIRROR cards only carry `chipset`, so fit on real bids is `uncertain` (a caution, never a veto) until card length and connectors are on the SpecCard.

## JSON layout (`demo/out/run-<timestamp>.json`)
`schema`, `run_id`, `generated_at`, `provenance` (what is real, what is a stand-in), `beats` (`"1"` to `"5"`, full detail), `checks` (the pass/fail list),
and `artifacts`, a flat index for replay: `goal`, `owned_parts`, `need`, `allowance`, `seller_agents` (origin, listing URL, floor per line),
`bids`, `claims`, `verdicts` (`referee`, `shield`, `ranking`, `advocate_cards`, `winner`, `injected_listing`, `control_listing`), `mandate_at_approval`,
`mandate` (final, status `used`, signature attached), `approval_record` (VoiceApproval), `approval_attempts`, `call_script`, `signatures`, `signature_checks`,
`charge`, `loss_reports` (round 1 and round 2), `strategy_diff`, `what_to_change`. Bids, claims, cards, verdicts, mandates, approval records and loss
reports validate against `contracts/` (all on main); the tests check all of them.

## Limits (checked and not checked)
- Checked: 45 tests; two mutations (the old $900 cap, picking the most expensive line instead of the cheapest) fail them as they should; the full run completes with sockets disabled;
  one `--stripe` run created a real test-mode PaymentIntent (id and status in the handoff).
- Not checked: a real Cartesia call, a real merchant simulator, the TypeScript market rules themselves (parity is by shared fixtures only), and Lane A's agents running
  under uagents (only their pure functions run).
- The Shield, fit and claim wording is the real code's output; the quality-adjustment weights are SIM.
