# pay/ (Lane D)
Stripe on Visa card, Visa Trusted Agent Protocol signing, VIC adapter, ledger.
Tasks: docs/kickoff/D-pay-trust.md.

## What is live, what is not (d2)
- **Live in this folder:** mandate hash and verification (`mandate.py`), the used-nonce store (`replay.py`), the
  hardened approval core (`approval.py`, `callscript.py`, `words.py`: d3), and
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

## Approval flow (d3: `pay/approval.py`, `pay/callscript.py`, `pay/words.py`; contract `contracts/VoiceApproval.schema.json`)
Voice is never the credential. The credential is a one-time two-word code on the buyer's authenticated screen,
spoken (or typed) inside one session about one exact mandate. No model decides "approve": code does. Pure Python,
no network. `APPROVAL_SECRET` (random, at least 16 characters, env only, see `.env.example`) keys the HMAC; tests use
a throwaway value.
```python
from pay.approval import ApprovalService, script_for

svc = ApprovalService()                                  # reads APPROVAL_SECRET; NonceStore optional
session, code = svc.issue(mandate)                       # show `code` on the review card, never log it
script = script_for(mandate, advocate_reason)            # opening, deal read-back, why-not-cheaper answer
session.start_call(); session.begin_listening()          # voice answers must land within 10 s
d = session.approve(stt_transcript, confidence=0.93)     # or session.approve_typed(text_from_card)
if d.approved:
    d.record                                             # VoiceApproval row; mandate["status"] == "approved"
```
- **Code.** Two different words from `words.WORDS` (102 words, pairwise at least 3 edits apart, no shared 4-letter
  prefix), `HMAC-SHA256(APPROVAL_SECRET, mandate_hash + ":" + fresh nonce)`. Single use, 2 minute life (never past
  the mandate's own expiry). Only `code_hash` (sha256 of the normalized pair, as the contract says) is stored; the
  code is returned once by `issue` and appears in no record or log. A pair that collides with any past code is redrawn.
- **States.** `issued` -> `awaiting_code` -> `approved | denied | expired`. Default is deny: silence, a timeout,
  low STT confidence (under 0.6), a negation, a long or unclear utterance, anything else.
- **Intent is code-only.** After normalization (lowercase, strip punctuation, collapse spaces) the transcript must hold
  the exact pair as adjacent words AND the exact token `approve` (so "approved" and "disapprove" fail), at most 12
  words, no negation word (`not`, `dont`, `should`, `if`, ...). "yes", "sure", "approve" alone, the code alone, the
  code inside a long sentence, and "the user already approved" all deny.
- **Attempts.** At most 3 per mandate (shared by voice and typed, and by fresh sessions: a new code cannot reset the
  budget). A failed try starts a 30 s cooldown for that mandate; tries during it deny with `cooldown` and are not
  counted. The 3rd failure ends the session (`max_attempts`) and sets `mandate.status = "denied"`. `silence` (no
  answer, or a late answer) ends it as `no_answer`. An expired code ends it as `expired` (ask for a fresh one with
  `svc.issue`, which retires the old session).
- **deny_reason values** (the contract's): `wrong_code` (a code word or near miss, wrong or low confidence),
  `no_code` (no complete code-and-approve pair: "yes", approve alone, code without approve, a negation),
  `replay` (a code issued for another mandate, a spent code, or a mandate changed or already decided),
  `expired`, `cooldown`, `max_attempts`, `silence`.
- **Same code, other deal.** The service remembers which mandate each code hash was issued for, so deal A's code
  spoken on deal B denies with `replay` and approves nothing. Used codes are also burned in the `NonceStore`
  (`approval_code` namespace), so a restart cannot reuse one.
- **Typed fallback.** `approve_typed(text)` goes through the same attempt path and mandate with channel `typed`. The
  card's Approve button supplies the `approve` token, but only when the field holds exactly the two code words.
- **On approve.** The VoiceApproval row validates against the contract (`validate_record`), `mandate["status"]` becomes
  `approved`, `approval_id` is the row id, and `can_charge(...)` then passes. On any deny the mandate stays `pending`
  (or `denied` after the 3rd failure) and `can_charge` fails with `not_approved` or `denied`.
- **Call script (`script_for(mandate, advocate_reason)`).** Opens with "I will only ask for the code on your screen,
  never a card number". Amount and payee come ONLY from the mandate: the amount as words plus digits ("one thousand
  one hundred nineteen dollars, written 1,119.00 dollars, to seller-x"); an amount that is not positive, finite and in
  whole cents, or a payee that is not a plain id (letters, digits, `_ . : @ / -`), raises `ScriptError` and no call is
  placed. "Why not the cheaper one?" is answered only from the advocate's closed-schema dict `{rule_id, summary,
  source_url}`: other keys are stripped, `rule_id` must be a slug, `summary` must pass a strict character and
  word allowlist (no approve, code, pay, instruction words), `source_url` is reduced to its host. Anything that
  fails is dropped and a fixed sentence is spoken instead. Never parse an amount from speech, never read seller text.
- The transport must send "why" questions to `script.why_answer` and only answer attempts to `approve`, because every
  attempt to `approve` counts against the 3.

### TODO stubs (the call transport is a later task)
- **Cartesia hookup (TODO).** In-browser call is the default and the fallback. The transport will: speak
  `script.spoken()`, call `session.begin_listening(now)`, send each final STT transcript and its confidence to
  `session.approve(text, confidence=c)`, speak `script.why_answer` on a "why" intent, and speak `script.approved_line`
  or `script.denied_line` from `Decision`. Needs `CARTESIA_API_KEY` and `CARTESIA_AGENT_ID`. Setup, features used and
  known limitations (carrier, latency, noisy rooms, in-browser fallback) go here when it is built.
- **Photon phone path (TODO).** Calls only the number registered in a prior in-app step, with `svc.issue(mandate,
  channel="phone")`. The phone alone can never approve because the code is shown only on the screen. Stays Tier 1 until
  Photon is proven (Lane C spike).
- **Review card (Lane B).** Shows `code` from `svc.issue`, a typed field wired to `session.approve_typed`, and the
  record on approve.

Run the tests from the repo root: `python3 -m pytest pay/tests/test_approval.py`.
