# pay/ (Lane D)
Stripe on Visa card, Visa Trusted Agent Protocol signing, VIC adapter, ledger.
Tasks: docs/kickoff/D-pay-trust.md.

## What is live, what is not (d2)
- **Live in this folder:** mandate hash and verification (`mandate.py`), the used-nonce store (`replay.py`), and
  **TAP-style signing per RFC 9421; conformance checked by our merchant simulator** (`tap.py`).
- **Not live:** Stripe charge (test mode, later task), Visa Intelligent Commerce (an adapter swaps in only if Visa
  grants sandbox access). We never say "Visa settles": the payment is a Stripe test charge on a Visa test card,
  and the request signature is verified by our own merchant simulator, not by Visa.
- Python 3.12, `cryptography` for Ed25519, `jsonschema` used for schema checks only if installed (a minimal
  manual check runs otherwise). Run the tests from the repo root: `python3 -m pytest pay/tests`.

## Mandate (`pay/mandate.py`, contract `contracts/Mandate.schema.json`)
```python
from pay.mandate import new_mandate, verify, can_charge, mark_used
from pay.replay import NonceStore

store = NonceStore("/abs/path/nonces.json")      # path optional; memory only without it
m = new_mandate(deal_id="deal-A", buyer_id="b1", amount=1119.00, payee="seller-x", tier_price=None)
verify(m)                       # Verdict(ok, reason): hash, ttl cap, expiry, status (not approval)
m["status"], m["approval_id"] = "approved", "appr-1"   # set only by the approval flow
can_charge(m, store=store, deal_id="deal-A", amount=1119.00, payee="seller-x")   # the guard before any charge
mark_used(m, store=store, deal_id="deal-A", amount=1119.00, payee="seller-x")    # spends it once; a second call raises MandateError("replayed_mandate")
```
- `mandate_hash(m)` is sha256 hex over canonical JSON (sorted keys, no spaces) of `deal_id, amount, currency, payee,
  tier_price, nonce, expires_at`. Other fields (status, approval_id, buyer_id, tap_signature) are not hashed.
  A whole-number float and an int hash the same (1119.0 and 1119).
- `new_mandate` draws a random 128-bit nonce and sets `expires_at` at most 10 minutes out (default 10). Checks cap both `expires_at - created_at` and
  `expires_at - now` at 10 minutes (`ttl_too_long`), because `created_at` is not hashed.
- `can_charge` refuses unless the mandate is valid, unexpired, status `approved`, has a non-blank `approval_id`,
  matches the expected deal, amount and payee (keyword-required on `can_charge` and `mark_used`, as is `store`;
  `buyer_id` is optional), and its nonce is unused. Pass it only a mandate loaded from the server's own approval
  row: status and approval_id are not hashed. A mandate for deal A
  cannot authorize deal B. Use `idempotency_key(m)` (`"mandate:" + hash`) as the Stripe idempotency key.
- Every check returns a `Verdict` with a stable `reason`: `hash_mismatch`, `expired`, `already_used`, `denied`,
  `ttl_too_long`, `schema_invalid`, `not_approved`, `no_approval_id`, `deal_mismatch`, `amount_mismatch`,
  `payee_mismatch`, `buyer_mismatch`, `bad_amount`, `replayed_mandate`.

## TAP-style signing (`pay/tap.py`)
Signs every buyer-agent request with an RFC 9421 HTTP Message Signature (Ed25519). The signature covers
`@method`, `@authority`, `@path`, `@query`, `content-digest` and `mandate-hash`, with params `created`, `expires`,
`keyid`, `alg="ed25519"`, `nonce` and `tag="agent-browser-auth"`. The query string is covered (changing `?x=1` to `?x=2` fails); the money fields
live in the signed body.
```python
from pay.tap import load_private_key, keyring, sign_request, verify_request, attach_signature

priv = load_private_key()                          # path from VISA_TAP_PRIVATE_KEY_PATH
headers = sign_request(method="POST", url="https://merchant.example/v1/charge",
                       body=body_bytes, mandate=m, private_key=priv)   # Content-Digest, Mandate-Hash,
attach_signature(m, headers)                                           # Signature-Input, Signature

verdict = verify_request(method="POST", url=url, headers=request_headers, body=body_bytes,
                         keys=keyring(public_key), store=store,
                         expected_mandate_hash=hash_from_merchants_own_record)
```
- Body convention: a JSON object with the mandate under `"mandate"`; the verifier recomputes its hash and
  compares it with the signed `Mandate-Hash` header (pass `mandate=` to bind one explicitly).
- `verify_request` fails with a reason: `missing_header`, `bad_signature_input`, `bad_component_set`, `bad_alg`,
  `bad_tag`, `unknown_key`, `ttl_too_long`, `signature_not_yet_valid`, `signature_expired`, `digest_mismatch`
  (body changed), `bad_signature` (method, host, path, digest or hash header changed), `mandate_mismatch`,
  `mandate_hash_mismatch`, `unbound_mandate` (neither an expected hash nor a mandate in the body), `replayed_nonce`,
  plus every `mandate.verify` reason (`expired`, `already_used`, `denied`, ...) and `replayed_mandate` (the mandate nonce
  is already spent in the store). The nonce is recorded only after every other check passes, so a
  forged request cannot burn a real one. Signatures live at most 300 s (default 60 s).
- Keys: set `VISA_TAP_PRIVATE_KEY_PATH` to an Ed25519 PEM kept outside the repo. `generate_keypair(path)` writes a
  new one (mode 0600, never overwrites) for dev and tests; tests use a throwaway key in a temp dir. `*.pem` is
  gitignored. Nothing in this folder reads `.env`.

## Replay (`pay/replay.py`)
`NonceStore(path=None)`: SQLite (stdlib), in memory or in a file. `consume(namespace, nonce)` is one INSERT against a
UNIQUE (namespace, nonce) constraint, so it is True once and False after, even when two instances or two processes
share the file. A corrupt or non-SQLite file raises (fail closed) instead of loading empty. Namespaces: `mandate`,
`tap` and (d3) `approval_code`. The store does not prune old nonces; it is small for a demo.
