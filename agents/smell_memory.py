"""Shared quarantine memory for Smell Test. A trick Shield caught once goes on a short-lived list in a local file; every
agent's common.screen reads it, so the same trick is flagged for every agent, even where the rules alone would say allow.

Why a file and not a market table: a table needs a SpacetimeDB schema change and a republish (Lane B), and the agents that
read it all run on one machine. The file is private (mode 600), lives in ~/.bazaar-shield, and is capped.

Rules of the list (deterministic, no model):
  - only the attack text itself is remembered (override, hidden instruction, exfil, impersonation, approval pressure); not a payee,
    a price, an encoded blob or a classifier flag, which only mean something for one message;
  - a pattern is 12 to 80 characters, stored lower case with spaces collapsed, with a count and two times;
  - entries expire after SMELL_QUARANTINE_TTL_S (default 6 hours; seeing it again refreshes it);
  - at most SMELL_QUARANTINE_MAX entries (default 200), the oldest dropped first;
  - a hit only ever ADDS a quarantine to an allow; it never lowers a verdict, and the buyer's own side (buyer, advocate,
    marketplace) is exempt, because their text may legitimately say what a seller's must not;
  - any disk error leaves the verdict exactly as Shield gave it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # not on Windows; the file is then unlocked, which is fine for a cache
    fcntl = None

try:
    from shield.rules.base import BUYER_SIDE
except ImportError:
    BUYER_SIDE = frozenset({"buyer", "advocate", "marketplace"})

SEEN_RULE = "shield.quarantine.seen"
MIN_LEN, MAX_LEN = 12, 80
DEFAULT_TTL_S, DEFAULT_MAX = 6 * 3600, 200
REMEMBER = ("shield.override.", "shield.hidden.instruction", "shield.exfil.", "shield.intent.override",
            "shield.intent.approval_bypass", "shield.intent.agent_directed", "shield.intent.authority_claim",
            "shield.impersonation", "shield.money.approval")


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def _exempt(context) -> bool:
    return str((context or {}).get("sender_role") or "").strip().lower() in BUYER_SIDE


def _number(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, ""))
        return v if v > 0 else default
    except ValueError:
        return default


class Memory:
    def __init__(self, path, ttl_s: float | None = None, max_entries: int | None = None, clock=time.time):
        self.path = Path(path)
        self.ttl_s = ttl_s if ttl_s is not None else _number("SMELL_QUARANTINE_TTL_S", DEFAULT_TTL_S)
        self.max_entries = int(max_entries if max_entries is not None else _number("SMELL_QUARANTINE_MAX", DEFAULT_MAX))
        self._clock = clock

    # --- storage ---------------------------------------------------------------------------------------------------
    def _load(self) -> list[dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            items = raw["entries"]
            if not isinstance(items, list):
                return []
        except (OSError, ValueError, KeyError, TypeError):
            return []
        now = self._clock()
        keep = []
        for e in items:
            if (isinstance(e, dict) and isinstance(e.get("pattern"), str) and isinstance(e.get("rule_id"), str)
                    and all(isinstance(e.get(k), (int, float)) and not isinstance(e.get(k), bool) for k in ("first_seen", "last_seen", "count"))
                    and MIN_LEN <= len(e["pattern"]) <= MAX_LEN and now - e["last_seen"] <= self.ttl_s):
                keep.append({k: e[k] for k in ("pattern", "rule_id", "first_seen", "last_seen", "count")})
        return keep

    def _save(self, entries: list[dict]) -> None:
        entries = sorted(entries, key=lambda e: e["last_seen"])[-self.max_entries:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f)
        os.replace(tmp, self.path)

    def _locked(self):
        class Lock:
            def __enter__(inner):
                inner.f = None
                if fcntl is not None:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    inner.f = open(self.path.with_name(self.path.name + ".lock"), "a")
                    fcntl.flock(inner.f, fcntl.LOCK_EX)

            def __exit__(inner, *a):
                if inner.f is not None:
                    inner.f.close()
        return Lock()

    # --- the list --------------------------------------------------------------------------------------------------
    def remember(self, text: str, result: dict, context: dict | None = None) -> int:
        """Put the attack spans of a non-allow verdict on the list. Returns how many spans were stored or refreshed."""
        try:
            if _exempt(context) or result.get("verdict") not in ("block", "quarantine"):
                return 0
            fresh = {}
            for span in result.get("evidence_spans") or []:
                pattern = _norm(span.get("text")) if isinstance(span, dict) else ""
                rule = span.get("rule_id") if isinstance(span, dict) else ""
                if isinstance(rule, str) and rule.startswith(REMEMBER) and MIN_LEN <= len(pattern) <= MAX_LEN:
                    fresh[pattern] = rule
            if not fresh:
                return 0
            with self._locked():
                entries, now = self._load(), self._clock()
                by_pattern = {e["pattern"]: e for e in entries}
                for pattern, rule in fresh.items():
                    if pattern in by_pattern:
                        by_pattern[pattern].update(last_seen=now, count=by_pattern[pattern]["count"] + 1)
                    else:
                        by_pattern[pattern] = {"pattern": pattern, "rule_id": rule, "first_seen": now, "last_seen": now, "count": 1}
                self._save(list(by_pattern.values()))
            return len(fresh)
        except Exception:
            return 0

    def match(self, text: str) -> list[dict]:
        """Remembered patterns found in this text: [{rule_id, start, end, text}] with offsets in the raw text."""
        hits = []
        for e in self._load():
            m = re.search(r"\s+".join(re.escape(w) for w in e["pattern"].split()), text, re.I)
            if m:
                hits.append({"rule_id": e["rule_id"], "start": m.start(), "end": m.end(), "text": text[m.start():m.end()][:MAX_LEN]})
        return hits

    def apply(self, text: str, result: dict, context: dict | None = None) -> dict:
        """Called with every Shield result. A non-allow is remembered; an allow that contains a remembered pattern becomes
        a quarantine. Everything else, and any error, returns the result as it came."""
        try:
            if _exempt(context) or not isinstance(result, dict):
                return result
            if result.get("verdict") != "allow":
                self.remember(text, result, context)
                return result
            hits = self.match(text)
            if hits:
                result.update(verdict="quarantine", reasons=[SEEN_RULE], rule_ids=[SEEN_RULE], attack_type="other", severity="medium",
                              evidence_spans=[{**h, "rule_id": SEEN_RULE, "seen_as": h["rule_id"]} for h in hits[:8]])
        except Exception:
            pass
        return result

    def summary(self) -> dict:
        """Counts only, never the patterns: the patterns are other people's words."""
        by_rule: dict[str, int] = {}
        entries = self._load()
        for e in entries:
            by_rule[e["rule_id"]] = by_rule.get(e["rule_id"], 0) + 1
        return {"count": len(entries), "by_rule": by_rule, "ttl_s": self.ttl_s, "max_entries": self.max_entries}


def default() -> Memory | None:
    """The shared list: SMELL_QUARANTINE_FILE, else ~/.bazaar-shield/quarantine.json. "off" turns it off, and a pytest run
    has none unless a test names a file, so the suite never touches a real list."""
    raw = os.environ.get("SMELL_QUARANTINE_FILE", "").strip()
    if raw.lower() in ("off", "0", "false"):
        return None
    if raw:
        return Memory(raw)
    if "pytest" in sys.modules:
        return None
    return Memory(Path.home() / ".bazaar-shield" / "quarantine.json")
