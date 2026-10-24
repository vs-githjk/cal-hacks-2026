# Bazaar Shield (Lane D core, task d4)

Shield is the security API inside Tech Bazaar. It screens every message an agent is about to act on and
verifies signed payment requests against their mandate. Beat 3 of the demo: an injected listing is stopped
before the advocate reads it, and the rule that fired is shown.

Status: core is built and tested (86 tests). Lane C adds OpenAPI docs, API keys, rate limits, metering and
`shield-bench` on top of this core. Signed verdict receipts are not built yet (see Limits).

## Run it

```
python3 -m pytest shield/tests -q                     # 86 tests, no network
python3 -m shield.corpus.run_corpus --write           # dev corpus numbers, rewrites corpus/RESULTS.md
python3 -m uvicorn shield.api:app --port 8787         # the API
```

Environment (names only, no values in git):

| Name | Meaning |
|---|---|
| `SHIELD_TAP_PUBKEYS` | comma-separated base64 raw Ed25519 public keys that may sign payment requests. Empty means every `verify-mandate` call fails with `unknown_key` |
| `SHIELD_NONCE_DB` | path of the SQLite nonce store (default in memory; set a file so a restart cannot replay) |
| `SHIELD_CLASSIFIER=1` and `ANTHROPIC_API_KEY` | both required to switch the optional Claude classifier on. Off by default |
| `SHIELD_MODEL` | classifier model id. Default `claude-haiku-4-5`, **unverified until a live call answers**: if the id is wrong every call is `unavailable` (a fail-closed quarantine) and the run prints a WARNING |

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
| `shield.classifier.suspicious` / `.unavailable` | quarantine | only when the optional classifier is on (below) |
| `shield.error` | block | internal error |
| `shield.mandate.*` | quarantine or block | `verify-mandate` outcomes |

Text is normalised first (HTML entities, zero-width characters, NFKC, common Cyrillic and Greek look-alikes,
lowercase), so `ig​nore` and `&#105;gnore` are caught and the evidence span points into the original text.
The verdict is the strongest action among the rules that fired; rules never get averaged away.

## Optional classifier

`shield/classifier.py` defines `Classifier.classify(message, context) -> "SAFE" | "SUSPICIOUS"`. It runs only
on messages the rules allowed, and can only ADD a quarantine. A timeout, error or any other answer also
quarantines (fail closed). It can never lower a rule's block or quarantine, and its words never enter the
verdict. Off unless `SHIELD_CLASSIFIER=1` and `ANTHROPIC_API_KEY` are set. The Claude client is tested only with a
mocked transport: it has not been run against the live API.

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

`shield/corpus/dev.jsonl`: 30 labelled attacks (one is Anoop's injected listing page) and 10 clean controls
(two are Anoop's honest pages). `corpus/RESULTS.md` holds the dated numbers. `evasion_probe.jsonl` holds 10
paraphrases written after the rules; the rules stop none of them, and the file is there to show that.

## Limits (honest)

- Rules are keyword and structure checks. A paraphrase with no trigger words, another language, spaced or
  leetspeak letters, a payee given as a bank account or a name, a shortened link, or an instruction split over
  several messages gets through (see `evasion_probe.jsonl`: 0 of 10 stopped). The classifier is the planned
  answer for ambiguous text but is unproven here.
- The dev corpus is in-sample (same author as the rules). Quote the held-out and adaptive columns, not this one,
  and say "blocked X of Y on this corpus", never "secure".
- Payee and price rules need `context`. Without a record or history they stay silent.
- Any CSS-hidden element with text is quarantined, so a legitimate hidden menu inside a pasted page would be
  held. Listings from our mirror do not carry one.
- No signed verdict receipts yet, no rate limit, no keys, no metering (Lane C's layer). One nonce store per
  process unless `SHIELD_NONCE_DB` points at a shared file.
- Latency was measured in-process (p95 about 2 ms on the dev corpus), not over a network.
