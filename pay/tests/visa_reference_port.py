"""A faithful Python port of the checks in Visa's Trusted Agent Protocol sample CDN proxy verifier.

Source read (not copied): github.com/visa/trusted-agent-protocol, commit 16d59bdf3f8a542bc538d0962edbb80ea30a02af
  cdn-proxy/server.js (blob 703d9ced)
    parseRFC9421SignatureInput  lines 213-260   Signature-Input parsing
    buildRFC9421SignatureString lines 263-307   signature base construction
    verifySignature             lines 397-560   timing window, nonce replay cache, algorithm dispatch
    validateKeyId               lines 65-70     keyId charset and length
    verifyEd25519Signature      lines 347-394   raw Ed25519 over the UTF-8 base string
  tap-agent/agent_app.py lines 1321-1366 (create_ed25519_signature) is the reference signer; its header
    format is what `reference_agent_headers` reproduces so the port itself can be sanity checked.
  merchant-backend/app/security/signature_verification.py line 59 reads Signature-Agent as a quoted URL.

Why a port and not a vendored copy: the repo's LICENSE.md points at the Visa Developer Center terms, so
nothing from it is copied. This file re-implements the same checks from reading them, in Python, with the
JavaScript regular expressions kept as they are (JavaScript String.match is unanchored, so re.search).
Deliberately kept quirks of the reference: the parser is case sensitive (`keyId`, not `keyid`), the base
string only knows @authority, @path, content-type and host (any other covered component is silently
dropped), and the nonce is cached before the signature is checked.
"""
from __future__ import annotations

import base64
import re
import time
from typing import Mapping, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def parse_signature_input(signature_input: str) -> Optional[dict]:
    """server.js:216 regex sig2=\\(([^)]+)\\);\\s*(.+) then (\\w+)=("[^"]*"|\\d+) attributes."""
    m = re.search(r'sig2=\(([^)]+)\);\s*(.+)', signature_input)
    if not m:
        return None
    components = [re.sub(r"['\"]", "", p) for p in re.split(r"\s+", m.group(1))]
    attributes: dict = {}
    for key, value in re.findall(r'(\w+)=("[^"]*"|\d+)', m.group(2)):
        attributes[key] = value[1:-1] if value.startswith('"') else int(value)
    return {"params": components, "nonce": attributes.get("nonce"), "created": attributes.get("created"),
            "expires": attributes.get("expires"), "keyId": attributes.get("keyId"),
            "algorithm": attributes.get("alg"), "tag": attributes.get("tag")}


def build_signature_string(components: list, request_data: Mapping[str, str], signature_input_header: str) -> str:
    """server.js:263-298."""
    lines = []
    for c in components:
        if c == "@authority":
            lines.append(f'"@authority": {request_data["authority"]}')
        elif c == "@path":
            lines.append(f'"@path": {request_data["path"]}')
        elif c == "content-type":
            lines.append(f'"content-type": {request_data.get("contentType") or "application/json"}')
        elif c == "host":
            lines.append(f'"host": {request_data.get("host") or request_data["authority"]}')
        elif request_data.get(c):
            lines.append(f'"{c}": {request_data[c]}')
    params = signature_input_header[5:] if signature_input_header.startswith("sig2=") else signature_input_header
    lines.append(f'"@signature-params": {params}')
    return "\n".join(lines)


class ReferenceVerifier:
    """One instance is one CDN proxy: it owns the keyId registry and the in-memory nonce cache."""

    def __init__(self, registry: Mapping[str, Ed25519PublicKey]):
        self.registry = dict(registry)
        self.nonce_cache: dict[str, float] = {}

    def verify(self, *, signature_input: Optional[str], signature: Optional[str], authority: str, path: str,
               now: Optional[int] = None) -> tuple[bool, str]:
        if not signature_input or not signature:
            return False, "missing_headers"
        data = parse_signature_input(signature_input)
        if not data:
            return False, "bad_signature_input"
        key_id = data["keyId"]
        if (not isinstance(key_id, str) or len(key_id) > 100 or not re.fullmatch(r"[a-zA-Z0-9._-]+", key_id)):
            return False, "bad_key_id"
        public_key = self.registry.get(key_id)
        if public_key is None:
            return False, "key_not_found"
        now = int(time.time()) if now is None else now
        if data["created"] and data["created"] > now + 60:
            return False, "created_in_future"
        if data["expires"] and data["expires"] < now:
            return False, "expired"
        nonce = data["nonce"]
        if not nonce:
            return False, "missing_nonce"
        if nonce in self.nonce_cache:
            return False, "replay"
        self.nonce_cache[nonce] = float(now)
        base = build_signature_string(data["params"], {"authority": authority, "path": path, "host": authority},
                                      signature_input)
        sig = re.search(r"sig2=:([^:]+):", signature)
        if not sig:
            return False, "bad_signature_format"
        if (data["algorithm"] or "").lower() != "ed25519":
            return False, "unsupported_algorithm"
        try:
            public_key.verify(base64.b64decode(sig.group(1)), base.encode("utf-8"))
        except (InvalidSignature, ValueError):
            return False, "bad_signature"
        return True, "ok"


def reference_agent_headers(private_key, *, authority: str, path: str, key_id: str, nonce: str, created: int,
                            expires: int, tag: str) -> dict:
    """What tap-agent/agent_app.py:1321 (create_ed25519_signature) emits."""
    params = (f'("@authority" "@path"); created={created}; expires={expires}; keyId="{key_id}"; '
              f'alg="ed25519"; nonce="{nonce}"; tag="{tag}"')
    base = f'"@authority": {authority}\n"@path": {path}\n"@signature-params": {params}'
    sig = base64.b64encode(private_key.sign(base.encode("utf-8"))).decode()
    return {"signature-input": f"sig2={params}", "signature": f"sig2=:{sig}:"}
