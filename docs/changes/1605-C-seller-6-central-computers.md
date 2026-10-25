# 16:05 Lane C: seller_6, the Central Computers (SF) MIRROR agent (#342 item 3, approved by Vidyut)

Additive only. No existing agent address, seed, name or port changes (tested: seller_1 to seller_5 keep their
addresses with seller_6 on or off).

- `agents/common.py` (Lane A, additive): `CATALOG_SELLERS` (the five SIM sellers, unchanged), `MIRROR_SELLERS =
  ("seller_6",)`. `SELLERS` is the five plus `seller_6` only when `SELLER_6_AGENT_SEED` holds a private seed (16+
  characters, not a `*-dev` value). There is no default seed: unset, `seller_6` is not in `SELLERS` or `SEEDS`, and
  `address("seller_6")` raises a clear ValueError. `SELLER_PORTS["seller_6"] = 8016`; `BUILT_IN_ROLES` includes
  `seller_6`, so a custom seller cannot take its seed name.
- `agents/sellers/factory.py`: 8016 in `RESERVED_PORTS` and `PORT_OWNERS`; custom sellers now land on 8017 or later.
- `agents/sellers/seller_agent.py`: `build("seller_6")` reads `policy.mirror_seller("central_computers_sf")` under
  its own id `seller_6` (the buyer checks a bid's id against its sender), picks the card for the buyer's case clearance
  when the need carries `owned.case`, bids the listed price with no learning, and replies with a fixed persona line
  (the MIRROR label, never a model speaking as the store). Display name "Central Comp MIRROR" (under 20, #259). Without
  the seed, `build` exits with the fix. Its `OrderPlaced` and `CommitPayment` handlers refuse everything: no payment
  request, no completion, even for a fully approved, charged transaction (tested against the same fixtures that make
  seller_1 send).
- `agents/sellers/run_all.py`: the local seller Bureau runs `seller_6` when its seed is set and prints how to turn it
  on when not. `agents/sellers/AGENTVERSE-seller_6.md` added (five sections, the honest MIRROR label). Agentverse
  registration is not done (Abhinav, later); no avatar yet.
- `data/mirror/not_partners.py`: `seller_6` added to the registry, so every #333 guard (advocate veto, pick_best,
  eligible_for_order, conclude, on_requote) holds it back as it does `central_computers_sf` (tested end to end for both).
- `.env.example`: `SELLER_6_AGENT_SEED=` (name only).
- Tests that loop over catalog sellers with `policy.seller(n)` now use `CATALOG_SELLERS` (test_policy, test_factory,
  test_shield_context, test_mirror_seller, test_recovery `_open_round`), so the suite also passes on a machine whose
  agents/.env sets the seed.

To run on the stage Mac: put a private `SELLER_6_AGENT_SEED` in agents/.env (never commit it), then
`python sellers/run_all.py` from agents/. The buyer then asks six sellers; seller_6's bid shows as MIRROR with
"Shown for comparison, cannot be bought here." and is never approved, ordered or paid. Note: seller_6 has no Market
identity (like sellers 4 and 5), so it is not a Market candidate.
