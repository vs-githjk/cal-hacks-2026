"""#449 PL-17: /v1/memory and /v1/build served every buyer's goals, caps, spend and payees, filtered only in the browser.
AGENT_FEED_TOKEN is optional: unset, today's behaviour on loopback; set, both routes need `Authorization: Bearer <token>` and a
`buyer` query parameter and return only that buyer's rows. The token stays server-side; browsers cannot send it (no CORS header)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(1, str(SCRIPTS.parent))
spec = importlib.util.spec_from_file_location("agent_feed_449", SCRIPTS / "agent_feed.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)

TOKEN = "feed-token-for-tests-0123456789"
GOOD = {"Authorization": f"Bearer {TOKEN}"}


def row(id_, kind, buyer, **detail):
    return {"id": id_, "kind": kind, "at": f"2026-10-24T0{len(id_) % 9}:00:00Z", "origin": "SIM", "source": "market", "source_ref": "x",
            "buyer_id": buyer, "seller_id": "", "summary": id_, "detail": detail}


ROWS = [row("goal-a", "goal", "buyer-a"), row("buy-a", "purchase", "buyer-a"), row("veto-a", "veto", "buyer-a"),
        row("goal-b", "goal", "buyer-b"), row("buy-b", "purchase", "buyer-b"), row("veto-b", "veto", "buyer-b"),
        row("veto-market", "veto", ""), row("lesson-1", "lesson", ""), row("lesson-a", "lesson", "buyer-a"),
        row("goal-orphan", "goal", ""), row("buy-orphan", "purchase", "")]


@pytest.fixture
def memory_dir(tmp_path):
    (tmp_path / "market-memory-1.json").write_text(json.dumps({"entries": ROWS}))
    return tmp_path


def client(tmp_path, memory_dir=None, token=TOKEN, build=None):
    if build is not None:
        (tmp_path / "build-view.json").write_text(json.dumps(build))
    return TestClient(F.create_app(tmp_path / "run", memory_dir=memory_dir or tmp_path / "none", build_dir=tmp_path, token=token))


def view(buyer="buyer-a"):
    return {"goalId": f"goal-{buyer}", "buyerId": buyer, "budget": 2100.0, "spent": 1299.0, "origin": "SIM",
            "parts": [], "checks": [], "events": [], "approval": None}


def ids(r):
    return sorted(e["id"] for e in r.json()["entries"])


# ---- unset: today's behaviour ---------------------------------------------------------------------------------------
def test_with_no_token_both_routes_are_open_and_unscoped_as_before(tmp_path, memory_dir, monkeypatch):
    monkeypatch.delenv("AGENT_FEED_TOKEN", raising=False)
    c = client(tmp_path, memory_dir, token=None, build=view("buyer-b"))
    assert ids(c.get("/v1/memory")) == sorted(r["id"] for r in ROWS)
    assert ids(c.get("/v1/memory", params={"buyer": "buyer-a"})) == sorted(r["id"] for r in ROWS)   # ignored: it is not a gate
    assert c.get("/v1/build").status_code == 200 and c.get("/v1/build", params={"buyer": "buyer-a"}).status_code == 200


def test_a_blank_token_is_no_token(tmp_path, memory_dir):
    assert client(tmp_path, memory_dir, token="   ").get("/v1/memory").status_code == 200


def test_the_env_variable_sets_the_token(tmp_path, memory_dir, monkeypatch):
    monkeypatch.setenv("AGENT_FEED_TOKEN", TOKEN)
    c = TestClient(F.create_app(tmp_path / "run", memory_dir=memory_dir, build_dir=tmp_path))
    assert c.get("/v1/memory", params={"buyer": "buyer-a"}).status_code == 401
    assert c.get("/v1/memory", params={"buyer": "buyer-a"}, headers=GOOD).status_code == 200


# ---- set: the bearer, the buyer parameter, the scoping ---------------------------------------------------------------
@pytest.mark.parametrize("path", ["/v1/memory", "/v1/build"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": TOKEN}, {"Authorization": f"Basic {TOKEN}"},
                                     {"X-API-Key": TOKEN}, {"Authorization": f"Bearer {TOKEN}x"}, {"Authorization": b"Bearer \xc3\xa9"}])
def test_a_missing_or_wrong_bearer_is_401_and_nothing_is_read(tmp_path, memory_dir, path, headers):
    r = client(tmp_path, memory_dir, build=view()).get(path, params={"buyer": "buyer-a"}, headers=headers)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert "goal" not in r.text and "buyer-a" not in r.text and TOKEN not in r.text


@pytest.mark.parametrize("path", ["/v1/memory", "/v1/build"])
@pytest.mark.parametrize("params", [{}, {"buyer": ""}, {"buyer": "   "}, {"buyer": "x" * 300}])
def test_the_right_bearer_without_a_usable_buyer_is_400(tmp_path, memory_dir, path, params):
    r = client(tmp_path, memory_dir, build=view()).get(path, params=params, headers=GOOD)
    assert r.status_code == 400 and "buyer" in r.json()["detail"]


def test_the_bearer_is_checked_before_the_buyer(tmp_path, memory_dir):
    assert client(tmp_path, memory_dir).get("/v1/memory").status_code == 401


def test_memory_returns_only_this_buyers_rows_plus_the_buyerless_veto_and_lessons_the_client_shows(tmp_path, memory_dir):
    c = client(tmp_path, memory_dir)
    a = c.get("/v1/memory", params={"buyer": "buyer-a"}, headers=GOOD)
    assert ids(a) == ["buy-a", "goal-a", "lesson-1", "lesson-a", "veto-a", "veto-market"]
    b = c.get("/v1/memory", params={"buyer": "buyer-b"}, headers=GOOD)
    assert ids(b) == ["buy-b", "goal-b", "lesson-1", "veto-b", "veto-market"]
    assert "buyer-a" not in json.dumps([e for e in b.json()["entries"] if e["kind"] != "lesson"])
    assert ids(c.get("/v1/memory", params={"buyer": "stranger"}, headers=GOOD)) == ["lesson-1", "veto-market"]
    # a goal or purchase with no buyer id belongs to nobody, whoever asks
    for who in ("buyer-a", "buyer-b", "stranger"):
        assert not {"goal-orphan", "buy-orphan"} & set(ids(c.get("/v1/memory", params={"buyer": who}, headers=GOOD)))


def test_the_limit_and_kind_apply_after_the_buyer_scoping(tmp_path, memory_dir):
    c = client(tmp_path, memory_dir)
    got = c.get("/v1/memory", params={"buyer": "buyer-b", "kind": "purchase", "limit": 1}, headers=GOOD).json()["entries"]
    assert [e["id"] for e in got] == ["buy-b"]            # not cut away by another buyer's newer rows
    assert c.get("/v1/memory", params={"buyer": "buyer-b", "limit": 0}, headers=GOOD).json()["entries"] == []


def test_the_scoped_response_keeps_the_envelope(tmp_path, memory_dir):
    body = client(tmp_path, memory_dir).get("/v1/memory", params={"buyer": "buyer-a"}, headers=GOOD).json()
    assert set(body) == {"entries", "sources", "note"} and body["sources"][0]["kind"] == "market"


def test_build_is_served_only_to_the_buyer_it_belongs_to(tmp_path):
    c = client(tmp_path, build=view("buyer-b"))
    mine = c.get("/v1/build", params={"buyer": "buyer-b"}, headers=GOOD)
    assert mine.status_code == 200 and mine.json()["buyerId"] == "buyer-b"
    other = c.get("/v1/build", params={"buyer": "buyer-a"}, headers=GOOD)
    assert other.status_code == 404 and "buyer-b" not in other.text and "goal-buyer-b" not in other.text


def test_a_build_with_no_buyer_id_is_served_to_nobody_when_a_token_is_set(tmp_path):
    no_owner = view()
    del no_owner["buyerId"]
    assert client(tmp_path, build=no_owner).get("/v1/build", params={"buyer": "buyer-a"}, headers=GOOD).status_code == 404


def test_build_with_no_run_is_404_and_a_bad_file_is_503_for_the_right_caller(tmp_path):
    assert client(tmp_path).get("/v1/build", params={"buyer": "buyer-a"}, headers=GOOD).status_code == 404
    (tmp_path / "build-view.json").write_text("{not json")
    assert client(tmp_path).get("/v1/build", params={"buyer": "buyer-a"}, headers=GOOD).status_code == 503


def test_the_other_routes_stay_open(tmp_path):
    c = client(tmp_path)
    assert c.get("/v1/health").json() == {"ok": True}
    assert c.get("/v1/agents").status_code == 200


def test_the_token_is_compared_in_constant_time_and_a_browser_cannot_send_it():
    import inspect
    assert "compare_digest" in inspect.getsource(F)
    assert 'allow_headers=[]' in inspect.getsource(F)      # no Authorization in a cross-origin preflight: browser pages cannot hold the token


def test_the_server_filter_is_the_same_rule_as_the_clients(tmp_path):
    """web/src/lib/memory.ts memoryForBuyer: buyer_id === buyerId, or a lesson or veto with no buyer id. Keep the two equal."""
    ts = (SCRIPTS.parent / "web" / "src" / "lib" / "memory.ts").read_text()
    assert '(e.kind === "lesson" || e.kind === "veto") && e.buyer_id === ""' in ts
    assert F.BUYERLESS_KINDS == ("lesson", "veto")
