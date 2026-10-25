# demo/: the end-to-end demo runner (Lane D)

One command walks the five stage beats through the real code on main. Where a lane's code cannot run here (node and
the uagents runtime are not installed), a clearly labelled Python stand-in runs instead. Offline by default: no network,
no keys, nothing installed.

```
python3 demo/run_demo.py              # all five beats; writes demo/out/run-<timestamp>.json
python3 demo/run_demo.py --beat 3     # one beat (beats it needs run silently first)
python3 demo/run_demo.py --json       # run JSON on stdout, the story on stderr
python3 demo/bridge.py --live-call --stripe   # ONE Stripe TEST PaymentIntent, only after a real call approves (sk_test_ key only)
python3 -m pytest demo/tests          # 45 tests, about a second
```
Exit code is 1 if any of the demo's own checks fails (cheapest eligible bid vetoed with a source, a real MIRROR seller
wins, one seller shows new and open-box lines, injected listing blocked, approval only on the third try, can_charge only
after approval, replay fails, learner closes the gap). Optional env: `APPROVAL_SECRET` (else a random throwaway),
`VISA_TAP_PRIVATE_KEY_PATH` (else a throwaway Ed25519 key in a temp dir that is deleted). Nothing prints a key or the approval code.

## Stripe test charge (`demo/bridge.py --live-call --stripe`)
Only a real phone call can lead to a Stripe call. `run_demo.py` types its approval (no call), so its beat 4 always pays with the SIM stub and
`run_demo.py --stripe` is refused; `bridge.py --stripe` without `--live-call` is refused too. With `--live-call --stripe` the bridge charges once, after
the call approves, `can_charge` passes and the market has recorded the approval; a denied, silent or failed call charges nothing.
`STRIPE_SECRET_KEY` is read from the environment, else from the lane-d `.env` (`../lane-d/.env` next to this checkout, or `--env-file PATH`); only that
one name is read, the value is never printed or written to the JSON. It must start with `sk_test_`, otherwise the SIM stub runs and the console says so.
The charge happens after `can_charge` passes at charge time, never before: one `POST /v1/payment_intents` (stdlib `urllib`, certificate checking on) with
`payment_method=pm_card_visa`, `confirm=true`, `Idempotency-Key = mandate:<mandate hash>`, amount from the approved mandate. The console and JSON show only
the PaymentIntent id and status. A refused call prints Stripe's error type and code, not the request, and the SIM stub is recorded instead.
This is not Visa settlement: it is a Stripe test charge on a Visa test card under a TAP-style signed mandate.

## A full build in the market (`demo/build.py`, #345)
```
python3 demo/build.py --dry-run                 # the goal and the six part rounds as reducer calls, nothing written
python3 demo/build.py --live-call --reset       # one real call for the whole build, only above the allowance
python3 -m pytest demo/tests/test_build.py demo/tests/test_build_view.py   # fake market, fake call, fake Bright Data: no network
```
One goal (`type: "build_by_date"`, an owned part is a skipped goal item), then one need and one sealed round per part to buy, each closed before the next opens
(the GPU runs the bridge's own round: real MIRROR listings plus the planted sellers, judged by the real advocate). The market's rank 1 is a part's champion;
a held-back, vetoed or non-partner champion is never mandated, and a part with no eligible bid is `failed`: no call, nothing paid. Each MIRROR champion's price is re-checked
live with Bright Data (parallel, bounded; a failed read keeps the dated price and says so). Above the allowance: ONE call ("6 parts from 3 sellers, <total>"), then one mandate,
approval, payment and receipt per part; inside it: no call (method `allowance`). `demo/out/build-view.json` (the board's BuildView) is rewritten at every step.
Details and the keys added to the board's shape: `docs/changes/1705-D-build-in-the-market.md`.

## Screen bridge (`demo/bridge.py`): watch the run on /buyer and /market
```
python3 demo/bridge.py --step-delay 2 --reset   # about 90 s; --reset calls reset_demo first (keeps roles and pair codes)
python3 demo/bridge.py --dry-run                # the reducer calls, nothing written
python3 -m pytest demo/tests/test_bridge.py     # mapping with a fake client, no network
```
It runs `run_all` (this folder's real lane code), then writes each step through the market's EXISTING reducers with the role token each one demands
(buyer: `post_goal`, `post_need`; referee: `open_round`, `attach_verdict`, `attach_claim_check`, `close_round`, `create_mandate`, `record_approval`, `record_payment`;
one seller identity per demo seller: `set_floor`, `place_bid`). Needs `referee.json` and `buyer-vidyut.json` from `market/scripts/setup_roles.py` (auto-found in `.tokens/` or the launcher's) and the
local DB on 127.0.0.1:3000. Seller identities get tokens in `.tokens/bridge-<seller>.json` (gitignored) and an owner `assign_role` (the setup_roles call). Pair /buyer as `vidyut` with
`spacetime sql -s local tech-bazaar "SELECT code FROM pair_code"`. The buyer is Vidyut; the goal, owned parts and payment data are labelled SIM; the DB buyer id is `vidyut`, the only id /buyer pairs with.
The advocate's cards are bridged: `attach_advocate_card` carries Lane A's real card for each bid (a veto cites its source and disqualifies the bid at the close), the need carries
`allowed_conditions` (open-box lines rank), a bid carries all its condition lines as alternatives (the market picks the cheapest allowed one), the market drops bids over the goal cap
(`over_cap`), and `record_payment` carries `mode` (`sim` or `stripe_test`) so /market labels the SIM stub honestly. The console ends with the market's ranking, every bid it put out with its
reason, and a DIVERGENCE line if its #1 is not the demo's winner.
### Two buyers, one unit (`--two-buyers`)
```
python3 demo/bridge.py --two-buyers --reset   # after Vidyut's deal, a second SIM buyer (buyer-2) goes for the same single units
```
buyer-2 sets the same goal and the same sellers bid again, each with one unit. The unit Vidyut's round won is sold, so that line is skipped by the market with "sold out to an earlier round" and the next best bid wins. The bridge creates a `bridge-buyer-2.json` identity in `.tokens/` and gives it the buyer role for `buyer-2` only (owner `assign_role`, skipped with `--no-assign-roles`). A denied `--live-call` now also calls `deny_approval`, which releases the held unit at once. Rules: `docs/ARENA_RULES.md`.

### Real phone call inside the round (`--live-call`)
```
python3 demo/bridge.py --live-call --reset                 # beat 4 places ONE real Cartesia call; names read from pay.voice_cartesia's env file
python3 demo/bridge.py --live-call --env-file /path/to/.env --dry-run   # says where the call would go; no network, no call
```
When beat 4 starts the bridge reads the market's own `round_result` and takes rank 1 (not the demo's winner): a fresh pending mandate for exactly that
bid's deal, landed amount and seller's payee, 10 minutes (`MANDATE_MINUTES`), sent with `create_mandate`. No single readable rank 1, or a #1 that is not a bid
this run placed, stops the run there with no mandate and nothing paid; this holds for a run without `--live-call` too. A rank 1 the market marks `held back: advocate caution (...)` in its `reasons` (every bid carries a
caution, so rank 1 is only the least bad) is refused the same way (#251): no mandate, no call, "nothing was paid". The gate reads the market again after the
call, so a rank 1 that turns held back during it is not paid either. With `--live-call` it then runs
`pay.voice_cartesia.run_approval_call` for that mandate: one call to `APPROVAL_CALL_TO` only, the two-word code sent to /buyer with `issue_approval_code`
(the same code the call judges; printed as `SCREEN CODE` when the market refuses it, and also while the market module still
exports `approve_typed`, because a code on /buyer would arm that typed approval; see #191), three tries. The code reaches /buyer
only on a `--live-call` run: a run without it issues no code. After the call the market is read again, and only an
approved call plus a `pay.mandate.can_charge` pass against the market's rank 1 makes the bridge call `record_approval` and then `record_payment`. A denial (wrong code, silence, no
answer, dial failure, expired mandate) or a missing Cartesia setup prints the denial, records no approval and no payment, leaves the mandate pending and ends the run there: nothing is charged.
Before the call, the winning seller gets one CRS identity check (#257, `agents/crs.py` `check_payee`, cached per
seller for 10 minutes). A business seller (an approved business profile in `CRS_TEST_IDENTITIES_PATH`) needs a
verified check, and that check's id is bound into the mandate and checked again before the charge. A failed check,
CRS not configured, or an unreadable profile file holds the payee gate: no mandate, no call, nothing paid. When CRS
does not answer, the adapter may use its own recorded result for that seller if it is under 24 hours old (labelled
cached on the console); with none, the gate holds. A seller with no business profile is a SIM seller and is said to
be unchecked. Only a verified answer is reused, for 10 minutes; consent is read again every time. The call reads the result ("checked with CRS and
verified" or "a simulated seller, not checked with CRS"), and the console prints it.
On `--live-call` the bridge also loads `BRIGHT_DATA_API_KEY` and `TIGER_DATA_SERVICE_URL` from the same env file
as the call (the process environment wins; values are never printed) (#269). Right before the call, Bright Data
re-checks the winner's listing price (45 s limit): a live price above the quote, or out of stock, stops the call and
nothing is paid; a slow or failed read keeps the quoted MIRROR price and the console says so. The call says "the
price was checked live just now" or "the price is from a dated listing snapshot". After the close, the round's
prices go to Tiger Data as bid ticks (rank 1 is the win); a Tiger failure is one console line and the deal goes on.
`python3 -m scripts.sponsor_status` reads the same env file (`--env-file` to point elsewhere).
`--live-call --stripe` makes one Stripe test charge after the approval is recorded (never before the round). There is no scripted approval (#251, decided by Vidyut):
without `--live-call` the bridge makes the mandate, then stops at the approval gate with
"approval needs the real phone call (--live-call); nothing was paid": no `record_approval`, no `record_payment`, the held unit released with `deny_approval`,
beat 5 not played, exit 1. The only `record_approval` method the bridge sends is `voice_code`, with the call's VoiceApproval id. Rehearsals and the video
run with `--live-call`; a deal inside the buyer's allowance keeps #240's `allowance` method and needs no call. Tests use a fake client and place no call.

## Stage runner (`demo/stage.py`): one command for the video and the room
```
python3 demo/stage.py                      # check services, reset, press Enter to play each beat
python3 demo/stage.py --auto               # hands free: each beat starts after its reading delay
python3 demo/stage.py --auto --live-call   # beat 4 places ONE real Cartesia call (see above for what denies it)
python3 demo/stage.py --dry-run            # cues and reducer calls only: no check, no reset, no market
python3 -m pytest demo/tests/test_stage.py # fakes only, about a second
```
It wraps `bridge.py` (same reducers, same tokens, same live-call gate) and adds the show around it:
1. **Service check.** The launcher's own status logic (`scripts/launch.py status`) reads `--run-dir` (default `.run` in this checkout; when you run from another checkout than the live stack, pass the stack's, for example `--run-dir /path/to/bidding-royale/.run`). It refuses to start if any service is DOWN or FAILED, or if the launcher started nothing; `--force` plays anyway and says FORCED. A SKIPPED service does not block (the launcher already said why).
2. **Reset.** `reset_demo` (referee), which keeps roles and pair codes, then the beats.
3. **Five beats, in order.** 1 goal and need, 2 sealed round (open to close), 3 Shield blocks the injected listing, 4 mandate, approval, payment, 5 round 2 with the learner's lower price. Before each beat the console prints `BEAT n of 5` and one **SAY THIS** line for the narrator.
4. **Pacing.** Without `--auto` it waits for Enter before each beat (`q` stops). With `--auto` it waits `--delays` seconds between a beat's cue and the beat (five numbers, default `7,8,6,9,8`, time to say the line); `--step-delay` (default 2) is the pause between visible steps inside a beat, as in the bridge.
5. **Live call.** Approval needs the real phone call: without `--live-call` the run stops at beat 4's approval gate with exit 1 ("approval needs the real phone call (--live-call); nothing was paid"; no approval, no payment, beat 5 not played). `--live-call` is passed straight to the bridge's gate. A denial, silence or missing Cartesia setup stops the run at beat 4 with exit 1: no approval and no payment recorded, nothing charged, beat 5 not played. The mandate the call judges is made when beat 4 starts (a mandate lives 10 minutes, so a long wait at the Enter prompts cannot expire it). Retake by running again (it resets). The two-word code shows on /buyer (`issue_approval_code`); it prints as `SCREEN CODE` on this console only if the market refuses it. `--live-call` has no `--stripe` pairing: the stage runner never makes a Stripe call.
After beat 2 the runner reads the market's `round_result` back and prints its ranking; if the market's #1 is not the demo's winner it prints DIVERGENCE before beat 3, and `--auto` pauses once for Enter so the operator sees it before the beat 4 cue (the mandate that follows is the demo's winner).
Exit codes: 0 all beats played, 1 refused or stopped (service down, market refusal, denial, `q`), 130 Ctrl-C. Open /buyer (paired as `vidyut`) and /market first; the console reminds you.
The cue text for beat 4 changes with `--live-call` (the run stops at the gate versus the phone ringing); the other four cues are fixed in `stage.CUES`. The Gadget Grove (Vedant) price change in beat 5 shows on /market through the replayed round 2. Beat 5 opens with round 1's loss reports through `record_loss_report` (SIM rows: banded gap, reason and cited source, and the learner's strategy step and "what to change" line), so each seller's own screen shows its report (#216).

The bridge sets Vidyut's standing allowance ($250 per buy, $500 a month, SIM) with the referee's `set_allowance` right after the goal, so /buyer shows it and the deal still needs the call. The market starts spending this period at $0 (the run's $120 spent is not bridged).

Not bridged, so it is printed as NOT BRIDGED at the end of every run and is the Lane B gap list: goal state, denied approval attempts, seller personas,
and a floor per seller, SKU and condition (the market keeps one floor per SKU). Bridged since #216: the buyer name (`set_buyer_profile`, SIM), loss reports
(`record_loss_report`) and one SIM line per demo agent on the Fetch tile (`record_agent_event`, with the agents' own addresses from agents/common; no rows
when agents/ cannot be loaded, and the run says so).

## Tags
Every line that shows data carries one: **LIVE** (a real outside party right now; offline there is none, Stripe's test API with `bridge.py --live-call --stripe` after a real call is the only one),
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
Real merchants are never contacted or paid: the payee on a MIRROR seller is a SIM test address (`best-buy@pay.example.test`) in the offline run, and on the market (the bridge, #240) the mandate's payee is the winning seller's id (`best-buy`); no money reaches either.

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
| 4 Approval | all of `pay/`: `new_mandate`, `script_for` (closed-schema reason), `ApprovalService`, `can_charge`, `sign_request` and `verify_request` (RFC 9421 Ed25519, TAP-style), `mark_used`, replay and an edited amount both fail | call transport (transcripts typed by the runner, no Cartesia); the sim clock (+31 s per retry, no sleeping); the merchant (the runner calls `verify_request` directly) | The charge is always the SIM stub (the approval is scripted); Stripe test mode only via `bridge.py --live-call --stripe` |
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

## CRS signals into the market (`python3 -m demo.crs_relay`)
```
python3 -m demo.crs_relay --dry-run     # list the record_supplier_signal calls from .cache/crs-signals.json, touch nothing
python3 -m demo.crs_relay               # send them as the referee (needs the market to have record_supplier_signal, Lane B PR 320)
```
Reads the sanitized cache `agents/crs.py --live` writes (override with `--cache PATH` or `CRS_SIGNAL_CACHE_PATH`). Mapping, in one place
(`MARKET_SELLER`): seller_1 to seller-a, seller_2 to seller-b, seller_3 to seller-c. Only a signal with exactly the four fields, a known
band, source sandbox or recorded, and a time within the last 24 hours (not in the future) is sent; the rest are skipped with the reason, so
a seller with no signal has no row and is never shown as verified. If the market lacks the reducer the relay says so and sends nothing.
`demo/bridge.py` and `demo/build.py` run it right before each round opens, best effort (a problem is one note and the round opens anyway).
Exit 0 all sent, 1 a call was refused, 2 nothing sent.
