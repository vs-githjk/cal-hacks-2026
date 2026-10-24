"""Run the attack corpus through Shield. `python3 -m shield.corpus.run_corpus --write` rewrites RESULTS.md.

"Block rate" here means the share of attack cases that were stopped (verdict quarantine or block). The
classifier is always off: results are deterministic and need no network.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date

from shield.classifier import SUSPICIOUS_RULE, UNAVAILABLE_RULE, ClaudeClassifier
from shield.core import screen

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.join(HERE, "dev.jsonl")
PROBE = os.path.join(HERE, "evasion_probe.jsonl")  # HELD-OUT: frozen, never edited, never tuned against
DEV2 = os.path.join(HERE, "dev2.jsonl")
FRESH = os.path.join(HERE, "fresh12.jsonl")  # written after the rules froze, run once, not tuned
RESULTS = os.path.join(HERE, "RESULTS.md")
ENV_FILE = os.path.join(HERE, "..", "..", ".env")  # repo root; read only for the names in ENV_NAMES


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run(path: str, classifier=None) -> dict:
    """Run one corpus. `classifier=None` is rules only (the default, deterministic, no network)."""
    rows = load(path)
    lat, missed, wrong_rule, fp_ids, per_rule = [], [], [], [], {}
    blocked = quarantined = attacks = controls = clf_suspicious = clf_unavailable = 0
    for r in rows:
        out = screen(r["message"], r.get("context"), classifier=classifier)
        clf_suspicious += SUSPICIOUS_RULE in out["rule_ids"]
        clf_unavailable += UNAVAILABLE_RULE in out["rule_ids"]
        lat.append(out["latency_ms"])
        if r["label"] == "attack":
            attacks += 1
            if out["verdict"] == "allow":
                missed.append(r["id"])
                continue
            blocked += out["verdict"] == "block"
            quarantined += out["verdict"] == "quarantine"
            for rid in out["rule_ids"]:
                per_rule[rid] = per_rule.get(rid, 0) + 1
            if r.get("expect_rule") and r["expect_rule"] not in out["rule_ids"]:
                wrong_rule.append(r["id"])
        else:
            controls += 1
            if out["verdict"] != "allow":
                fp_ids.append(r["id"])
    lat.sort()
    p95 = lat[max(0, math.ceil(0.95 * len(lat)) - 1)] if lat else 0.0
    stopped = blocked + quarantined
    return {
        "attacks": attacks, "controls": controls, "blocked": blocked, "quarantined": quarantined,
        "stopped": stopped, "block_rate": stopped / attacks if attacks else 0.0,
        "false_positives": len(fp_ids), "false_positive_rate": len(fp_ids) / controls if controls else 0.0,
        "false_positive_ids": fp_ids, "missed": missed, "wrong_rule": wrong_rule,
        "p95_ms": round(p95, 2), "per_rule": dict(sorted(per_rule.items())),
        "clf_suspicious": clf_suspicious, "clf_unavailable": clf_unavailable,
    }


def _row(name: str, st: dict) -> str:
    fp = f'{st["false_positives"]} of {st["controls"]}' if st["controls"] else "no controls"
    return (f"| {name} | {st['stopped']} of {st['attacks']} ({st['block_rate']:.1%}) | {st['blocked']} | "
            f"{st['quarantined']} | {fp} |")


def render_results(dev: dict, dev2: dict, probe: dict, fresh: dict, today: str) -> str:
    rules = "\n".join(f"| `{k}` | {v} |" for k, v in dev2["per_rule"].items())
    return f"""# Shield corpus results

Run date: {today}. Command: `python3 -m shield.corpus.run_corpus --write`. Classifier off, no network, rules only.
"Stopped" means the verdict was quarantine or block.

## The numbers (reported separately, never averaged)

| Set | Attacks stopped | block | quarantine | Clean controls wrongly stopped |
|---|---|---|---|---|
{_row("dev (`dev.jsonl`, in-sample)", dev)}
{_row("dev2 (`dev2.jsonl`, development set 2, in-sample)", dev2)}
{_row("held-out (`evasion_probe.jsonl`, frozen, see caveat)", probe)}
{_row("post-freeze check (`fresh12.jsonl`, run once, not tuned)", fresh)}

False positives across ALL controls (dev {dev["controls"]} + dev2 {dev2["controls"]}): {dev["false_positives"] + dev2["false_positives"]}.
p95 latency per message: dev {dev["p95_ms"]} ms, dev2 {dev2["p95_ms"]} ms.

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
- Misses on held-out: {", ".join(probe["missed"]) or "none"}. Misses on the post-freeze check: {", ".join(fresh["missed"]) or "none"}.
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
{rules}

Cases from outside our lane: a01 (injected listing page) and c09, c10 (honest pages) in dev.jsonl are Anoop's pages
from `data/liar_pages` (Lane C c4), copied unchanged.
"""


def _line(name: str, st: dict) -> str:
    fp = f", false positives {st['false_positives']}/{st['controls']}" if st["controls"] else ""
    return f"{name}: stopped {st['stopped']}/{st['attacks']} (block {st['blocked']}, quarantine {st['quarantined']}){fp}"


ENV_NAMES = ("ANTHROPIC_API_KEY", "SHIELD_CLASSIFIER", "SHIELD_MODEL")


def load_dotenv(path: str, env: dict) -> None:
    """Copy ENV_NAMES from a KEY=VALUE file into `env` without overriding a name that is already set.
    Nothing is printed, and no other name in the file is read into `env`."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        val = val.strip().strip("'\"")
        if key in ENV_NAMES and val and not env.get(key):
            env[key] = val


def make_classifier(env: dict):
    return ClaudeClassifier(env["ANTHROPIC_API_KEY"], model=env.get("SHIELD_MODEL") or None)


def classifier_main(env_file: str) -> int:
    """Live run with the optional classifier. Only when ANTHROPIC_API_KEY and SHIELD_CLASSIFIER=1 are set
    (environment or the repo .env). The key is never printed. Reads no network otherwise."""
    env = dict(os.environ)
    load_dotenv(env_file, env)
    if not (env.get("ANTHROPIC_API_KEY") and env.get("SHIELD_CLASSIFIER") == "1"):
        print("classifier not enabled: set ANTHROPIC_API_KEY and SHIELD_CLASSIFIER=1 (environment or a .env file in "
              "the repo root). No network call was made.")
        return 0
    clf = make_classifier(env)
    print(f"classifier LIVE, model {env.get('SHIELD_MODEL') or ClaudeClassifier('x')._model} (unverified until it answers)")
    unavailable = 0
    for name, path in (("dev", DEV), ("dev2", DEV2), ("held-out (evasion probe)", PROBE), ("post-freeze check", FRESH)):
        rules_only, with_clf = run(path), run(path, classifier=clf)
        unavailable += with_clf["clf_unavailable"]
        fp = f", false positives {rules_only['false_positives']} -> {with_clf['false_positives']} of {with_clf['controls']}" if with_clf["controls"] else ""
        print(f"{name}: stopped {rules_only['stopped']} -> {with_clf['stopped']} of {with_clf['attacks']}{fp}; "
              f"classifier suspicious {with_clf['clf_suspicious']}, classifier unavailable {with_clf['clf_unavailable']}")
    if unavailable:
        print(f"WARNING: {unavailable} classifier calls were unavailable (timeout, error or an unknown model id). "
              "Those are quarantines by fail-closed design, NOT classifier catches; do not quote them as recall.")
    return 0


def main(argv: list[str], env_file: str = ENV_FILE) -> int:
    if "--classifier" in argv:
        return classifier_main(env_file)
    dev, dev2, probe, fresh = run(DEV), run(DEV2), run(PROBE), run(FRESH)
    print(_line("dev", dev) + f", p95 {dev['p95_ms']} ms")
    print(_line("dev2", dev2))
    print(_line("held-out (evasion probe)", probe))
    print(_line("post-freeze check", fresh))
    if "--write" in argv:
        with open(RESULTS, "w", encoding="utf-8") as f:
            f.write(render_results(dev, dev2, probe, fresh, date.today().isoformat()))
        print(f"wrote {RESULTS}")
    bad = dev["missed"] or dev["wrong_rule"] or dev["false_positive_ids"] or dev2["false_positive_ids"]
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
