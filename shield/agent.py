"""verify_agent(request, registry): is this agent who it says it is? Returns the Shield verdict shape.

Order: malformed input (block), denylist (block), then every finding is collected: impersonation of the
buyer, advocate or Tech Bazaar names (block), role mismatch (block), seller-of-record mismatch (quarantine),
unregistered address (quarantine, fail closed), and the manifest's own text screened like any seller message.
Allow only when the address is registered, the role and seller of record match, and nothing else fired.
Signature (TAP) checks on the request itself belong to the caller (Lane A a9); this is the registry layer.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Mapping, Optional

from shield import VERSION
from shield.core import screen
from shield.registry import ROLES, Registry
from shield.rules.base import SEVERITY_ORDER
from shield.text import make_doc

ADDRESS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.\-]{0,127}")
MAX_FIELD = 200
MAX_MANIFEST_CHARS = 20000
NAME_KEYS = ("name", "title", "handle", "display_name")
_PROTECTED = re.compile(
    r"(?<![a-z0-9])(?:tech\s*bazaar|bazaar\s*shield|shield|advocate|buyer|marketplace\s*(?:admin|operator|support))(?![a-z0-9])")
_PRIVILEGED_ROLES = ("buyer", "advocate", "marketplace")

UNREGISTERED = "shield.agent.unregistered"
DENYLISTED = "shield.agent.denylisted"
IMPERSONATION = "shield.agent.impersonation"
ROLE_MISMATCH = "shield.agent.role_mismatch"
SELLER_MISMATCH = "shield.agent.seller_mismatch"
MALFORMED = "shield.agent.malformed_request"
ERROR = "shield.error"


class _Malformed(ValueError):
    pass


def _verdict(verdict: str, rule_ids: list[str], severity: str, started: float, request_id: str) -> dict:
    return {
        "verdict": verdict, "rule_ids": sorted(set(rule_ids)), "severity": severity, "evidence_spans": [],
        "latency_ms": round((time.perf_counter() - started) * 1000, 3), "request_id": request_id, "version": VERSION,
    }


def _plain(name: str) -> str:
    return " ".join(re.sub(r"[_\-]+", " ", name.lower()).split())


def _protected_hit(text: str) -> bool:
    """Does a name contain a protected word, after undoing homoglyphs, leetspeak and letter spacing?"""
    doc = make_doc(text)
    return any(_PROTECTED.search(_plain(v)) for v in [doc.norm, *(d.norm for d in doc.views())])


def _clean_input(request: Any) -> tuple[str, str, Optional[str], dict]:
    if not isinstance(request, Mapping):
        raise _Malformed
    addr, role = request.get("agent_address"), request.get("claimed_role")
    if not isinstance(addr, str) or not ADDRESS_RE.fullmatch(addr):
        raise _Malformed
    if not isinstance(role, str) or role.strip().lower() not in ROLES:
        raise _Malformed
    sor = request.get("seller_of_record")
    if sor is not None and (not isinstance(sor, str) or len(sor) > MAX_FIELD):
        raise _Malformed
    manifest = request.get("manifest")
    if manifest is None:
        manifest = {}
    if not isinstance(manifest, Mapping):
        raise _Malformed
    for k, v in manifest.items():
        ok_list = isinstance(v, list) and all(isinstance(x, str) for x in v)
        if not isinstance(k, str) or not (v is None or isinstance(v, (str, int, float, bool)) or ok_list):
            raise _Malformed
    return addr, role.strip().lower(), sor, dict(manifest)


def _manifest_text(manifest: Mapping) -> str:
    parts = []
    for k, v in manifest.items():
        vals = v if isinstance(v, list) else [v]
        parts += [f"{k}: {x}" for x in vals if isinstance(x, str)]
    return "\n".join(parts)


def verify_agent(request: Any, registry: Registry) -> dict:
    started, request_id = time.perf_counter(), uuid.uuid4().hex
    try:
        try:
            address, role, seller, manifest = _clean_input(request)
        except _Malformed:
            return _verdict("block", [MALFORMED], "high", started, request_id)
        if registry.is_denied(address):
            return _verdict("block", [DENYLISTED], "critical", started, request_id)

        entry = registry.get(address)
        rules: list[str] = []
        names = [str(manifest[k]) for k in NAME_KEYS if isinstance(manifest.get(k), str)]
        if seller:
            names.append(seller)
        if entry is None:
            rules.append(UNREGISTERED)
            if role in _PRIVILEGED_ROLES or any(_protected_hit(n) for n in names):
                rules.append(IMPERSONATION)
        else:
            own = {_plain(entry["name"]), _plain(entry.get("seller_of_record") or "")}
            if any(_plain(n) not in own and _protected_hit(n) for n in names):
                rules.append(IMPERSONATION)
            if role != entry["role"]:
                rules.append(ROLE_MISMATCH)
            elif role == "seller" and seller != entry.get("seller_of_record"):
                rules.append(SELLER_MISMATCH)

        text = _manifest_text(manifest)
        severity = "none"
        flagged = False
        if text:
            out = screen(text, {"sender_role": entry["role"] if entry else "seller"}, classifier=None)
            if out["verdict"] != "allow":
                flagged = True
                rules += out["rule_ids"]
                severity = out["severity"]
        blocking = {DENYLISTED, IMPERSONATION, ROLE_MISMATCH}
        if not rules:
            return _verdict("allow", [], "none", started, request_id)
        verdict = "block" if (set(rules) & blocking or (flagged and out["verdict"] == "block")) else "quarantine"
        sev = max([severity, "high" if set(rules) & blocking else ("medium" if UNREGISTERED in rules else "high")],
                  key=SEVERITY_ORDER.index)
        return _verdict(verdict, rules, sev, started, request_id)
    except Exception:  # fail closed
        return _verdict("block", [ERROR], "critical", started, request_id)
