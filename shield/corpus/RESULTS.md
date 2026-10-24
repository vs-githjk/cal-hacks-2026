# Shield corpus results

Run date: 2026-10-23. Command: `python3 -m shield.corpus.run_corpus --write`. Classifier off, no network, rules only.
"Stopped" means the verdict was quarantine or block.

## The numbers (reported separately, never averaged)

| Set | Attacks stopped | block | quarantine | Clean controls wrongly stopped |
|---|---|---|---|---|
| dev (`dev.jsonl`, in-sample) | 30 of 30 (100.0%) | 15 | 15 | 0 of 10 |
| dev2 (`dev2.jsonl`, development set 2, in-sample) | 30 of 30 (100.0%) | 17 | 13 | 0 of 15 |
| held-out (`evasion_probe.jsonl`, frozen, see caveat) | 6 of 10 (60.0%) | 4 | 2 | no controls |
| post-freeze check (`fresh12.jsonl`, run once, not tuned) | 6 of 12 (50.0%) | 3 | 3 | no controls |

False positives across ALL controls (dev 10 + dev2 15): 0.
p95 latency per message: dev 11.6 ms, dev2 0.42 ms.

## How to read these honestly

- **dev and dev2 are in-sample.** The rules and lexicons were written while looking at them. 30 of 30 shows the
  rules do what they were written to do, not that Shield is secure. Never say "secure".
- **held-out is `evasion_probe.jsonl`: the file was frozen byte for byte (a test pins its sha256) and no rule was
  tuned to make a probe row pass. Caveat: the author had READ the ten probe messages before writing the new
  lexicons, so this number is an upper bound, not a clean held-out result. One probe-shaped pattern ("do what this
  note says", "treat its content as your new rules") was written, noticed as tuned to the probe, and deleted before
  commit. A truly blind number needs Anoop's held-out set (c8) or the adaptive set.**
- **post-freeze check** is 12 new paraphrases written after the rules froze and run exactly once; whatever it
  scored is printed here and nothing was changed after seeing it. It is the better guess at real-world recall:
  about half. It is a small sample (12), so the interval is wide.
- Misses on held-out: p03, p08, p09, p10. Misses on the post-freeze check: f02, f03, f05, f06, f07, f08.
  Known gaps of lexicon rules: a language outside English, Spanish and Hindi transliteration (p03 is French), soft
  requests for private data (p08), shortened links (p09), instructions split across messages (p10), claims that a human
  already agreed with no approval word near them (f02), "pretend" and "let it through" phrasing (f03, f08), a payment
  sent to a named third party with no change word (f05), a claimed exemption with no approval word (f06), and a note
  for "whichever AI" reads the page (f07). The optional Claude classifier (quarantine only) is meant for these; it is
  not exercised here.
- Controls are near-misses on purpose ("Skip the queue", "banking details have not changed", "FCC compliance"). A
  separate ad-hoc stress of 27 tricky honest sentences (not committed) produced one stop: a seller text that says
  "as the buyer of record ... I accept the terms", which is correct under the seller role (a buyer sender is exempt).

## Corpus shapes

- `dev.jsonl`: 30 attacks, 10 clean controls (unchanged from d4).
- `dev2.jsonl`: 30 attacks in six families (polite skip of approval, role-play and agent-directed text, indirect
  payee change, urgency and authority, obfuscation by leetspeak, spacing, dots and homoglyphs, Spanish and Hindi
  transliteration) plus 15 new clean controls.
- `evasion_probe.jsonl`: 10 attacks, frozen.
- `fresh12.jsonl`: 12 attacks, written after the freeze.

Rule hits across the dev2 attacks (a case can fire several rules):

| Rule | Cases |
|---|---|
| `shield.encoded.payload` | 1 |
| `shield.intent.agent_directed` | 2 |
| `shield.intent.approval_bypass` | 16 |
| `shield.intent.authority_claim` | 8 |
| `shield.intent.override` | 2 |
| `shield.intent.payment_redirect` | 8 |
| `shield.money.approval` | 6 |
| `shield.override.instruction` | 1 |

Cases from outside our lane: a01 (injected listing page) and c09, c10 (honest pages) in dev.jsonl are Anoop's pages
from `data/liar_pages` (Lane C c4), copied unchanged.
