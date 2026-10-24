# Shield corpus results

Run date: 2026-10-23. Command: `python3 -m shield.corpus.run_corpus --write`. Classifier off, no network, rules only.

## Dev corpus (`dev.jsonl`: 30 attacks, 10 clean controls)

| Metric | Value |
|---|---|
| Attacks stopped (quarantine or block) | 30 of 30 (100.0%) |
| of which block | 15 |
| of which quarantine | 15 |
| Clean controls wrongly stopped | 0 of 10 (0.0%) |
| p95 latency per message | 2.14 ms |

Read this honestly: the dev corpus was written by the same author as the rules, so it is in-sample.
100% here shows the rules do what they were written to do, not that Shield is secure. The held-out set (Anoop, c8) and the
adaptive set (Claude-generated after the rules freeze) are the numbers to quote to Armadin. Never say "secure".

Rule hits across the 30 attacks (a case can fire several rules):

| Rule | Cases |
|---|---|
| `shield.encoded.payload` | 6 |
| `shield.exfil.send` | 4 |
| `shield.hidden.instruction` | 3 |
| `shield.hidden.text` | 2 |
| `shield.impersonation` | 2 |
| `shield.money.approval` | 7 |
| `shield.override.instruction` | 7 |
| `shield.payee.swap` | 4 |
| `shield.price.contradiction` | 4 |

Cases from outside our lane: a01 (injected listing page) and c09, c10 (honest pages) are Anoop's pages from
`data/liar_pages` (Lane C c4), copied unchanged into the corpus.

## Evasion probe (`evasion_probe.jsonl`, 10 paraphrases written after the rules, NOT tuned)

Stopped 0 of 10. Missed: p01, p02, p03, p04, p05, p06, p07, p08, p09, p10.

These are the known gaps of a deterministic rule layer: paraphrase with no trigger words, other languages,
spaced or leetspeak letters, payees given as a bank account or a name, shortened links, and instructions split
across messages. They are what the optional Claude classifier (quarantine only) and the held-out and adaptive
sets are for. They are reported, not hidden, and not asserted by a test.
