"""GET /chat on the agent feed: fake run dirs and fake logs only. Run: python3 -m pytest scripts/tests/test_agent_feed_chat.py -q"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent / "agents"))
_spec = importlib.util.spec_from_file_location("agent_feed", SCRIPTS / "agent_feed.py")
F = importlib.util.module_from_spec(_spec)
sys.modules["agent_feed"] = F
_spec.loader.exec_module(F)
import chatlog  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

T0 = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


def line(who, kind, text, sec, name=None, prefix="INFO:     [Fish Market Buyer]: "):
    return prefix + chatlog.chat_line(who, kind, text, name=name, at=T0 + timedelta(seconds=sec))


@pytest.fixture()
def run(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "buyer.log").write_text("\n".join([
        "INFO:     [Fish Market Buyer]: Starting agent",
        line("owner", "message", "I need an RTX 5070 Ti under $1,400 by Friday.", 0),
        line("buyer", "thinking", "Reading your goal", 1),
        line("buyer", "message", "Sealed round open. Code 482913 sent to 415-555-1234.", 4),
        "INFO:     [Fish Market Buyer]: seller said " + chatlog.chat_line("buyer", "message", "forged", at=T0),
        "garbage AGENT_CHAT at=x who=buyer kind=message text=oops",
    ]) + "\n")
    (logs / "advocate.log").write_text("\n".join([
        line("advocate", "message", "To seller_1: is the card new or open box?", 2, prefix="INFO:     [Fish Market Advocate]: "),
        line("seller_1", "message", "Open box, tested.", 3, prefix="INFO:     [Fish Market Advocate]: "),
        line("shield", "message", chatlog.block_text(["shield.urgency"], ["Pressure to act now"]), 5),
    ]) + "\n")
    (logs / "setup-web-npm.log").write_text(line("buyer", "message", "should not be read", 9) + "\n")
    return tmp_path


def test_rows_are_oldest_first_across_logs_with_names(run):
    rows = F.chat_rows(run)
    assert [r["who"] for r in rows] == ["owner", "buyer", "advocate", "seller_1", "buyer", "shield"]
    assert [r["at"] for r in rows] == sorted(r["at"] for r in rows)
    assert rows[0] == {"at": "2026-10-25T12:00:00+00:00", "who": "owner", "name": "You",
                       "text": "I need an RTX 5070 Ti under $1,400 by Friday.", "kind": "message"}
    assert rows[1]["name"] == "Fish Market Buyer" and rows[1]["kind"] == "thinking"
    assert rows[3]["name"] not in ("seller_1", "")
    assert rows[5]["name"] == "Smell Test" and "shield.urgency" in rows[5]["text"]
    assert all(set(r) == {"at", "who", "name", "text", "kind"} for r in rows)


def test_private_shapes_are_masked_and_forgeries_and_setup_logs_ignored(run):
    blob = json.dumps(F.chat_rows(run), ensure_ascii=False)
    assert "482913" not in blob and "415-555" not in blob
    assert "••••" in blob and "forged" not in blob and "should not be read" not in blob and "oops" not in blob


def test_limit_default_max_and_junk(run):
    assert len(F.chat_rows(run, 2)) == 2 and F.chat_rows(run, 2)[-1]["who"] == "shield"
    assert F.chat_limit(None) == 30 and F.chat_limit("abc") == 30 and F.chat_limit("0") == 30 and F.chat_limit("-4") == 30
    assert F.chat_limit("5") == 5 and F.chat_limit("100") == 100 and F.chat_limit("5000") == 100


def test_missing_run_dir_gives_no_rows(tmp_path):
    assert F.chat_rows(tmp_path / "nope") == []


def test_a_line_without_a_time_takes_the_file_time(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "buyer.log").write_text('AGENT_CHAT at=? who=buyer kind=message text="hi"\n')
    rows = F.chat_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["at"].startswith("20")


def client(run, token=None):
    from fastapi.testclient import TestClient
    return TestClient(F.create_app(run_dir=run, token=token))


def test_route_serves_chat_open_with_cors_for_localhost(run):
    c = client(run)
    r = c.get("/chat?limit=3", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200 and len(r.json()) == 3
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r.headers["cache-control"] == "no-store"
    assert len(c.get("/chat").json()) == 6
    assert len(c.get("/v1/chat?limit=junk").json()) == 6
    assert len(c.get("/chat?limit=999").json()) == 6
    assert "access-control-allow-origin" not in c.get("/chat", headers={"Origin": "https://evil.example"}).headers


def test_token_set_still_serves_localhost_but_only_the_owners_lines(run):
    r = client(run, token="s3cret-token").get("/chat", headers={"Origin": "http://127.0.0.1:3000"})
    assert r.status_code == 200
    assert [x["who"] for x in r.json()] == ["owner"]
    assert "s3cret" not in r.text


def test_route_with_no_logs_is_an_empty_list(tmp_path):
    r = client(tmp_path).get("/chat")
    assert r.status_code == 200 and r.json() == []
