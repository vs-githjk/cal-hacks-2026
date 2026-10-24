# Lane A seller admission envelope

This is a separate identity proof for seller agents. It does not create a buyer mandate, payment approval, charge, or payee change. It uses the existing RFC 9421 parsing/signature primitives and Ed25519 keys in `pay.tap`, plus the existing `NonceStore` database.

## Fixed signed request profile

- Method: `POST`. The URL signature covers `@method`, `@authority`, `@path`, and `@query`.
- Exact ordered covered components: `("@method", "@authority", "@path", "@query", "content-digest", "agent-address", "admission-audience")`.
- Required headers: `Content-Digest`, `Agent-Address`, `Admission-Audience`, `Signature-Input`, and `Signature`. `Mandate-Hash` is forbidden.
- Signature parameters are `created`, `expires`, `keyid`, `alg="ed25519"`, `nonce`, and the fixed `tag="techbazaar-seller-admission-v1"`. The existing 300-second maximum lifetime and 30-second future clock skew apply.
- `Agent-Address` must exactly match the actual sender supplied by the authenticated transport. `Admission-Audience` must match the server-configured expected audience.
- The content digest signs the exact UTF-8 body bytes. The server then requires canonical JSON encoded with sorted keys, compact separators, UTF-8, and no extra fields or duplicate keys.
- Admission bodies are non-empty and capped at 64 KiB. Signature headers are bounded and ASCII/control-character checked before parsing; URL whitespace/control characters are rejected before URL parsing.
- This profile is purpose-separated from payment TAP. The payment `verify_request` path keeps its mandatory `Mandate-Hash` and spend-mandate checks unchanged.

## Canonical body

Required fields are `protocol="techbazaar/seller-admission/v1"`, `audience`, `agent_address`, `claimed_role="seller"`, `seller_of_record`, `manifest`, and `origin`. `audience` and `agent_address` must equal the server's configured audience and authenticated sender. The operator registry entry must match that sender, have role `seller`, and have the same `seller_of_record`.

For `origin="MIRROR"`, include `source_url` and timezone-aware `observed_at`; both fields are forbidden for other origins. The result's origin is taken from the operator-controlled `Registry.origin`, never promoted from a seller's body. The signed body's origin must match that trusted value. `LIVE` means the server/operator has configured a LIVE registry context; a signature alone does not prove outside participation. Seeded test entries remain `SIM`.

## Operator key pin and replay storage

The operator enrolls sellers by adding their agent address and seller-of-record to the existing Shield registry, then pins `admission_key_id` to the public-key identifier for that seller's Ed25519 key. The admission verifier restricts the keyring to that single pinned ID. Missing pins, unknown keys, denied senders, and non-seller entries fail closed. No self-registration or seller-controlled key mapping is accepted.

After the signature, sender, audience, URL, digest, and time checks pass, the verifier consumes `seller-admission:<keyid>:<nonce>` in namespace `seller-admission`. It reuses the same durable `agents/.state/state.sqlite3` `NonceStore` used by payment and does not change payment's `tap` namespace. A forged or cryptographically invalid signature does not burn a nonce. A valid signature over a malformed, non-canonical, semantically invalid, or Shield-blocked body consumes its admission nonce because payload and Shield checks follow cryptographic verification. Oversized bodies are rejected before signature verification and do not consume it.

## Caller and integration gates

`agents.examples.shield_caller.screen_message` accepts the exact Shield `/v1/shield/screen` endpoint URL, disables redirects, reads at most 64 KiB, and returns only validated `verdict` and `rule_ids`. Its transport/status/schema failures return a fixed sanitized block.

The admission verifier is transport-independent; its caller must supply the authenticated actual sender, operator registry, pinned keyring, expected audience, and existing durable replay store. Seller factory and buyer eligibility wiring are sequential integration work and remain gated on owner reconciliation. No live outside seller was contacted or verified as part of this change. Any future LIVE claim needs actual outside-bid evidence.
