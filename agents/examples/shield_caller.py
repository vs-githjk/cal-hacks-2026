"""Small, fail-closed client for Bazaar Shield's message-screen endpoint."""
from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from typing import Mapping
from urllib.parse import urlsplit

ENDPOINT_PATH = "/v1/shield/screen"
MAX_RESPONSE_BYTES = 64 * 1024
BLOCK = {"verdict": "block", "rule_ids": ["shield.caller.unavailable"]}
_RULE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _endpoint(url: str) -> str:
    if not isinstance(url, str) or not url or any(c.isspace() for c in url):
        raise ValueError("expected the Shield screen endpoint URL")
    parts = urlsplit(url)
    _ = parts.port  # Reject malformed ports before the opener sees the URL.
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.netloc.endswith(":") or parts.path != ENDPOINT_PATH or parts.query or parts.fragment):
        raise ValueError("expected the Shield screen endpoint URL")
    return url


def screen_message(*, shield_url: str, message_id: str, sender_agent: str, text: str,
                   context: Mapping[str, object], timeout: float = 2.0,
                   api_key: str | None = None) -> dict:
    """POST to Shield core, or to the keyed product API when an explicit API key is supplied."""
    try:
        if (not all(isinstance(v, str) and v for v in (message_id, sender_agent))
                or not isinstance(text, str) or not isinstance(context, Mapping)
                or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            return dict(BLOCK, rule_ids=list(BLOCK["rule_ids"]))
        if api_key is not None and (not isinstance(api_key, str) or not api_key or len(api_key) > 4096
                                    or any(ord(char) < 0x21 or ord(char) > 0x7E for char in api_key)):
            return dict(BLOCK, rule_ids=list(BLOCK["rule_ids"]))
        endpoint = _endpoint(shield_url)
        body = json.dumps({"message_id": message_id, "sender_agent": sender_agent,
                           "text": text, "context": dict(context)},
                          ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key is not None:
            headers["X-API-Key"] = api_key
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return dict(BLOCK, rule_ids=list(BLOCK["rule_ids"]))
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return dict(BLOCK, rule_ids=list(BLOCK["rule_ids"]))
        def unique_object(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError("duplicate response field")
                out[key] = value
            return out

        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        if (not isinstance(result, dict) or result.get("verdict") not in ("allow", "quarantine", "block")
                or not isinstance(result.get("rule_ids"), list)
                or len(result["rule_ids"]) > 128
                or any(not isinstance(rule, str) or not _RULE_ID.fullmatch(rule) for rule in result["rule_ids"])):
            return dict(BLOCK, rule_ids=list(BLOCK["rule_ids"]))
        return {"verdict": result["verdict"], "rule_ids": list(result["rule_ids"])}
    except (OSError, TimeoutError, ValueError, TypeError, OverflowError, RecursionError, UnicodeError,
            json.JSONDecodeError,
            urllib.error.URLError):
        return dict(BLOCK, rule_ids=list(BLOCK["rule_ids"]))
