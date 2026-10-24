"""Agent feed tests: fake run dirs and fake logs only, no network, no real agents. Run: python3 -m pytest scripts/tests/test_agent_feed.py -q"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("agent_feed", SCRIPTS / "agent_feed.py")
F = importlib.util.module_from_spec(_spec)
sys.modules["agent_feed"] = F
_spec.loader.exec_module(F)
import launch as L  # noqa: E402  (agent_feed imports the launcher; same module object)

ADDR_B = "agent1q" + "b" * 58
ADDR_A = "agent1q" + "a" * 58
ADDR_1 = "agent1q" + "1" * 58
ADDR_2 = "agent1q" + "2" * 58

BUYER_LOG = f"""buyer address: {ADDR_B}
INFO:     [tech_bazaar_buyer]: Starting agent with address: {ADDR_B}
INFO:     [tech_bazaar_buyer]: Agent inspector available at https://agentverse.ai/inspect/?uri=x&address={ADDR_B}
INFO:     [tech_bazaar_buyer]: Starting server on http://0.0.0.0:8001 (Press CTRL+C to quit)
INFO:     [tech_bazaar_buyer]: Manifest published successfully: AgentChatProtocol
INFO:     [uagents.registration]: Registration on Almanac API successful
WARNING:  [uagents.registration]: I do not have enough funds to register on Almanac contract
INFO:     [tech_bazaar_buyer]: to owner: Round open: 5 sellers asked
INFO:     [tech_bazaar_buyer]: late or stray bid ignored
"""

ADVOCATE_LOG = f"""INFO:     [quality_advocate]: Starting agent with address: {ADDR_A}
INFO:     [quality_advocate]: Agent registration status updated to active
WARNING:  [quality_advocate]: shield block from agent1qxyz: ['spoofed']
"""

SELLERS_LOG = f"""seller_1 address: {ADDR_1}
seller_2 address: {ADDR_2}
WARNING:  [bureau]: Overwriting the agent's endpoints with the Bureau's endpoints
INFO:     [Byte Bros Outlet]: Starting agent with address: {ADDR_1}
INFO:     [Silicon Sally's Surplus]: Starting agent with address: {ADDR_2}
INFO:     [Byte Bros Outlet]: order deal-7 placed; requesting $1249.99
INFO:     [Silicon Sally's Surplus]: payment committed: 1249.99 USD, ref r1
INFO:     [Byte Bros Outlet]: payment committed: 1249.99 USD, ref r2
"""


def alive_rec(log: Path | None, mailbox: bool | None = None, port=None) -> dict:
    rec = {"state": "running", "pid": os.getpid(), "lstart": L.proc_start_marker(os.getpid()), "port": port, "group": "agents",
           "log": str(log) if log else None}
    if mailbox is not None:
        rec["mailbox"] = mailbox
    return rec


def write_run(tmp_path: Path, services: dict, logs: dict[str, str]) -> Path:
    run = tmp_path / ".run"
    (run / "logs").mkdir(parents=True)
    for name, text in logs.items():
        (run / "logs" / f"{name}.log").write_text(text, encoding="utf-8")
    (run / "pids.json").write_text(json.dumps({"services": services}), encoding="utf-8")
    return run


def by_role(rows, role):
    return [r for r in rows if r["role"] == role][0]


def by_name(rows):
    return {r["name"]: r for r in rows}


def standard_run(tmp_path, mailbox=False):
    run = write_run(tmp_path, {
        "buyer": alive_rec(tmp_path / ".run" / "logs" / "buyer.log", mailbox),
        "advocate": alive_rec(tmp_path / ".run" / "logs" / "advocate.log", mailbox),
        "sellers": alive_rec(tmp_path / ".run" / "logs" / "sellers.log", mailbox),
    }, {"buyer": BUYER_LOG, "advocate": ADVOCATE_LOG, "sellers": SELLERS_LOG})
    return run


def test_parses_agent_rows_from_launcher_logs(tmp_path):
    rows = by_name(F.agent_rows(standard_run(tmp_path)))
    assert set(rows) == {"tech_bazaar_buyer", "quality_advocate", "Byte Bros Outlet", "Silicon Sally's Surplus"}
    b = rows["tech_bazaar_buyer"]
    assert b["role"] == "buyer" and b["address"] == ADDR_B
    assert b["last_message"] == "late or stray bid ignored"
    assert rows["quality_advocate"]["role"] == "advocate"
    assert rows["quality_advocate"]["last_message"].startswith("shield block from")
    # one Bureau log, two agents: each gets its own last line, never the other's
    assert rows["Byte Bros Outlet"]["role"] == "seller"
    assert rows["Byte Bros Outlet"]["last_message"] == "payment committed: 1249.99 USD, ref r2"
    assert rows["Silicon Sally's Surplus"]["last_message"] == "payment committed: 1249.99 USD, ref r1"
    assert rows["Silicon Sally's Surplus"]["address"] == ADDR_2


def test_startup_noise_is_not_a_last_message(tmp_path):
    run = write_run(tmp_path, {"advocate": alive_rec(tmp_path / ".run" / "logs" / "advocate.log")},
                    {"advocate": ADVOCATE_LOG.rsplit("WARNING", 1)[0]})
    row = [r for r in F.agent_rows(run) if r["role"] == "advocate"][0]
    assert row["name"] == "quality_advocate" and row["last_message"] is None and row["at"] is None


def test_timestamp_only_for_the_agent_that_wrote_the_log_last(tmp_path):
    rows = by_name(F.agent_rows(standard_run(tmp_path)))
    assert rows["Byte Bros Outlet"]["at"] is not None and rows["Byte Bros Outlet"]["at"].endswith("+00:00")
    assert rows["Silicon Sally's Surplus"]["at"] is None


def test_status_agentverse_only_when_mailbox_flag_is_on(tmp_path):
    on = F.agent_rows(standard_run(tmp_path / "on", mailbox=True))
    off = F.agent_rows(standard_run(tmp_path / "off", mailbox=False))
    assert {r["status"] for r in on} == {"agentverse"}
    assert {r["status"] for r in off} == {"local"}


def test_old_pidfile_without_mailbox_field_is_local(tmp_path):
    assert {r["status"] for r in F.agent_rows(standard_run(tmp_path, mailbox=None))} == {"local"}


def test_mailbox_on_but_manifest_not_published_is_local(tmp_path):
    run = standard_run(tmp_path, mailbox=True)
    (run / "logs" / "buyer.log").write_text(BUYER_LOG + "WARNING:  [tech_bazaar_buyer]: Unable to publish manifest\n", encoding="utf-8")
    rows = by_name(F.agent_rows(run))
    assert rows["tech_bazaar_buyer"]["status"] == "local"
    assert rows["quality_advocate"]["status"] == "agentverse"


def test_missing_run_dir_gives_three_down_rows_never_raises(tmp_path):
    rows = F.agent_rows(tmp_path / "does-not-exist")
    assert {r["role"] for r in rows} == {"buyer", "advocate", "seller"}
    assert {r["status"] for r in rows} == {"down"}
    assert all(r["address"] is None and r["last_message"] is None and r["origin"] == "SIM" for r in rows)


def test_corrupt_pidfile_is_the_same_as_missing(tmp_path):
    run = tmp_path / ".run"
    run.mkdir()
    (run / "pids.json").write_text("{not json", encoding="utf-8")
    assert {r["status"] for r in F.agent_rows(run)} == {"down"}


def test_missing_log_file_gives_status_down_even_with_a_live_process(tmp_path):
    run = write_run(tmp_path, {"buyer": alive_rec(tmp_path / ".run" / "logs" / "gone.log", mailbox=True)}, {})
    rows = F.agent_rows(run)
    buyer = [r for r in rows if r["role"] == "buyer"]
    assert len(buyer) == 1 and buyer[0]["status"] == "down" and buyer[0]["address"] is None


def test_dead_process_is_down_but_keeps_what_the_log_said(tmp_path):
    run = standard_run(tmp_path, mailbox=True)
    state = json.loads((run / "pids.json").read_text())
    state["services"]["buyer"]["lstart"] = "Thu Jan  1 00:00:00 1970"
    (run / "pids.json").write_text(json.dumps(state))
    b = by_name(F.agent_rows(run))["tech_bazaar_buyer"]
    assert b["status"] == "down" and b["address"] == ADDR_B and b["origin"] == "SIM"


def test_skipped_service_is_down_with_its_reason(tmp_path):
    run = write_run(tmp_path, {"sellers": {"state": "skipped", "port": 8010, "reason": "agents venv missing", "group": "agents"}}, {})
    row = [r for r in F.agent_rows(run) if r["role"] == "seller"][0]
    assert row["status"] == "down" and row["last_message"] == "agents venv missing"


def test_only_agent_services_become_rows(tmp_path):
    run = write_run(tmp_path, {"web": {"state": "running", "pid": os.getpid(), "lstart": L.proc_start_marker(os.getpid()),
                                       "group": "web", "log": str(tmp_path / "w.log")},
                               "buyer": alive_rec(tmp_path / ".run" / "logs" / "buyer.log")}, {"buyer": BUYER_LOG})
    assert {r["role"] for r in F.agent_rows(run) if r["status"] != "down"} == {"buyer"}
    assert "web" not in {r["name"] for r in F.agent_rows(run)}


def test_secrets_and_long_lines_never_reach_the_feed(tmp_path):
    log = ("INFO:     [tech_bazaar_buyer]: Starting agent with address: " + ADDR_B + "\n"
           "INFO:     [tech_bazaar_buyer]: charged with sk_test_SUPERSECRETVALUE123 ok\n")
    run = write_run(tmp_path, {"buyer": alive_rec(tmp_path / ".run" / "logs" / "buyer.log")}, {"buyer": log})
    msg = by_role(F.agent_rows(run), "buyer")["last_message"]
    assert "SUPERSECRET" not in msg and "sk_test" not in msg
    log2 = "INFO:     [tech_bazaar_buyer]: Starting agent with address: " + ADDR_B + "\nINFO:     [tech_bazaar_buyer]: " + "x" * 500 + "\n"
    (run / "logs" / "buyer.log").write_text(log2, encoding="utf-8")
    assert len(by_role(F.agent_rows(run), "buyer")["last_message"]) <= F.MAX_MESSAGE


def test_order_and_mandate_json_lines_are_not_shown(tmp_path):
    log = (f"INFO:     [tech_bazaar_buyer]: Starting agent with address: {ADDR_B}\n"
           "INFO:     [tech_bazaar_buyer]: to owner: Bids are in\n"
           'INFO:     [tech_bazaar_buyer]: MANDATE {"deal_id": "d", "nonce": "n"}\n')
    run = write_run(tmp_path, {"buyer": alive_rec(tmp_path / ".run" / "logs" / "buyer.log")}, {"buyer": log})
    assert by_role(F.agent_rows(run), "buyer")["last_message"] == "to owner: Bids are in"


def test_http_endpoint_returns_the_rows_and_allows_the_local_web_origin(tmp_path):
    from fastapi.testclient import TestClient
    client = TestClient(F.create_app(standard_run(tmp_path, mailbox=True)))
    r = client.get("/v1/agents", headers={"Origin": "http://localhost:3100"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3100"
    assert {x["status"] for x in r.json()} == {"agentverse"}
    assert set(r.json()[0]) == {"name", "role", "address", "status", "last_message", "at", "origin"}
    assert client.get("/v1/agents", headers={"Origin": "https://evil.example"}).headers.get("access-control-allow-origin") is None
    assert client.get("/v1/health").json() == {"ok": True}


def test_http_endpoint_with_missing_run_dir_is_200_with_down_rows(tmp_path):
    from fastapi.testclient import TestClient
    r = TestClient(F.create_app(tmp_path / "nope")).get("/v1/agents")
    assert r.status_code == 200 and {x["status"] for x in r.json()} == {"down"}


def test_launcher_runs_the_feed_and_records_the_mailbox_flag(tmp_path):
    from argparse import Namespace
    base = dict(shield_port=8787, stdb_port=3000, web_port=3100, run_dir=str(tmp_path / "rd"))
    on = {s.name: s for s in L.build_services(Namespace(**base, mailbox=True), tmp_path)}
    feed = on["agent-feed"]
    assert feed.port == 8790 and feed.health_path == "/v1/health" and feed.extra_env["AGENT_FEED_RUN_DIR"] == str(tmp_path / "rd")
    assert "agent_feed:app" in feed.cmd and "8790" in feed.cmd
    assert L.mailbox_record(on["buyer"]) is True and L.mailbox_record(on["shield"]) is False
    off = {s.name: s for s in L.build_services(Namespace(**base, mailbox=False), tmp_path)}
    assert L.mailbox_record(off["buyer"]) is False


def test_missing_fastapi_skips_the_feed_like_the_shield():
    from argparse import Namespace
    svcs = L.build_services(Namespace(shield_port=8787, stdb_port=3000, web_port=3100, mailbox=False), Path("/nowhere"))
    checks = [L.Check("shield deps (fastapi, uvicorn)", False, "", "fix")]
    L.decide_skips(svcs, checks)
    assert {s.name for s in svcs if s.skip_reason} == {"shield", "agent-feed"}
