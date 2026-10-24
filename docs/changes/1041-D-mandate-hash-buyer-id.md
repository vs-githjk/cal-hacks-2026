# 1041 D: the mandate hash binds buyer_id (#186)

- What: `pay.mandate.HASH_FIELDS` adds `buyer_id`. The canonical JSON is now deal_id, buyer_id, amount, currency, payee,
  tier_price, nonce, expires_at (plus crs_check_id when present). `contracts/Mandate.schema.json` `hash` description updated.
- Why: a mandate approved for one buyer could be relabelled to another buyer with the hash still valid (audit M5-1).
- Who is affected: anyone who computes a mandate hash. Every caller in the repo uses `pay.mandate.mandate_hash` or
  `new_mandate` (agents/payment.py, hyphenate/, demo/, pay/tap.py), so new mandates hash the new way with no code change.
  A mandate hashed before this change no longer verifies (`hash_mismatch`): re-quote it. Mandates live 10 minutes.
- Market (Lane B): the market stores the hash the referee sends and never recomputes it; nothing to change.
