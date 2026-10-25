# Lane D: UCP on each Seller Kit shop (#261)

Label everywhere: UCP draft spec 2026-01-11, not certified. Implemented from the 2026-01-11 overview and checkout pages
as understood; ucp.dev was not reachable from the build machine, so the shapes are not validated against the official
JSON schemas.

New routes on the Seller Kit (`seller_kit/api.py`, logic in `seller_kit/ucp.py`), per kit shop id:
- `GET /ucp/<shop>/.well-known/ucp`: the business profile. `ucp.version` 2026-01-11, service `dev.ucp.shopping` (REST
  endpoint `/ucp/<shop>`), capability `dev.ucp.shopping.checkout`, one payment handler `dev.techbazaar.phone_approval`
  (id `tech_bazaar_phone_approval`, payee `<shop>@pay.example.test`, a SIM test address).
- `POST /ucp/<shop>/checkout-sessions`, `GET` and `PUT /ucp/<shop>/checkout-sessions/<id>`,
  `POST .../complete`, `POST .../cancel`. Amounts are integer cents. The price is the shop's list price, never its floor.
- `complete` needs a Tech Bazaar mandate for exactly this session (deal_id = session id, amount = total, payee = the
  shop's payee; `pay.mandate.verify` passes). It holds the order as `complete_in_progress` with
  `order.money_moved_here: false`. No money moves and nothing is approved here: the charge stays in pay/ after the
  buyer's phone call.

Buyer side: `agents/buyer/ucp_client.py` (`discover`, `create_checkout`, `complete`). Discovery refuses another UCP
version, no checkout capability, an endpoint on another host and a shop with no phone-approval handler. Wiring it into
the buyer agent's purchase flow waits for the Lane A stack (#207 and the PRs on it).
