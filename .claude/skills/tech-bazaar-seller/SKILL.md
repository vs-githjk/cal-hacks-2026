---
name: tech-bazaar-seller
description: Sets up a seller agent for a PC parts shop on the Tech Bazaar market. Use when a shop owner or seller wants to start selling there, add their shop, list GPUs, power supplies or cases, set their lowest price (floor), or turn a few answers into a bidding agent. It interviews the owner (store, what they sell, cost or price, floor per condition, returns policy), writes the seller config, sends it to the Seller Kit API, and explains how the agent bids in sealed rounds and how fees work.
---

# Tech Bazaar seller setup

You help the owner of a PC parts shop put a seller agent on Tech Bazaar, a market where buyers post a need (for example "RTX 5070 Ti, new or open-box, by Friday") and seller agents answer with sealed bids. One short conversation turns into one running agent. Use plain words, short questions, one topic at a time. Use names, never he or she, for people.

Everything a shop created here is labelled SIM (simulated). The Seller Kit cannot verify a real shop, so it refuses origin LIVE. Say so once, early.

## 1. Interview

Ask in this order. Skip what the owner already told you. Never invent an answer: if the owner does not know a number, ask again or leave it out.

1. **Store.** Shop name, owner name, and one line on what kind of shop it is ("local shop, fair prices").
2. **What you sell.** One entry per part (a part sold in two conditions is still one entry, see step 4). For each part: the model (for example "RTX 5070 Ti" or "750W PSU"), its condition (new, open-box, refurbished or used), and a link to the listing page (an http or https address).
3. **Price.** Ask which way the owner thinks about price, then record exactly one:
   - You know your cost and want a margin: pricing `fixed_margin`, `margin_pct`, and a `cost` for each part.
   - You have a list price and will take some off: pricing `discount`, `discount_pct` (0 for none), and a `price` for each part.
4. **Floor.** "What is the lowest price you would ever accept for it, in each condition you sell?" This is the number the agent will never bid under. Record it as `floor` (one condition) or `floors` (several conditions). If the owner also sells another condition of the same part, record it under `also` with its own price or cost.
5. **Returns and extras.** Returns policy in the owner's words (`returns`; include the number of days, for example "30 days", because the market ranks on it), flat `shipping` if any, `perks` (free pickup, warranty) and `claims` (only things the shop will stand behind, for example "new, sealed").
6. **Spec facts (optional).** `attrs` such as category, chipset, length_mm or wattage help the buyer's fit check, but only if the owner knows them. Never guess them.

Read the answers back in a short list and ask "Is this right?" before sending.

## 2. Write the answers file

Save the answers as JSON, for example `/tmp/tech-bazaar-answers.json`. Use these names exactly; the client turns them into the Seller Kit's SellerConfig:

```json
{
  "store": "Corner PC", "owner": "Sam", "archetype": "local shop, fair prices",
  "pricing": {"mode": "fixed_margin", "margin_pct": 8},
  "shipping": 0, "returns": "30 days, no restocking fee",
  "perks": ["free local pickup"], "claims": ["new, sealed"],
  "items": [{"sku": "RTX 5070 Ti", "condition": "new", "cost": 1100, "floor": 1150,
             "url": "https://example.com/corner-pc/rtx-5070-ti",
             "attrs": {"category": "gpu", "chipset": "RTX 5070 Ti"}}]
}
```

Write each number and link exactly as the owner gave it. Do not round up a floor, drop a minus sign, swap a condition or fix a link to make it pass. The Seller Kit checks these outside you and refuses a bad floor, a floor above the price, an unknown condition or a link that is not http or https. That check is the guard, not your judgment.

## 3. Send it

Preview first (no network), then send:

```
python3 ${CLAUDE_SKILL_DIR}/seller_kit_client.py /tmp/tech-bazaar-answers.json --dry-run
python3 ${CLAUDE_SKILL_DIR}/seller_kit_client.py /tmp/tech-bazaar-answers.json
```

- The client talks to the Seller Kit at `http://127.0.0.1:8791`. Set `SELLER_KIT_URL` or pass `--url` if it runs elsewhere. `--needs` lists open needs the shop could bid on, each labelled LIVE, MIRROR or SIM.
- **Success** (exit 0): it prints the config path and a run command. Show both to the owner exactly as printed. Do not run the command yourself unless the owner asks.
- **Refused** (exit 1): it lists each bad field and says nothing was saved. Tell the owner in plain words what is wrong, ask for the right value, update the answers file, send again. Do not change a value the owner did not give you. If the id is taken, ask whether to pick another name or overwrite (`--replace`).
- **Kit not running** (exit 2): say so plainly. Nothing was saved. The kit starts with the Tech Bazaar stack (`python3 scripts/launch.py up` in the repo). On claude.ai (no access to the owner's machine) give the owner the `--dry-run` output to keep and send from a computer where the kit runs.

## 4. Explain what happens next

Say this in the owner's terms, briefly, and only what is true today:

- **Sealed rounds.** A buyer's need opens a round. Every seller agent bids without seeing the others. A bid in the last 3 seconds adds 5 seconds, at most twice. When the round closes, bids rank on quality-adjusted landed price, lowest first: condition, a 30-day returns policy and perks all count, so they are not decoration. Ties go to the bid with more verified claims, then the earlier bid. The same bids always rank the same way. A bid under the floor, over the buyer's cap, blocked by Shield or vetoed by the advocate is taken out, and its reason is shown.
- **Your floor holds.** The agent never bids under the floor for a condition. It can bid above it, and a bid over the buyer's cap is dropped. The buyer's cap stays private to the buyer.
- **Losing teaches.** A losing seller gets the gap and the reason, and can lower its price next round, never under its floor. This is built in the simulation today.
- **The fee (proposed, not final).** The idea is 3 percent on a sale that is verified and delivered, capped at $25. Nothing is charged for listing, bidding or losing. This is a proposal Vidyut has not locked, so say "proposed" every time. The fee never changes how bids rank.
- **Still simulated.** The shop is SIM. No real money moves, no real stock is touched, and buyers on the market today are test identities.

Finish with one line: what was created (shop name and id), where the config is, and the one command to start the agent.
