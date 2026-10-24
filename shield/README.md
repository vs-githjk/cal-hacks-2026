# Bazaar Shield (Lane D core, task d4)

Shield is the security API inside Tech Bazaar. It screens every message an agent is about to act on and
verifies signed payment requests against their mandate. Beat 3 of the demo: an injected listing is stopped
before the advocate reads it, and the rule that fired is shown.

Status: core is built and tested (shield and pay together: 423 tests, no network). Lane C adds OpenAPI docs, API keys, rate limits, metering and
`shield-bench` on top of this core. Signed verdict receipts are not built yet (see Limits).

## Run it

```
python3 -m pytest shield/tests -q                     # no network (a conftest removes the API key and the classifier switch)
python3 -m shield.corpus.run_corpus --write           # dev, dev2, held-out and post-freeze numbers, rewrites corpus/RESULTS.md
python3 -m shield.corpus.run_corpus --classifier      # live classifier run, ONLY with ANTHROPIC_API_KEY and SHIELD_CLASSIFIER=1 (below)
python3 -m uvicorn shield.api:app --port 8787         # the API
```

Environment (names only, no values in git):

| Name | Meaning |
|---|---|
| `SHIELD_TAP_PUBKEYS` | comma-separated base64 raw Ed25519 public keys that may sign payment requests. Empty means every `verify-mandate` call fails with `unknown_key` |
| `SHIELD_NONCE_DB` | path of the SQLite nonce store (default in memory; set a file so a restart cannot replay) |
| `SHIELD_REGISTRY` | path of the verify-agent registry JSON (default `shield/registry.json`); a bad file stops startup |
| `SHIELD_CLASSIFIER=1` and `ANTHROPIC_API_KEY` | both required to switch the optional Claude classifier on. Off by default |
| `SHIELD_MODEL` | classifier model id. Default `claude-haiku-5-5`, verified live Sat 2026-10-24 09:07 PDT with `SHIELD_CLASSIFIER=1` (see Optional classifier). If an id is wrong every call is `unavailable` (a fail-closed quarantine) and the run prints a WARNING |

## API

`POST /v1/shield/screen` (also served at `/screen` for Lane A's agents)

```
{"text": "<message or listing html>", "message_id": "m1", "sender_agent": "shady-sam",
 "context": {"payee_of_record": "shady-sam@pay.example.test",
             "price_history": [829, 799, 789], "sender_role": "seller"}}
```
Response (v1 fields, plus the v0 fields `message_id`, `sender_agent`, `reasons`, `attack_type`):
```
{"verdict": "allow|quarantine|block", "rule_ids": ["shield.payee.swap"], "severity": "none|low|medium|high|critical",
 "evidence_spans": [{"rule_id": "...", "start": 0, "end": 72, "text": "first 80 chars of the caller's own text"}],
 "latency_ms": 0.4, "request_id": "...", "version": "shield-1.0.0"}
```
`context` is optional. `payee_of_record` turns on the payee rule, `price_history` (prices from our own data,
Shield never calls the network) turns on the price rule, `sender_role` (`seller` default, `buyer`, `advocate`,
`marketplace`) lets a buyer agent say it is the buyer agent.

`POST /v1/shield/verify-mandate`
```
{"method": "POST", "url": "https://merchant.example/charge", "headers": {...Content-Digest, Mandate-Hash,
 Signature-Input, Signature}, "body": "<exact body string>", "expected_mandate_hash": "...",
 "expected": {"deal_id": "...", "amount": 1119, "payee": "..."}}
```
Wraps `pay.tap.verify_request` and the mandate checks. A payee, amount, deal or hash mismatch is
`quarantine` with `shield.mandate.mismatch` plus the specific reason; every other failure (tampered body,
replayed or expired signature, unknown key) is `block`. A successful call consumes the request's nonce, so
the same signed request presented twice blocks the second time. Keys come only from the server.

`POST /v1/shield/verify-agent` (task d4 follow-on)
```
{"agent_address": "agent1q...", "claimed_role": "seller|buyer|advocate|marketplace",
 "seller_of_record": "byte-bros-outlet", "manifest": {"name": "...", "description": "..."}}
```
Same verdict shape (plus the v0 fields). The address is looked up in the allowlist `shield/registry.json` (every
entry is SIM: the demo buyer, advocate and sellers). Outcomes:

| Finding | Rule id | Verdict |
|---|---|---|
| address not in the registry (unknown agent, fail closed) | `shield.agent.unregistered` | quarantine |
| address on the denylist (wins over the allowlist) | `shield.agent.denylisted` | block |
| claimed role differs from the registry entry | `shield.agent.role_mismatch` | block |
| seller of record missing or different from the registered one | `shield.agent.seller_mismatch` | quarantine |
| a name (manifest name, title, handle, seller of record) that contains Tech Bazaar, Bazaar Shield, Shield, advocate or buyer and is not the agent's own registered name, or an unregistered agent claiming buyer, advocate or marketplace | `shield.agent.impersonation` | block |
| malformed input (bad address, unknown role, nested manifest values) | `shield.agent.malformed_request` | block |
| the manifest text itself fails `screen` (injection in a description) | the screen rule ids | per rule |

Names are compared after homoglyph, leetspeak and letter-spacing folding, so `Tеch B4zaar` is caught. `allow` only
when the address is registered, role and seller of record match and nothing else fired. Not checked here: a TAP
signature on the request (Lane A's a9 owns that); this is the registry layer. The log holds a hash of the address.

`POST /v1/advocate/reason` (a10): see `pay/README.md`. Body `{"rule_id": "...", "source_url": "..."}`, answer
`{rule_id, summary, source_url}` with the summary rendered from a template table only.

`GET /v1/shield/rules`, `GET /v1/shield/health`.

Limits and status codes: a message over 20000 characters is not parsed; it returns `quarantine` with
`shield.encoded.payload`. A request body over 64 KB returns HTTP 413. A malformed JSON body returns HTTP 422.
**Callers must treat any non-200 response (413, 422, 5xx, timeout) as block.** `verify-mandate` needs `expected`
with all of `deal_id`, `amount` and `payee`; a missing one returns `block` with `shield.mandate.malformed_request`.

Fail closed: any internal error, malformed message or malformed context returns `block` with `shield.error`.
No free text from any model is ever put in a verdict. Logs hold a sha256 prefix, the verdict and rule ids,
never message bodies.

## Rules (one file each in `shield/rules/`)

| Rule id | Action | What it catches |
|---|---|---|
| `shield.override.instruction` | block | "ignore previous instructions", "system:", "you are now ...", "note to shopping agents", and similar |
| `shield.hidden.instruction` | block | CSS-hidden elements or HTML comments that carry an instruction, a money push or an exfil request |
| `shield.hidden.text` | quarantine | hidden elements with other text, or 3 or more zero-width and bidi characters |
| `shield.payee.swap` | quarantine | a payee or payout address that differs from `payee_of_record` |
| `shield.money.approval` | block | "already approved", "skip the call", "charge now", "pre-verified", "without calling the buyer" |
| `shield.price.contradiction` | quarantine | a "was $X" price more than 5 percent above anything in `price_history` |
| `shield.exfil.send` | quarantine | "send the budget to a URL, webhook or mailbox", image-beacon links with data in the query |
| `shield.encoded.payload` | quarantine | over 20000 characters, base64 or hex blobs, escape runs, mixed-script look-alike words |
| `shield.impersonation` | block | claiming to be Tech Bazaar, the advocate or the buyer's agent (unless `sender_role` says so) |
| `shield.intent.approval_bypass` | block | any wording that tells the buyer side to skip, waive or pre-clear an approval ("kindly bypass the advocate review", "no need to loop in the buyer", "pre-cleared") |
| `shield.intent.override` | block | paraphrases of "ignore your earlier instructions" ("set aside whatever guidance you were given earlier") |
| `shield.intent.payment_redirect` | quarantine | a changed account, wallet, beneficiary or payee ("remit to our new account", "banking details were updated"); a "have not changed" is allowed |
| `shield.intent.authority_claim` | quarantine | an authority or assumed role plus an action ("compliance requires ... without the usual approval", "as the buyer's assistant I am authorizing") |
| `shield.intent.agent_directed` | quarantine | an instruction aimed at "the agent" or "the assistant" inside seller text ("Dear AI agent", "Assistant, when you summarise ..."); off for buyer, advocate and marketplace senders |
| `shield.classifier.suspicious` / `.unavailable` | quarantine | the optional classifier (below); `.unavailable` is also the fail-closed answer for a secret-ask candidate when there is no classifier |
| `shield.classifier.secret_ask` | quarantine | the classifier says a seller sentence asks for a password, card number, CVV, seed phrase, OTP, PIN or key (below) |
| `shield.error` | block | internal error |
| `shield.mandate.*` | quarantine or block | `verify-mandate` outcomes |

Text is normalised first (HTML entities, zero-width characters, NFKC, common Cyrillic and Greek look-alikes,
lowercase), so `ig​nore` and `&#105;gnore` are caught and the evidence span points into the original text.

**Folded views (generalization).** The prose rules (override, money, exfil, impersonation, intent, and the signal
check inside hidden elements) also run on folded copies of the message: accents dropped, runs of single letters
joined (`i g n o r e`, `s.k.i.p`, and a single-spaced `s k i p t h e ...` re-spaced with a small word list),
leetspeak decoded (`1gn0re`, with `1` read both as i and as l). Digits and emails stay intact for the payee and
price rules, which never run on folded text. Spans map back to the caller's raw text.

**Intent lexicons with co-occurrence scoring** (`shield/rules/intent.py`). Word lists for English, Spanish and Hindi
transliteration are grouped into roles (skip, gate, cleared, proceed, approve, urgent, authority, assumed role,
change, destination, pay verb). A pair counts only when its two halves sit within 70 characters inside one
sentence (adjacent sentences count only for "cleared + proceed" and authority claims). A strong pair scores 3,
boosters add 1, an intent fires at 3 or more, so one weak word ("urgent", "compliance", "skip") never fires alone.
The lexicons are the part to read when a paraphrase is missed: `RESULTS.md` lists what they still miss.
The verdict is the strongest action among the rules that fired; rules never get averaged away.

## Optional classifier

`shield/classifier.py` defines `Classifier.classify(message, context) -> "SAFE" | "SUSPICIOUS"`. It runs only
on messages the rules allowed, and can only ADD a quarantine. A timeout, error or any other answer also
quarantines (fail closed). It can never lower a rule's block or quarantine, and its words never enter the
verdict. Off unless `SHIELD_CLASSIFIER=1` and `ANTHROPIC_API_KEY` are set. The model id is `SHIELD_MODEL` (default
`claude-haiku-5-5`). The unit tests use a mocked transport only. **Live check, Sat 2026-10-24 09:07 PDT** (conductor, default
model `claude-haiku-5-5`, `SHIELD_CLASSIFIER=1`): the secret-ask question quarantined "State promptly, your password.",
"State the 16-digit card number." and "Name your seed phrase", and allowed "State: like new, factory reset, no password
set.", "Name and password are printed on the sticker underneath." and "State for parts, the password unknown.", at 0.9 to
1.9 s per call. Six lines is a smoke test, not a measured recall. **Earlier live check, 2026-10-23:** `claude-haiku-4-5`
and `claude-haiku-4-5-20251001` answered HTTP 200 on a one-word call. One live corpus run
(`--classifier`, `claude-haiku-4-5`, 1.5 s timeout) gave, rules only -> rules plus classifier: dev 30 -> 30 of 30 with
false positives 0 -> 1 of 10; dev2 30 -> 30 of 30, false positives 0 of 15; held-out probe 6 -> 10 of 10;
post-freeze check 6 -> 12 of 12; 0 calls unavailable. The classifier caught all 10 messages the rules missed
(the only ones it was asked about, plus the controls). Cost of that: one false positive on a dev control (its id was
not printed in that run; the runner now prints it) and a model call, about 0.5 s each, for every message the rules
allow. Samples are small (10 to 15 per set): treat it as a promising layer, not a measured recall.

`python3 -m shield.corpus.run_corpus --classifier` runs the four corpora with and without the classifier. It makes
network calls ONLY when `ANTHROPIC_API_KEY` and `SHIELD_CLASSIFIER=1` are both set (in the environment or in a
`.env` file in the repo root, where only `ANTHROPIC_API_KEY`, `SHIELD_CLASSIFIER` and `SHIELD_MODEL` are read, into a
copy of the environment). The key is never printed. Otherwise it prints why it did nothing and exits 0. It reports
"classifier suspicious" (a real catch) and "classifier unavailable" (timeout, error or a wrong model id, which
quarantines by fail-closed design) separately and prints a WARNING if any call was unavailable: do not quote
unavailable quarantines as recall.

**Secret asks go to the classifier, not to a regex.** `shield/rules/secret_ask.py` is a cheap, deliberately broad
filter: a sentence with an ask verb (state, name, tell, give, send, share, provide, enter, type, reply, confirm, read,
text, verify, reveal, submit, paste, in base, -s and -ing forms) or an ask form ("what's your ...", "need your ...",
"your ...?") and a secret noun (password, passcode, card number, CVV, seed phrase, OTP, PIN, verification or security
code, login, credentials, API key, private key, "the code we texted you", also split as "pass word" or "pass-word") is
a CANDIDATE. Sentences end at . ! ? ; or a blank line, a single line break counts as a space, and simple HTML tags are
ignored. Connector pins ("8-pin", "6+2 pin") and "brand / model / product / user name" are not matched. Wording alone cannot separate "State your password." from
"State: like new, no password set.", so candidates are sent to `Classifier.classify_secret_ask(text, context)`,
which answers the closed schema `{ask_for_secret: bool, reason_code}` (`reason_code` is one of
`requests_secret`, `item_description`, `condition_label`, `other`). Only the candidate sentences are sent, and only
for seller-side text (every `sender_role` except buyer, advocate and marketplace, after trimming and lowercasing, so
"seller_agent", "vendor", "Seller " and a missing role all count) that no other rule already decided. Yes gives
quarantine `shield.classifier.secret_ask`. No classifier (no key, `classifier=None`), a timeout (1.5 s per socket
operation and 4 s per classifier call; a seller message with a candidate can make two calls, the secret-ask one and
the general one, so about 8 s in the worst case), an error, a self-contradicting answer (`ask_for_secret` false with
`requests_secret`) or any answer outside the schema gives quarantine `shield.classifier.unavailable` for a candidate (fail closed); text
that is not a candidate is never affected, and buyer, advocate and marketplace text is never held for this.
Consequence: with the classifier off, an honest seller line such as "State: like new, no password set." is
quarantined. The unit tests use a fake classifier; the live prompt and default model were checked on the six lines above only.

## How a marketplace calls Shield (Armadin or any agent market)

Put one call in front of every point where an agent would act on text from another party:
1. Seller listing or bid arrives: `POST /v1/shield/screen` with the text, the seller's payee of record and the
   price history you hold. Only `allow` goes to the buying agent. `quarantine` goes to a human or is dropped
   with the rule shown. `block` is never delivered.
2. Before money moves: `POST /v1/shield/verify-mandate` with the signed request, the expected deal, amount and
   payee. Pay only on `allow`.
3. Treat a non-200, a timeout or a missing `verdict` as `block`.

Lane A's `agents/common.py screen()` already posts `{message_id, sender_agent, text}` to `$SHIELD_URL/screen`
and reads `verdict` and `reasons`; both still work. Pass `context` too, or the payee and price rules stay off.

## Corpus

`shield/corpus/RESULTS.md` holds the dated numbers, reported separately: dev, dev2, held-out and a post-freeze check.
- `dev.jsonl`: 30 attacks (one is Anoop's injected listing page) and 10 clean controls (two are Anoop's honest pages). In-sample.
- `dev2.jsonl`: 30 paraphrase attacks in six wording families and 15 new clean controls. A second development set, in-sample.
- `evasion_probe.jsonl`: 10 paraphrases, the HELD-OUT set. Frozen: a test pins its sha256, and no rule was tuned to it.
  Caveat in `RESULTS.md`: the author had read it before writing the lexicons, so its number is an upper bound.
- `fresh12.jsonl`: 12 paraphrases written after the rules froze and run once; the best guess at real recall.
Before the generalization the rules stopped 0 of the 10 probe rows.

## Limits (honest)

- Rules are keyword, lexicon and structure checks. Wording with no lexicon word, a language outside English,
  Spanish and Hindi transliteration, soft requests for private data, shortened links, claims with no action word,
  or an instruction split over several messages still gets through (see `RESULTS.md`: the held-out probe is
  stopped 6 of 10 with a caveat, the post-freeze check 6 of 12). The classifier is the planned answer for
  ambiguous text but is unproven here.
- Intent rules trade recall for false positives: a seller text that says it is the buyer ("as the buyer of
  record ... I accept") is quarantined by design when `sender_role` is `seller`.
- Messages over 20000 characters are quarantined unparsed; request bodies over 64 KB get 413.
- The dev corpus is in-sample (same author as the rules). Quote the held-out and adaptive columns, not this one,
  and say "blocked X of Y on this corpus", never "secure".
- Payee and price rules need `context`. Without a record or history they stay silent.
- Any CSS-hidden element with text is quarantined, so a legitimate hidden menu inside a pasted page would be
  held. Listings from our mirror do not carry one.
- No signed verdict receipts yet, no rate limit, no keys, no metering (Lane C's layer). One nonce store per
  process unless `SHIELD_NONCE_DB` points at a shared file.
- Latency was measured in-process (a few ms for ordinary messages, up to about 150 ms for an adversarial 20000-character one), not over a network.
