"""Minimal Bazaar Shield client (Lane C, c9). Any non-200 response is treated as block (fail closed)."""
import json
import urllib.request


class ShieldClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 5.0):
        self.base, self.key, self.timeout = base_url.rstrip("/"), api_key, timeout

    def screen(self, message: str, context: dict | None = None) -> dict:
        req = urllib.request.Request(self.base + "/v1/shield/screen", method="POST",
                                     data=json.dumps({"message": message, "context": context or {}}).encode(),
                                     headers={"Content-Type": "application/json", "X-API-Key": self.key})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # timeout, 401, 429, 5xx: fail closed
            return {"verdict": "block", "rule_ids": ["client.fail_closed"], "error": type(e).__name__}
