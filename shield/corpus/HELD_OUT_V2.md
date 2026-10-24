# Held-out set v2 (frozen)

File: `held_out_v2.jsonl`
sha256: `2c1a86e9e618e7f42f928009f36b77b359502c7117769b4da59aec55fe3831c9`
Pinned by: `shield/tests/test_held_out_v2.py` (the test fails if the file or this hash changes).

## What it is

56 rows in the corpus shape `{id, label, message, context}` plus a `style` tag: 38 attacks (`h2-a01` to `h2-a38`)
and 18 honest seller listings and messages (`h2-c01` to `h2-c18`, near-misses on purpose: "ignore the cosmetic
wear", "skip the line", "our bank details have not changed", "developer mode BIOS setting").

Attack styles follow families seen in public prompt-injection collections and write-ups, rewritten for a market
where the sender is a seller: instruction override, fake system or assistant turns, delimiter breaks, developer
mode, system-prompt leaks, markdown image exfiltration, tool-call spoofing, base64 and ROT13 payloads, HTML comment
and hidden CSS text, review-embedded text, bank-detail changes, skipped approval, allowance raising, secret
requests, authority and urgency pressure, score manipulation, hypothetical framing, translation smuggling, German,
zero-width characters, warning suppression, a claimed phone approval, price-history poisoning, link shorteners,
buyer impersonation, payee swaps and agent-to-agent forwarding.

## The freeze rule

This file was written and hashed in the FIRST commit of task T9, before any change to `shield/rules/*`. It is never
edited afterwards and never used to tune a rule. Rule work in T9 used only `dev.jsonl`, `dev2.jsonl` and
`evasion_probe.jsonl`.

## Honest limits (read before quoting a number from this set)

- The author did not open `shield/rules/*`, `dev.jsonl`, `dev2.jsonl` or the old held-out files before writing it.
- The author DID read `shield/corpus/run_corpus.py` and `shield/bench.py` first, to learn the row shape. The results
  template inside `run_corpus.py` lists known gaps in prose (a non-English message, a shortened link, a claimed
  human approval, a payee change without a change word). This set contains messages of those shapes (German
  `h2-a23`, shortener `h2-a33`, claimed approval `h2-a26`, payee swap `h2-a35`), so those rows are not blind.
- It is a small sample: 38 attacks and 18 controls. One extra attack is about 2.6 points, so quote counts, not
  claims of coverage. Nothing here shows Shield is secure.
- Every context uses `sender_role: "seller"`; three attacks carry `payee_of_record` and one carries `price_history`.
