# 1910-D #284: TAP wire format matches Visa's reference verifier; UI hook for the approval card

Lane D changed `pay/tap.py` (and `pay/merchant_sim.py`, tests, `pay/README.md`). Wire format change for
`sign_request` / `verify_request` (the seller-admission profile is untouched):

- `Signature-Input: sig2=("@authority" "@path"); created=N; expires=N; keyId="..."; alg="ed25519"; nonce="..."; tag="agent-payer-auth"`
- `Signature: sig2=:<base64>:` and a new `Signature-Agent: "https://..."` header (set `VISA_TAP_SIGNATURE_AGENT`).
- `pay.tap.TAG` is gone; use `PAYER_TAG`, `BROWSER_TAG`. `sign_request(..., tag=, signature_agent=)` are optional.
- Callers (`agents/buyer/checkout.py`, `demo/approval_flow.py`) need no change: they pass the headers dict through.

## UI hook for the approval card (Lane A / Lane C wire it; Lane D does not edit `agents/` or `web/`)

`MerchantSim.handle(...)` now returns `outcome["tap"]`:

```json
{"ok": true,  "label": "TAP signature verified", "reason": "ok",
 "verified_by": "merchant simulator (SIM), not by Visa"}
{"ok": false, "label": "Replay refused", "reason": "replayed_nonce", "verified_by": "..."}
{"ok": false, "label": "TAP signature refused", "reason": "bad_signature", "verified_by": "..."}
```

- Show `tap.label` on the approval card and keep `verified_by` as the small print (the claim is SIM, never Visa).
- `agents/buyer/checkout.py` builds `result` from a fixed key tuple
  (`("status", "reason", "charge_id", "mandate_hash", "origin")`); add `"tap"` to it so the field reaches the card.
  Until then the card can call `pay.tap.tap_status(verdict)` itself on any `verify_request` result.
- `tap` is present on every outcome that reaches TAP verification; refusals earlier in `handle` (bad body, receipt,
  no approval) have no `tap` key, so treat a missing key as "not reached".
