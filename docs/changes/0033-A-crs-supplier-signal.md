# Lane A to Lane B: CRS supplier signal

Lane A's adapter returns the existing `SupplierSignal` contract with exactly `supplier_id`, `stability`, `checked_at`, and `source`. `source` is `sandbox` for a live sandbox response and `recorded` for a genuine cached response. The accompanying reason is fixed by band:

- `verified_stable`: `Synthetic representative identity verified by CRS sandbox.`
- `caution`: `CRS sandbox returned a fraud alert; additional proof is required.`
- `not_verified`: `CRS sandbox could not verify the synthetic representative identity.`
- unavailable: `CRS sandbox check unavailable; a current recorded result may be used.`

For a recorded result, preserve the original `checked_at` and show `cached from CRS <time>`. The cache is sanitized, keyed by seller and approved persona, and usable for at most 24 hours. No raw CRS response or identity data belongs in shared market state. Consent is recorded in trusted operator setup, not inferred from a buyer request or seller bid. Proposed business mapping is `seller_1=P01`, `seller_2=P02`, `seller_3=P12`; `P16` is an optional approved step-up case. Trusted individual sellers are exempt from CRS checks.

The check covers an approved synthetic representative identity only. `verified_stable` means the documented response had an empty message list; `caution` means code `2401` and requires additional proof; malformed, adverse, mixed, or unknown responses are `not_verified`. Neither `caution` nor `not_verified` is eligible. This signal is not legal-entity verification or a financial-stability guarantee.

Lane B owns the market table/reducer, authenticated publisher integration, and visible disabled-row enforcement, including refusal at order/mandate creation. This change does not implement a market reducer, publisher, or endpoint; reducer/table names remain for Lane B to choose. Missing, expired, caution, or not-verified business signals must remain unselectable. Live CRS proof, issue owner acceptance of representative verification for the business-seller gate, and issue closure remain pending.
