# Composite purchase runtime

Parent build goals now accept up to three serialized child part goals. The Market enforces the parent cap across confirmed child payments, active holds, and the proposed amount using safe whole cents. Child and ownership retries are immutable and idempotent; child Needs retain the parent SKU, condition, variant and quantity through structured tuple matching; parent completion requires checked ownership assertions or settled child coverage.

Ownership rows record the buyer's assertion, not physical possession. SIM and Stripe test payments remain distinct from real purchase evidence.
