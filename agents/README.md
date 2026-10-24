# agents/ (Lane A): buyer, Quality Advocate and seller agents

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Fetch.ai uAgents for Tech Bazaar. The buyer takes a goal in ASI:One ("a GPU for 1440p that fits my case and PSU, under $800, by Friday"), remembers what the buyer already owns, runs a sealed round with five seller agents, has the Quality Advocate check every bid, and asks for approval before any payment.

## Agents

| Agent | Role | Agentverse address | Status |
|---|---|---|---|
| Tech Bazaar Buyer (@techbazaarbuyer) | Goal in ASI:One (Chat Protocol), ownership memory, sealed round, approval, Payment Protocol (buyer side) | `agent1qwxhy93uzmw5prlqldm8a2mz9gsmc2563um6th2l6z0pudw63juej97nmj8` | Registered on Agentverse (mailbox) |
| Tech Bazaar Quality Advocate (@techbazaaradvocate) | Checks fit with Lane C's checker; compares condition fields and SIM price history, recall and seller-record fixtures. At most 3 warnings with sources; can veto the cheapest bid; never sees the fee | `agent1qvxvlletez0ywdcq7da76ufzz4lvh5xvtd4fxam22g6phqzr07kvjcmhv05` | Registered on Agentverse (mailbox) |
| Byte Bros Outlet (@techbazaarseller1) | Seller agent: bids from its listings, price from policy code, never below floor | `agent1qd3gvg54tsaezed0wzpgg34rza4y6kvvfd778nj6h27j20k99d38zd3et9m` | Registered on Agentverse (mailbox) |
| Silicon Sally's Surplus (@techbazaarseller2) | Seller agent | `agent1qw9dvuwgnh570wyk8uukp0w48a03tdpmtuv8csm3qxy6t3udl3ahs2264np` | Registered on Agentverse (mailbox) |
| FlashDeal Frankie (@techbazaarseller3) | Seller agent; SIM planted trap (claims new, fixture page condition says open box) | `agent1qdcrmqy2ra2tvshq2qhc8q5rvqzpr7du77st32qynwazy48gtuvyspdm26l` | Registered on Agentverse (mailbox) |
| Bay Area PC Shop (@techbazaarseller4) | Seller agent; SIM local physical shop, fixed margin on its own cost, port 8014 | assigned when registered | Not registered yet: manual mailbox step, see below |
| ReNew Refurb (@techbazaarseller5) | Seller agent; SIM refurbisher, refurbished and open-box lines of one SKU in one bid, port 8015 | assigned when registered | Not registered yet: manual mailbox step, see below |
| Tech Bazaar Shield Client (@techbazaarshield) | Chat front door to the existing Shield HTTP screening service; no purchases or payments | `agent1q0m2z43cf3hg4cfy87hatf69ulyqkvuylm6mjv53e6y05weqmhjj6k4lknp` | Registered on Agentverse (mailbox) |

The five existing addresses come from private seeds in `agents/.env`; the Shield address comes from `agents/.env.shield`, injected into its process environment. Both files are gitignored and never committed. Seller listings, prices and records are SIM (simulated, example.com links).

Public profile verification on October 23, 2026 at 23:46 PDT: Agentverse's `GET /v1/search/agents/{address}` returned HTTP 200 for all six addresses, with matching names and handles, `status: active`, published Agent Chat Protocol 0.3.0, and READMEs containing both required badges. All six profiles were republished at 23:45 PDT; the five existing identities are unchanged. This verifies public metadata at that time, not ongoing responsiveness or ASI:One discovery. The advocate and seller Chat Protocol handlers explain their roles; shopping goals still start with the buyer.

## Seller Kit core (sellers 4 and 5, custom sellers)

Note for Abhinav: `seller_4` and `seller_5` are in `common.SELLERS` and run in `sellers/run_all.py`, so the buyer now asks five sellers. Putting them on Agentverse is a manual mailbox step that needs you: set `SELLER_4_AGENT_SEED` and `SELLER_5_AGENT_SEED` in `agents/.env` (private values; the dev defaults are public and the agent refuses to start with them in mailbox mode), run each with `SELLERS_MAILBOX=1`, then `connect.py 8014` and `connect.py 8015`, and add their addresses to the table above. Until the seeds are set, `sellers/run_all.py` in mailbox mode skips them (it prints `seller_4 skipped: set SELLER_4_AGENT_SEED`) and sellers 1 to 3 keep running; without mailbox mode all five bid locally. Their READMEs are `sellers/AGENTVERSE-seller_4.md` and `AGENTVERSE-seller_5.md`.

Every seller is described by a SellerConfig ([contracts/SellerConfig.schema.json](../contracts/SellerConfig.schema.json); change note in `docs/changes/0130-D-seller-config.md`). `sellers/sellers.json` holds all five as configs, and `sellers/factory.py` refuses a bad config (negative floor, floor above price, unknown condition, non-http listing URL) with field errors. A custom seller runs from its own file, from `agents/`:

```bash
.venv/bin/python sellers/seller_agent.py --config sellers/custom/<id>.json
```

The port comes from the config or is the next free one from 8016. The buyer's seller list is still `common.SELLERS`, so a custom seller bids only once the buyer is told its address.

## Issue #14 verification

All six agents replied through ASI:One in a fresh conversation. The buyer delivered three bids with a cited advocate veto at 00:05 PDT October 24, and a controlled advocate outage produced a visible timeout/retry message with nothing ordered at 00:06. See [ISSUE14_EVIDENCE.md](ISSUE14_EVIDENCE.md) for the conversation link, observations and verification limits. Checkout was not exercised.

After restoring the advocate, the scheduled automatic retry visibly delivered a new round with three reviewed bids in the same ASI:One conversation. No purchase approval was sent. Open a PR whose body includes `Closes #14` after verification.

The [Claude hub plan](https://claude.ai/artifact/Hjrg6QgJ8FgdmkoEAaLCeU) names a Shield client among its agent roles. The sixth agent here adds that role while keeping the issue's buyer, advocate and three sellers. A separate seller gateway is not implemented.

The [issue owner's October 23 update](https://github.com/vs-githjk/cal-hacks-2026/issues/14#issuecomment-6380938238) specifies local processes with Agentverse mailboxes and explicitly says no cloud server is needed. This updates the earlier cloud-hosting instruction in the plan. Keep the laptop awake during judging. Use the mailbox run instructions below.

## Issue #143 offline containment probe

At source snapshot `3ad940e`, the real local Shield benchmark derived 8 held-out misses (`h01`, `h03`, `h05`, `h07`, `h09`, `h13`, `h15`, `h20`). With Shield screening bypassed and deterministic SIM CRS identity fixtures, the actual buyer bid/tick, advocate, buyer review, recommendation, approval/requote callbacks preserved the baseline recommendation, payee and amount for all 8 rows. A selection control also showed the production recommendation at index 2 driving the second bid through approval and requote after the first bid's real condition mismatch was vetoed. For each resulting order and the same mandate hash, both absent approval and a real approval record for a different hash were refused by `MerchantSim` as `no_trusted_approval`; `agents.payment.commit` also refused, and the fake charger recorded zero calls. Network sentinels recorded zero attempts. This is a SIM behavioral result, not a full containment pass: the accepted `AdvocateCard` contract is still open, so the strict closed-schema test remains a dependency gate.

## Run

From `agents/`, with Python 3.12:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -q
```

On macOS/Linux, create the environment with `python3 -m venv .venv`, then use `.venv/bin/python` in place of `.venv/Scripts/python` in these commands.

Put the keys and agent seeds in `agents/.env` (see the repo's `.env.example`; values never go in git). Then, each in its own terminal:

```bash
.venv/Scripts/python sellers/run_all.py
.venv/Scripts/python -m advocate.advocate_agent
.venv/Scripts/python buyer/buyer_agent.py
```

For Agentverse and ASI:One, keep the existing private `BUYER_AGENT_SEED`, `ADVOCATE_AGENT_SEED` and `SELLER_1_AGENT_SEED` through `SELLER_3_AGENT_SEED` values (sellers 4 and 5 get their own private seeds, see Seller Kit core). Changing a seed changes the address. Do not use the public development defaults.

Set a new private `SHIELD_AGENT_SEED` for the sixth agent. `ADVOCATE_SEED`, `SELLER_1_SEED` through `SELLER_3_SEED` and `SHIELD_SEED` are aliases; existing `*_AGENT_SEED` values take priority. Do not replace the five existing seeds. Set `SHIELD_URL` to the running Shield HTTP service; the Shield client blocks if its screening service is unavailable or unconfigured.

This machine stores the Shield seed separately in the gitignored `agents/.env.shield`; `shield_client.py` does not load that sidecar automatically. To restart only the Shield client, first stop its existing process, then run this in a dedicated PowerShell terminal from `agents/` while the local Shield service is running on port 8787:

```powershell
$taskShieldConfig = Get-Content -LiteralPath .env.shield -Raw | ConvertFrom-StringData
$env:SHIELD_AGENT_SEED = $taskShieldConfig.SHIELD_AGENT_SEED
$env:SHIELD_MAILBOX = '1'
$env:SHIELD_URL = 'http://127.0.0.1:8787'
.\.venv\Scripts\python.exe shield_client.py
```

Keep that terminal open while the client runs; close it after stopping the client to discard its temporary environment. Do not print or commit the sidecar or its seed. The direct Shield command below assumes the private seed is already loaded into its process environment or configured in `agents/.env`.

Set `AGENTS_MAILBOX=1` in `agents/.env` to enable all six mailboxes. Individual flags are `BUYER_MAILBOX`, `ADVOCATE_MAILBOX`, `SELLERS_MAILBOX` and `SHIELD_MAILBOX`. Run these six processes in separate terminals from `agents/`:

```bash
.venv/Scripts/python buyer/buyer_agent.py
.venv/Scripts/python -m advocate.advocate_agent
.venv/Scripts/python sellers/seller_agent.py seller_1
.venv/Scripts/python sellers/seller_agent.py seller_2
.venv/Scripts/python sellers/seller_agent.py seller_3
.venv/Scripts/python shield_client.py
```

Register each once, while it is running, using the existing private `AGENTVERSE_API_KEY` in `agents/.env`:

```bash
.venv/Scripts/python connect.py 8001
.venv/Scripts/python connect.py 8003
.venv/Scripts/python connect.py 8011
.venv/Scripts/python connect.py 8012
.venv/Scripts/python connect.py 8013
.venv/Scripts/python connect.py 8004
```

Check each profile is Active on Agentverse, then find each by name in a fresh ASI:One chat. Local web chat fallback: `.venv/Scripts/python buyer/web_chat.py`, then open http://localhost:8080. Lane D owns mailbox flags in `scripts/launch.py`.

## Safety rules in code

Containment (issue #143, SIM, offline): **8 of 8 contained with Shield off**. The 8 held-out attacks Shield's rules do not block (the same ids `shield.bench` reports) are put into a bid's free text with Shield bypassed; the advocate's closed output still validates, the winner, payee and amount are unchanged, and no charge happens without an approval row for the mandate (`agents/tests/test_containment.py`).

### Current purchase readiness

- Market purchase actions require `MARKET_BUYER_OWNER_SENDER` to be explicitly configured with the exact authenticated buyer sender. The buyer checks this before mandate/approval and again against the frozen transaction before payment or seller completion acknowledgement. Missing or mismatched mapping fails closed; it is not inferred from a chat session.
- The buyer approves only by phone call: the real mandate-bound `ApprovalService` issues a one-time code, the private owner chat shows it and reports the call status and result, and the owner speaks the code on the call (`pay.voice_cartesia.run_approval_call`). A typed code or chat text is never approval. The service shares the buyer's persistent protected nonce store, so approval replay protection survives restarts. If the call is not configured (`CARTESIA_API_KEY`, `CARTESIA_AGENT_ID`, `APPROVAL_CALL_TO`), the buyer fails closed: the owner is told, nothing is approved and nothing is paid.
- Payment is not ready from environment variables alone. In `buyer_agent.py`, `MERCHANT_SIM`, `TAP_PRIVATE_KEY`, `SHIELD_RECEIPT_KEYS`, and `SHIELD_PAYMENT_SCREEN` start unset and have no startup bootstrap. The payment handler requires the checkout, signing, receipt-verification, and payment-screen dependencies; `SHIELD_PAYMENT_SCREEN` is a callback, not an environment setting. It is separate from `SHIELD_URL`, which is the message-screening endpoint. The current handler accepts only `SIM` payment origin; no live Stripe charge or deployed checkout is claimed.
- Build goals remain helper-only: three child goals, independent mandates/approvals, and full paid/owned completion are not wired into the buyer runtime. The current buyer source does not prove a full hunt restart or three-child build completion.

- Buyer, seller bid/order/payment handlers and advocate request handling use Shield message screening. `SHIELD_URL` configures that screening path; it is not the checkout payment-screen callback.
- Prices come from policy code, never from a model. Fit is decided by Lane C's checker, never by a model.
- If a voice-call helper is used in a separately approved integration, its reason input is limited to `{rule_id, summary, source_url}`; the summary is a fixed template per rule_id (`advocate/checks.py` CALL_SUMMARIES). The current buyer runtime does not place calls.

Where it could go wrong: the goal parser is regex-based and maps a "1440p GPU" to one SKU (SIM table until Lane C's SpecCards land); a buyer who does not state PSU connector counts gets "fit not confirmed". Condition evidence is supplied in bid fields, not independently fetched; price history, recalls and seller records use fixtures. Approval is the phone call with the spoken code; without a configured call the buyer fails closed, and checkout remains unbootstrapped.

## CRS sandbox setup (Issue #15)

Set `CRS_USERNAME` and `CRS_PASSWORD` in the private `agents/.env`; optionally set `CRS_BASE_URL` (default `https://api-sandbox.stitchcredit.com/api`). The adapter posts JSON credentials to `/users/login` once per process, caches the returned bearer token, rejects redirects, and permanently latches a failed login without retrying. Missing credentials perform zero network requests and override any old cache with `CRS not configured`. Set `CRS_TEST_IDENTITIES_PATH` there to an absolute path for a private operator JSON file outside the repository. The file has this shape; `request` must contain the exact body for the named persona from the official CRS Cal Hacks package version 1.1.2:

An optional preissued `CRS_API_KEY` may be supplied for an already-authorized sandbox process; it skips login and is never written to logs. A configured `seller_4` may be an individually classified seller with no CRS persona. A configured `seller_5` may be a business seller only when its private profile references an already approved persona such as `P01`, `P02`, or `P12`; do not invent identity bodies or public seller data.

```json
{
  "sellers": {
    "seller_1": {
      "seller_type": "business",
      "consent": false,
      "persona_ref": "P01",
      "request": { "<official request fields>": "<private values>" }
    },
    "seller_4": {
      "seller_type": "individual",
      "consent": true
    },
    "seller_5": {
      "seller_type": "business",
      "consent": true,
      "persona_ref": "P02",
      "request": { "<official request fields>": "<private values>" }
    }
  }
}
```

The proposed demo mapping is `seller_1=P01`, `seller_2=P02`, and `seller_3=P12`; set `consent` to true only after that seller's consent is explicitly recorded. `P16` is an optional approved step-up case. The adapter accepts only the exact-body digests for these official personas. Keep request bodies, identity data, and credentials out of git, logs, chat, and market state. Use the consent wording: `CRS sandbox identity check for this demo business seller's designated synthetic representative. Only a status band and check time are shared. No real-person data is submitted.`

This is a synthetic representative identity check, not business-entity verification or a credit/financial-stability guarantee. An empty documented CRS message list maps to `verified_stable`; code `2401` maps to `caution`; other, malformed, or unknown results map to `not_verified`. Configured business sellers without a valid check remain ineligible for ordering. When CRS is genuinely absent, the adapter reports `CRS_NOT_CONFIGURED` and the market may continue without a CRS gate while showing its once-only notice. Individually classified sellers are exempt using trusted operator configuration and are not checked. The adapter stores only sanitized signals in `.cache/crs-signals.json`; a genuine cached sandbox result can be reused for up to 24 hours as `source: recorded`, retaining its original `checked_at` and provenance. Its display provenance is `cached from CRS <time>`.

Lane A hands off the existing `SupplierSignal` fields (`supplier_id`, `stability`, `checked_at`, `source`) and a fixed reason derived from the band. Shared market enforcement and the greyed-out ineligible row remain Lane B work; this handoff does not implement a market reducer or publisher. For an explicit sandbox check, run from the repository root with the existing Windows interpreter:

```powershell
.\agents\.venv\Scripts\python.exe -B agents/crs.py --live
```

The equivalent command where `python3` is the configured interpreter is `python3 agents/crs.py --live`. Missing login credentials or profile configuration yields no CRS pass.

Live sandbox proof: the CRS login returned HTTP 200, and the operator-approved official synthetic representative mapping was `seller_1=P01`, `seller_2=P02`, `seller_3=P12`. Three adapter calls returned valid responses at `2026-10-24T07:50:12Z`: sellers 1 and 2 were `verified_stable` and eligible; seller 3 was `not_verified` and blocked. A separate cache fallback check returned the same dated results as `recorded` with zero additional CRS calls. Credentials and tokens remain in ignored local runtime configuration. The result verifies representative identity only. Issue owner acceptance of this scope and Lane B's shared market/UI enforcement remain pending.
