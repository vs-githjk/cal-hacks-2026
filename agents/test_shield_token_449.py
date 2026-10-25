"""#449 RT-26: the agents' Shield client sends SHIELD_API_TOKEN as a bearer token when it is set, and nothing when not."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"verdict": "allow", "rule_ids": []}).encode()


def capture(monkeypatch):
    seen = []
    monkeypatch.setenv("SHIELD_URL", "http://127.0.0.1:8787")
    monkeypatch.setattr(common, "_open_shield", lambda req, timeout: seen.append(req) or Response())
    return seen


def test_the_token_goes_as_a_bearer_header_when_set(monkeypatch):
    seen = capture(monkeypatch)
    monkeypatch.setenv("SHIELD_API_TOKEN", "tok-1234567890")
    assert common.screen("m1", "agent1q" + "a" * 58, "RTX 5070 Ti")["verdict"] == "allow"
    assert seen[0].get_header("Authorization") == "Bearer tok-1234567890"
    assert seen[0].get_header("Content-type") == "application/json"


def test_no_header_when_unset_or_blank(monkeypatch):
    seen = capture(monkeypatch)
    for value in (None, "", "  "):
        monkeypatch.delenv("SHIELD_API_TOKEN", raising=False)
        if value is not None:
            monkeypatch.setenv("SHIELD_API_TOKEN", value)
        common.screen("m1", "agent1q" + "a" * 58, "RTX 5070 Ti")
    assert len(seen) == 3 and all(req.get_header("Authorization") is None for req in seen)


def test_a_shield_that_refuses_the_token_blocks(monkeypatch):
    import urllib.error
    monkeypatch.setenv("SHIELD_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("SHIELD_API_TOKEN", "wrong")

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(common, "_open_shield", refuse)
    out = common.screen("m1", "agent1q" + "a" * 58, "RTX 5070 Ti")
    assert out["verdict"] == "block" and out["reasons"] == ["shield.unavailable"]
