# CRS check projection contract

The CRS adapter exposes a flat `to_crs_check` projection for consumers. Each result carries `seller_id`, `product` (`tu_identity`), `verified`, fixed `reason_codes`, `checked_at`, and `origin`; an approved `persona_id` may be included when available. `origin` is one of `SANDBOX`, `CACHED`, or `NOT_CONFIGURED`. A cached result keeps its original `checked_at` timestamp. The optional preissued CRS token remains supported; username/password authentication performs one login per process and does not retry a failed login.

Missing CRS configuration is represented as `CRS_NOT_CONFIGURED` only for a genuinely absent configuration or absent profile configuration, and the buyer-owned warning remains non-blocking once per buyer goal/ROUND workflow. A present invalid or unapproved profile still fails. Configured adverse, stale, unavailable, malformed, or mismatched signals remain blocking. Existing official P01, P02, and P12 synthetic representative profiles at version 1.1.2 remain the approved profile basis.

The canonical `CrsCheck` schema is not yet present in this repository, so this note records the declared projection shape and policy without claiming exact schema validation. Contracts and callers remain the source of truth until that schema is supplied.
