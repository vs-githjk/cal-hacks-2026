# Fallback matrix (#190)

For every outside dependency: what happens when it is down or slow, whether any money can move, and the one line the
operator or the buyer sees. Each row has a test in `demo/tests/test_fallback_matrix.py` that drives the real code with a
fake failing transport. Approval is by phone call only, so no row ever falls back to another way of approving.

| Dependency | When it is down, slow or refuses | Money | The line shown |
|---|---|---|---|
| Cartesia (the approval call) | Beat 4 stops: the call denies, the held unit is released (`deny_approval`), beat 5 does not play | Nothing is paid; no approval row | /buyer: "Approval denied: Call failed, nothing was paid." Console: the same line (`pay.voice_cartesia.denial_line`; no answer, timed out and nobody spoke each have their own line) |
| Agentverse / ASI:One (the agents) | The agent feed shows every agent as down; the stage still plays from the console and the local market | No agent can place an order | Agent feed row: status `down` for each role (`scripts/agent_feed.py`) |
| SpacetimeDB (the market) | The bridge and the stage stop before writing anything | Nothing is written, nothing is paid | "STOPPED: market not reachable at http://127.0.0.1:3000 (...). Start it with `python3 scripts/launch.py up` ..." |
| Bright Data (live price re-check) | 429 (blocked), timeout (slow), no record (empty) or any other error: the quoted MIRROR price stands and the call goes on | The mandate stays at the quoted price; only a live rise above the quote or out of stock stops the call | "Live re-check: nothing readable (blocked), so the quoted MIRROR price from <date> stands" (or "no answer in time", "Bright Data not configured") |
| Tiger Data (price history) | The write raises a named error with no connection string; the demo does not depend on it | No money path uses it | Sponsor status: `Tiger Data  configured yes  result error` (or `not_configured`) |
| CRS (business seller identity) | A business payee with no fresh verified check is not payable | `payee_ok` refuses: `crs_missing`, `crs_not_configured`, `crs_expired` | "identity not checked by CRS" (or "CRS is not configured, so no identity was checked") |
| Stripe test API | A refused or unreachable call records the SIM stub instead | No money moves (test mode only, and the stub moves nothing) | "Stripe test call refused (HTTP 503, api_error/...), so the SIM stub runs"; /market: "Payment recorded (SIM stub, no money moved)" |
| Anthropic classifier (behind Shield) | Seller text that needs the classifier is held, never passed | A held seller cannot be paid | Shield verdict `quarantine`, rule `shield.classifier.unavailable` |

Not covered here: the web app itself being down (the screens are then simply not there; the console still prints every
line above).
