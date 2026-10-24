# Seller admission

`agents.seller_admission.verify_admission_request` admits an already operator-enrolled seller only after a purpose-separated Ed25519 request signature, authenticated sender match, audience match, exact canonical body, registry role/seller-of-record, and existing Shield manifest check all pass. It does not issue a mandate, approval, charge, or payee change.

## Sign an admission request

Construct the canonical body described in [`docs/changes/0414-A-seller-admission-envelope.md`](../docs/changes/0414-A-seller-admission-envelope.md), then call `sign_admission_request(payload=..., method="POST", url=..., agent_address=..., private_key=...)`. The helper returns the exact body bytes and headers. The server must obtain `actual_sender` from its authenticated transport, not from the body or a caller-provided field.

The operator must pin `admission_key_id` on the existing seller registry entry and provide the matching public key. Admission consumes the shared SQLite `NonceStore` under its own `seller-admission` namespace. Invalid cryptographic signatures do not consume the nonce; a cryptographically valid request with an invalid payload may consume it.

`origin` comes from the operator-controlled `Registry.origin`. A seller cannot make an admission result `LIVE` by changing its JSON. MIRROR entries require a listing URL and timezone-aware observation time; seeded demo entries remain SIM. This implementation has no outside-seller evidence and makes no LIVE-participation claim.

## Standalone Shield caller

`agents.examples.shield_caller.screen_message` POSTs to the exact `https://host/v1/shield/screen` URL. It validates the response contract and returns a fixed `block` result on HTTP, timeout, redirect, size, or schema failures. Unit tests mock the opener and perform no network calls.
