# Lane A to Lane B: CRS supplier signal

Lane A's adapter returns the existing `SupplierSignal` contract with exactly `supplier_id`, `stability`, `checked_at`, and `source`. `source` is `sandbox` for a live sandbox response and `recorded` for a genuine cached response. The accompanying reason is fixed by band:

- `verified_stable`: `Synthetic representative identity verified by CRS sandbox.`
- `caution`: `CRS sandbox returned a fraud alert; additional proof is required.`
- `not_verified`: `CRS sandbox could not verify the synthetic representative identity.`
- unavailable: `CRS sandbox check unavailable; a current recorded result may be used.`

For a recorded result, preserve the original `checked_at` and show `cached from CRS <time>`. The cache is sanitized, keyed by seller and approved persona, and usable for at most 24 hours. No raw CRS response or identity data belongs in shared market state. Consent is recorded in trusted operator setup, not inferred from a buyer request or seller bid. Proposed business mapping is `seller_1=P01`, `seller_2=P02`, `seller_3=P12`; `P16` is an optional approved step-up case. Trusted individual sellers are exempt from CRS checks.

The check covers an approved synthetic representative identity only. `verified_stable` means the documented response had an empty message list; `caution` means code `2401` and requires additional proof; malformed, adverse, mixed, or unknown responses are `not_verified`. Neither `caution` nor `not_verified` is eligible. This signal is not legal-entity verification or a financial-stability guarantee.

Lane B owns the market table/reducer, authenticated publisher integration, and visible disabled-row enforcement, including refusal at order/mandate creation. This change does not implement a market reducer, publisher, or endpoint; reducer/table names remain for Lane B to choose. Missing, expired, caution, or not-verified business signals must remain unselectable.

Live proof obtained on 2026-10-24: one sandbox login returned HTTP 200, followed by three valid adapter responses using the explicitly operator-approved mapping `seller_1=P01`, `seller_2=P02`, `seller_3=P12`. At `2026-10-24T07:50:12Z`, sellers 1 and 2 were `verified_stable` and eligible; seller 3 was `not_verified` and blocked. An independent cache fallback check returned the same original timestamps as `recorded`, with zero further calls. Credentials remain in ignored local runtime configuration; no identity bodies or provider responses are recorded here. Issue owner acceptance of synthetic representative verification for the business-seller gate, Lane B shared market/UI integration, and issue closure remain pending.
