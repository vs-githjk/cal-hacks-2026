# 15:45 Lane C: a MIRROR store that never joined is never orderable (#333, review fix for PR #324)

Central Computers (SF) is a real store we mirror. It never agreed to sell on Tech Bazaar, so its bid is shown for
comparison and nothing may order it, put it on a mandate, charge it or pay it. The safe behaviour is the default: the
code-owned registry decides, and a bid cannot opt itself out.

- New `data/mirror/not_partners.py` (Lane C, pure): `SELLERS` (seller id to its MIRROR label), `STORES` (snapshot
  prefixes kept out of retail medians), `NOT_ORDERABLE` ("Shown for comparison, cannot be bought here."),
  `orderable(bid)` (False for a registry seller id or `orderable: false`; a non-dict fails closed) and `label(bid)`.
- Seller bid (Lane C, `agents/sellers/policy.py`): a `mirror_seller` bid carries `"orderable": false` (additive key; Bid
  has no top-level additionalProperties). `make_bid` makes no line for more units than `qty_available`.
  `mirror_seller(unknown)` returns None, and the repo root is put on sys.path once at import.
- Advocate (`agents/advocate/checks.py`): new veto kind `mirror_not_orderable`, rule id
  `advocate.mirror_not_orderable`, summary "This store is shown for comparison only and cannot be bought from here".
- `pay/reasons.py` (Lane D, one line): the same summary added to `SUMMARIES`, so `CALL_SUMMARIES <= SUMMARIES` holds.
- Buyer (Lane A, minimal guards, `agents/buyer/hunt.py` and `agents/buyer/buyer_agent.py`): `hunt.pick_best` skips a
  not-orderable bid; `eligible_for_order` refuses it; `conclude` names no winner for it (even if a market picked it),
  says "Shown for comparison, cannot be bought here. Nothing ordered." and shows the code-owned MIRROR label on its round
  line; `on_requote` refuses it before any `common.address` lookup or mandate, so the old KeyError is no longer what
  stops it. SIM and seller_1 MIRROR (Best Buy) bids are unaffected: the demo winner is unchanged.
- `hyphenate/engine.py` (Lane D, one line): `mirror_refs` skips the `centralcomputers` snapshot, so the RTX-5070-TI
  reference is the same median as without the file (the change note had claimed this; it was false for hyphenate).
- Advocate condition rule (#333 item 2): `unverified` only when neither side states a concrete condition. One concrete
  side against an unstated or different other side ((new, unknown), (unknown, used), (unknown, new)) is a condition veto
  again, as on main.

For whoever wires seller_6 or adds the store to Lane D's stage round: keep the bid's supplier id `central_computers_sf`
(or any id in `not_partners.SELLERS`); every money path refuses it. Tests:
agents/sellers/test_mirror_not_orderable.py (end to end through conclude, approve and on_requote, with the store given a
wired address), agents/sellers/test_mirror_seller.py, agents/advocate/test_checks.py, data/tests/test_central_computers.py.
