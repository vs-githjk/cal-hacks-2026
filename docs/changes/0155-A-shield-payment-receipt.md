# Shield payment-screen receipts

Lane A adds `POST /v1/shield/screen-payment` while preserving the legacy `/screen` endpoint. The payment route accepts an exact UTF-8 Payment Protocol `RequestPayment`, a message ID, registered seller sender, and expected deal/mandate/amount/currency/payee binding. It checks one positive whole-cent USD Stripe funds entry, recipient, reference, description and seller registry identity before screening the same bytes.

When Shield allows the request and `SHIELD_RECEIPT_PRIVATE_KEY_PATH` names a valid Shield-owned Ed25519 key, it signs a closed version 1 receipt. Canonicalization is sorted compact ASCII JSON with NaN forbidden, preceded by `tech-bazaar/shield-allow-receipt/v1\n`. The signature covers receipt ID, message ID, exact request SHA-256, deal ID, mandate hash, amount in cents, currency, payee, allow verdict, integer issue/expiry times, key ID and algorithm. Receipt lifetime is at most 60 seconds.

Receipt production is optional for legacy screening; no receipt key means no receipt. A configured invalid key stops startup. Buyer-side `SHIELD_RECEIPT_PUBKEYS` is a comma-separated base64 raw Ed25519 public-key ring. Checkout and MerchantSim fail closed for a missing, invalid, expired, unknown-key, or mismatched receipt. Verification is pure and does not consume the TAP or mandate nonce.

A receipt attests only that Shield allowed those exact bytes for the signed binding within the validity window. It does not establish buyer approval, seller ownership, or permission to change the deal, amount, currency, payee, or mandate. MerchantSim and the buyer-owned checkout adapter independently compare the receipt and RequestPayment against the authenticated buyer's stored transaction.
