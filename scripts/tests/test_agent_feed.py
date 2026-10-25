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


def mailbox_up(*tags: str) -> str:
    """The line uagents logs once an agent's mailbox client loop runs (mailbox.py:214)."""
    return "".join(f"INFO:     [{t}]: Starting mailbox client for https://agentverse.ai\n" for t in tags)


def standard_run(tmp_path, mailbox=False, flag=None):
    """mailbox=True: every agent's log shows its mailbox client started. flag: the pidfile hint (defaults to mailbox)."""
    flag = mailbox if flag is None else flag
    up = (lambda *t: mailbox_up(*t)) if mailbox else (lambda *t: "")
    run = write_run(tmp_path, {
        "buyer": alive_rec(tmp_path / ".run" / "logs" / "buyer.log", flag),
        "advocate": alive_rec(tmp_path / ".run" / "logs" / "advocate.log", flag),
        "sellers": alive_rec(tmp_path / ".run" / "logs" / "sellers.log", flag),
    }, {"buyer": up("tech_bazaar_buyer") + BUYER_LOG, "advocate": up("quality_advocate") + ADVOCATE_LOG,
        "sellers": up("Byte Bros Outlet", "Silicon Sally's Surplus") + SELLERS_LOG})
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


def test_status_agentverse_only_when_the_mailbox_client_started(tmp_path):
    on = F.agent_rows(standard_run(tmp_path / "on", mailbox=True))
    off = F.agent_rows(standard_run(tmp_path / "off", mailbox=False))
    assert {r["status"] for r in on} == {"agentverse"}
    assert {r["status"] for r in off} == {"local"}


def test_old_pidfile_without_mailbox_field_is_local(tmp_path):
    assert {r["status"] for r in F.agent_rows(standard_run(tmp_path, mailbox=False, flag=None))} == {"local"}


def test_pidfile_flag_alone_proves_nothing(tmp_path):
    # flag true, manifests published (BUYER_LOG says so), but the log never shows the mailbox client starting
    rows = F.agent_rows(standard_run(tmp_path, mailbox=False, flag=True))
    assert {r["status"] for r in rows} == {"local"}


def test_mailbox_client_running_without_the_pidfile_flag_is_agentverse(tmp_path):
    # AGENTS_MAILBOX=1 set only in agents/.env: the launcher records mailbox=false, the agents still run the mailbox client
    rows = F.agent_rows(standard_run(tmp_path, mailbox=True, flag=False))
    assert {r["status"] for r in rows} == {"agentverse"}


@pytest.mark.parametrize("bad", [
    "WARNING:  [tech_bazaar_buyer]: Agent mailbox not found: create one using the agent inspector\n",
    "WARNING:  [tech_bazaar_buyer]: Failed to connect to mailbox server: Cannot connect to host agentverse.ai\n",
    "ERROR:    [tech_bazaar_buyer]: Failed to retrieve messages: 401:Unauthorized\n",
    "WARNING:  [tech_bazaar_buyer]: Unable to publish manifest: timeout\n",
])
def test_mailbox_failure_lines_keep_that_agent_local(tmp_path, bad):
    run = standard_run(tmp_path, mailbox=True)
    (run / "logs" / "buyer.log").write_text(mailbox_up("tech_bazaar_buyer") + BUYER_LOG + bad, encoding="utf-8")
    rows = by_name(F.agent_rows(run))
    assert rows["tech_bazaar_buyer"]["status"] == "local"
    assert rows["quality_advocate"]["status"] == "agentverse"


def test_mailbox_not_found_warning_is_not_dropped_as_noise_but_start_line_is(tmp_path):
    log = (f"INFO:     [tech_bazaar_buyer]: Starting agent with address: {ADDR_B}\n"
           "INFO:     [tech_bazaar_buyer]: Agent inspector available at https://agentverse.ai/inspect/?uri=x\n"
           + mailbox_up("tech_bazaar_buyer")
           + "WARNING:  [tech_bazaar_buyer]: Agent mailbox not found: create one using the agent inspector\n")
    run = write_run(tmp_path, {"buyer": alive_rec(tmp_path / ".run" / "logs" / "buyer.log", True)}, {"buyer": log})
    row = by_role(F.agent_rows(run), "buyer")
    assert row["last_message"] == "Agent mailbox not found: create one using the agent inspector"
    assert row["status"] == "local"
    # the positive line alone never shows up as a message
    run2 = write_run(tmp_path / "two", {"buyer": alive_rec(tmp_path / "two" / ".run" / "logs" / "buyer.log", True)},
                     {"buyer": log.rsplit("WARNING", 1)[0]})
    row2 = by_role(F.agent_rows(run2), "buyer")
    assert row2["last_message"] is None and row2["status"] == "agentverse"


def test_mailbox_is_decided_per_agent_in_a_shared_bureau_log(tmp_path):
    log = mailbox_up("Byte Bros Outlet") + SELLERS_LOG
    run = write_run(tmp_path, {"sellers": alive_rec(tmp_path / ".run" / "logs" / "sellers.log")}, {"sellers": log})
    rows = by_name(F.agent_rows(run))
    assert rows["Byte Bros Outlet"]["status"] == "agentverse"
    assert rows["Silicon Sally's Surplus"]["status"] == "local"


def test_mailbox_up_but_process_dead_is_down(tmp_path):
    run = standard_run(tmp_path, mailbox=True)
    state = json.loads((run / "pids.json").read_text())
    state["services"]["buyer"]["lstart"] = "Thu Jan  1 00:00:00 1970"
    (run / "pids.json").write_text(json.dumps(state))
    assert by_name(F.agent_rows(run))["tech_bazaar_buyer"]["status"] == "down"


def test_our_agents_are_never_labelled_live(tmp_path):
    rows = F.agent_rows(standard_run(tmp_path, mailbox=True))
    assert {r["origin"] for r in rows} == {"SIM"}


def test_seller_origin_comes_from_its_config(tmp_path):
    cfg = tmp_path / "sellers.json"
    cfg.write_text(json.dumps({"sellers": {"seller_1": {"name": "Byte Bros Outlet", "origin": "MIRROR"},
                                           "seller_2": {"name": "Odd One", "origin": "bogus"}}}), encoding="utf-8")
    assert F.seller_origins(cfg) == {"Byte Bros Outlet": "MIRROR"}
    assert F.seller_origins(tmp_path / "missing.json") == {}
    real = F.seller_origins()
    assert real and set(real.values()) == {"SIM"}  # every shipped seller is SIM


def test_old_message_is_not_stamped_by_a_later_noise_line(tmp_path):
    run = standard_run(tmp_path)
    log = run / "logs" / "buyer.log"
    os.utime(log, (1, 1))
    assert by_role(F.agent_rows(run), "buyer")["at"] is not None  # message is the last line: its mtime is its time
    log.write_text(BUYER_LOG + "INFO:     [uagents.registration]: Registration on Almanac API successful\n", encoding="utf-8")
    row = by_role(F.agent_rows(run), "buyer")
    assert row["last_message"] == "late or stray bid ignored" and row["at"] is None
    # a boot line from the same agent after the message does the same
    log.write_text(BUYER_LOG + "INFO:     [tech_bazaar_buyer]: Manifest published successfully: X\n\n", encoding="utf-8")
    assert by_role(F.agent_rows(run), "buyer")["at"] is None


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
    assert {x["origin"] for x in r.json()} == {"SIM"}
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


def test_mailbox_record_reads_the_final_env_not_just_the_flag(tmp_path, monkeypatch):
    from argparse import Namespace
    for k in ("AGENTS_MAILBOX", "BUYER_MAILBOX", "ADVOCATE_MAILBOX", "SELLERS_MAILBOX"):
        monkeypatch.delenv(k, raising=False)
    off = {s.name: s for s in L.build_services(Namespace(shield_port=8787, stdb_port=3000, web_port=3100, mailbox=False), tmp_path)}
    assert L.mailbox_record(off["buyer"]) is False
    # AGENTS_MAILBOX set only in agents/.env (the agents load it themselves): `up` without --mailbox still runs them on Agentverse
    assert L.mailbox_record(off["buyer"], {}, {"AGENTS_MAILBOX": "1"}) is True
    assert L.mailbox_record(off["sellers"], {}, {"AGENTS_MAILBOX": "1"}) is True
    # the launcher env file and a per-role flag count too; the role flag is per role
    assert L.mailbox_record(off["advocate"], {"ADVOCATE_MAILBOX": "1"}) is True
    assert L.mailbox_record(off["buyer"], {"ADVOCATE_MAILBOX": "1"}) is False
    # not an agent service
    assert L.mailbox_record(off["shield"], {"AGENTS_MAILBOX": "1"}, {"AGENTS_MAILBOX": "1"}) is False


def test_missing_fastapi_skips_the_feed_like_the_shield():
    from argparse import Namespace
    svcs = L.build_services(Namespace(shield_port=8787, stdb_port=3000, web_port=3100, mailbox=False), Path("/nowhere"))
    checks = [L.Check("shield deps (fastapi, uvicorn)", False, "", "fix")]
    L.decide_skips(svcs, checks)
    assert {s.name for s in svcs if s.skip_reason} == {"shield", "agent-feed", "seller-kit"}


# ---- T4R: module loggers are not agents; a mailbox created after start clears "Local only" -------------------------------

MODULE_NOISE = (
    "WARNING:  [resolver]: Almanac API lookup attempt 1/3 for agent1qxyz failed: timeout\n"
    "ERROR:    [dispenser]: Failed to send envelope: Cannot connect to host localhost:8014\n"
    "INFO:     [network]: Registering on Almanac\n"
    "INFO:     [setup]: configuring\n"
    "INFO:     [server]: listening\n"
    "WARNING:  [config]: something\n"
    "INFO:     [communication]: dispatch\n"
)


def test_module_loggers_never_become_rows_even_with_fresh_errors(tmp_path):
    run = standard_run(tmp_path)
    log = run / "logs" / "buyer.log"
    log.write_text(BUYER_LOG + MODULE_NOISE, encoding="utf-8")
    rows = F.agent_rows(run)
    assert [r["name"] for r in rows if r["role"] == "buyer"] == ["tech_bazaar_buyer"]
    buyer = by_role(rows, "buyer")
    assert buyer["last_message"] == "late or stray bid ignored"
    # the module errors came after the buyer's last line, so it is not stamped fresh by them
    assert buyer["at"] is None
    assert not {"resolver", "dispenser", "network", "setup", "server", "config", "communication"} & set(by_name(rows))


def test_module_logger_only_log_is_a_down_row_not_a_made_up_agent(tmp_path):
    run = write_run(tmp_path, {"buyer": alive_rec(tmp_path / ".run" / "logs" / "buyer.log")}, {"buyer": MODULE_NOISE})
    rows = [r for r in F.agent_rows(run) if r["role"] == "buyer"]
    assert len(rows) == 1 and rows[0]["name"] == F.DEFAULT_NAMES["buyer"]
    assert rows[0]["status"] == "down" and rows[0]["last_message"] is None and rows[0]["address"] is None


def test_agent_whose_line_comes_before_its_start_line_still_gets_its_row(tmp_path):
    log = ("INFO:     [tech_bazaar_buyer]: to owner: early message\n"
           f"INFO:     [tech_bazaar_buyer]: Starting agent with address: {ADDR_B}\n" + MODULE_NOISE)
    run = write_run(tmp_path, {"buyer": alive_rec(tmp_path / ".run" / "logs" / "buyer.log")}, {"buyer": log})
    row = by_role(F.agent_rows(run), "buyer")
    assert row["name"] == "tech_bazaar_buyer" and row["last_message"] == "to owner: early message"


REGISTERED = "INFO:     [mailbox]: Successfully registered as mailbox agent in Agentverse\n"
NOT_FOUND = "WARNING:  [{t}]: Agent mailbox not found: create one using the agent inspector\n"


def seller4_log(*extra: str) -> str:
    return (f"INFO:     [seller_4]: Starting agent with address: {ADDR_1}\n" + mailbox_up("seller_4")
            + NOT_FOUND.format(t="seller_4") + "".join(extra))


def test_mailbox_created_after_start_clears_local_only_without_a_restart(tmp_path):
    run = write_run(tmp_path, {"sellers": alive_rec(tmp_path / ".run" / "logs" / "sellers.log")},
                    {"sellers": seller4_log(REGISTERED)})
    rows = [r for r in F.agent_rows(run) if r["role"] == "seller"]
    assert [r["name"] for r in rows] == ["seller_4"]  # no phantom 'mailbox' row
    assert rows[0]["status"] == "agentverse"
    # the stale 404 text is replaced by the registration line
    assert rows[0]["last_message"] == "Successfully registered as mailbox agent in Agentverse"
    # before connect.py runs it is still honest
    before = write_run(tmp_path / "b", {"sellers": alive_rec(tmp_path / "b" / ".run" / "logs" / "sellers.log")},
                       {"sellers": seller4_log()})
    assert [r["status"] for r in F.agent_rows(before) if r["role"] == "seller"] == ["local"]


def test_registration_line_with_two_agents_missing_a_mailbox_cannot_say_which(tmp_path):
    log = (f"INFO:     [seller_4]: Starting agent with address: {ADDR_1}\n"
           f"INFO:     [seller_5]: Starting agent with address: {ADDR_2}\n"
           + mailbox_up("seller_4", "seller_5") + NOT_FOUND.format(t="seller_4") + NOT_FOUND.format(t="seller_5") + REGISTERED)
    run = write_run(tmp_path, {"sellers": alive_rec(tmp_path / ".run" / "logs" / "sellers.log")}, {"sellers": log})
    rows = by_name([r for r in F.agent_rows(run) if r["role"] == "seller"])
    assert set(rows) == {"seller_4", "seller_5"}
    assert {r["status"] for r in rows.values()} == {"local"}  # unattributable: stay Local only, never guess Agentverse


def test_registration_line_may_belong_to_another_running_mailbox_agent(tmp_path):
    # seller_1 already has its mailbox; seller_4 got the 404; a re-run of connect.py for seller_1 logs the line
    log = (f"INFO:     [seller_1]: Starting agent with address: {ADDR_2}\n" + mailbox_up("seller_1")
           + f"INFO:     [seller_4]: Starting agent with address: {ADDR_1}\n" + mailbox_up("seller_4")
           + NOT_FOUND.format(t="seller_4") + REGISTERED)
    run = write_run(tmp_path, {"sellers": alive_rec(tmp_path / ".run" / "logs" / "sellers.log")}, {"sellers": log})
    rows = by_name([r for r in F.agent_rows(run) if r["role"] == "seller"])
    assert rows["seller_4"]["status"] == "local"
    assert rows["seller_4"]["last_message"] == "Agent mailbox not found: create one using the agent inspector"
    assert rows["seller_1"]["status"] == "agentverse"


def test_registration_line_never_clears_a_connect_or_auth_failure(tmp_path):
    for n, bad in enumerate(("WARNING:  [seller_4]: Failed to connect to mailbox server: Cannot connect to host agentverse.ai\n",
                "ERROR:    [seller_4]: Failed to retrieve messages: 401:Unauthorized\n")):
        log = (f"INFO:     [seller_4]: Starting agent with address: {ADDR_1}\n" + mailbox_up("seller_4")
               + NOT_FOUND.format(t="seller_4") + REGISTERED + bad)
        base = tmp_path / str(n)
        run = write_run(base, {"sellers": alive_rec(base / ".run" / "logs" / "sellers.log")}, {"sellers": log})
        assert [r["status"] for r in F.agent_rows(run) if r["role"] == "seller"] == ["local"]


def test_a_second_not_found_after_registration_goes_local_again(tmp_path):
    run = write_run(tmp_path, {"sellers": alive_rec(tmp_path / ".run" / "logs" / "sellers.log")},
                    {"sellers": seller4_log(REGISTERED, NOT_FOUND.format(t="seller_4"))})
    assert [r["status"] for r in F.agent_rows(run) if r["role"] == "seller"] == ["local"]



# ---------------------------------------------------------------- GET /v1/memory (#189)

def test_memory_endpoint_returns_entries_from_the_memory_dir(tmp_path):
    import shutil
    from fastapi.testclient import TestClient
    sample = SCRIPTS.parent / "demo" / "out" / "sample-run.json"
    shutil.copy(sample, tmp_path / "run-20261024T120000Z.json")
    client = TestClient(F.create_app(tmp_path / "run", memory_dir=tmp_path))
    body = client.get("/v1/memory").json()
    assert body["entries"] and {e["kind"] for e in body["entries"]} == {"goal", "purchase", "veto", "lesson"}
    assert all(e["origin"] in ("LIVE", "MIRROR", "SIM") for e in body["entries"])
    vetoes = client.get("/v1/memory", params={"kind": "veto", "limit": 1}).json()["entries"]
    assert len(vetoes) == 1 and vetoes[0]["kind"] == "veto"


def test_memory_endpoint_with_nothing_recorded_says_so(tmp_path):
    from fastapi.testclient import TestClient
    body = TestClient(F.create_app(tmp_path / "run", memory_dir=tmp_path / "none")).get("/v1/memory").json()
    assert body == {"entries": [], "sources": [], "note": "no demo runs or market snapshots recorded yet"}



@pytest.mark.parametrize("where", ["summary", "notes", "run_id"])
def test_memory_endpoint_survives_a_lone_surrogate(tmp_path, where):
    import json as _json
    from fastapi.testclient import TestClient
    sample = _json.loads((SCRIPTS.parent / "demo" / "out" / "sample-run.json").read_text())
    if where == "summary":
        (tmp_path / "market-memory-1.json").write_text(_json.dumps({"entries": [
            {"id": "x", "kind": "goal", "at": "1", "origin": "SIM", "summary": "\ud800", "detail": {}}]}))
    elif where == "notes":
        sample["artifacts"]["goal"]["notes"] = "\ud800"
        (tmp_path / "run-1.json").write_text(_json.dumps(sample))
    else:
        sample["run_id"] = "\ud800"
        (tmp_path / "run-1.json").write_text(_json.dumps(sample))
    r = TestClient(F.create_app(tmp_path / "run", memory_dir=tmp_path)).get("/v1/memory")
    assert r.status_code == 200 and "entries" in r.json()


# ---------------------------------------------------------------- GET /v1/build (the live BuildView for the /buyer panel)

HASH = "0x" + "ab" * 32
PRIVATE_BITS = (HASH, "Payee Seller LLC", "pay-ref-9", "voice_code", "approval-code-4821", "allowance", "+15551230000")


def _full_view() -> dict:
    """A BuildView as demo/build.py writes it to demo/out/build-view.json, with every private field filled in."""
    champ = {"bidId": "bid-1", "sellerId": "seller-1", "persona": "Micro Center", "landed": 1299.0, "origin": "MIRROR",
             "sourceUrl": "https://example.test/gpu", "mandateHash": HASH, "phone": "+15551230000",
             "liveCheck": {"state": "ok", "price": 1299.0}}
    return {"goalId": "goal-build-1", "buyerId": "vidyut", "budget": 2100.0, "spent": 1299.0, "origin": "MIRROR", "secret": "x",
            "parts": [{"part": "gpu", "label": "RTX 5070 Ti", "status": "locked", "budget": 1329.0, "origin": "MIRROR",
                       "champion": champ, "payee": "Payee Seller LLC"}],
            "checks": [{"a": "gpu", "b": "psu", "rule": "power", "state": "ok", "detail": "750 W is enough", "source": "fit.psu_wattage"}],
            "events": [{"at": "t1", "kind": "locked", "text": "RTX 5070 Ti: Micro Center locked at $1,299.00", "parts": ["gpu"], "origin": "MIRROR"},
                       {"at": "t2", "kind": "call", "text": "Calling Vidyut at +15551230000, code approval-code-4821", "parts": [], "origin": "SIM"},
                       {"at": "t3", "kind": "approved", "text": "Inside your allowance: $1,299.00", "parts": [], "origin": "SIM"},
                       {"at": "t4", "kind": "receipt", "text": "Payment recorded: pay-ref-9", "parts": ["gpu"], "origin": "SIM"}],
            "approval": {"state": "approved", "total": 1299.0, "sellers": 1, "method": "voice_code", "reason": "allowance rule",
                         "mandates": [{"sellerId": "Payee Seller LLC", "amount": 1299.0, "mandateHash": HASH, "part": "gpu"}]}}


def _build_client(tmp_path, text: str | None = None):
    from fastapi.testclient import TestClient
    if text is not None:
        (tmp_path / "build-view.json").write_text(text, encoding="utf-8")
    return TestClient(F.create_app(tmp_path / "run", build_dir=tmp_path))


def test_build_endpoint_never_carries_the_whole_build_approval_code_whatever_key_it_rides_in(tmp_path):
    """The code belongs to the buyer's own paired /buyer card (market approval_code row), never to this unauthenticated feed."""
    word = "amber harbor"
    view = _full_view()
    view["approval"].update(code=word, approvalCode=word, wordPair=word, pendingCode=word)
    view["code"] = word
    view["parts"][0]["code"] = word
    view["events"][0]["code"] = word
    r = _build_client(tmp_path, json.dumps(view)).get("/v1/build")
    assert r.status_code == 200 and word not in r.text and "harbor" not in r.text
    for key in ("code", "approvalCode", "wordPair", "pendingCode"):
        assert f'"{key}"' not in r.text


def test_build_endpoint_serves_the_latest_view_without_private_fields(tmp_path):
    r = _build_client(tmp_path, json.dumps(_full_view())).get("/v1/build")
    assert r.status_code == 200
    body = r.json()
    assert body["goalId"] == "goal-build-1" and body["origin"] == "MIRROR"
    assert body["parts"][0]["champion"]["persona"] == "Micro Center" and body["parts"][0]["champion"]["origin"] == "MIRROR"
    assert body["approval"] == {"state": "approved", "total": 1299.0, "sellers": 1}
    assert [e["kind"] for e in body["events"]] == ["locked"]
    for bit in PRIVATE_BITS:
        assert bit not in r.text
    for key in ("mandates", "mandateHash", "phone", "payee", "secret", "liveCheck", "method", "reason"):
        assert f'"{key}"' not in r.text


def test_build_endpoint_is_404_until_a_run_wrote_a_view(tmp_path):
    r = _build_client(tmp_path).get("/v1/build")
    assert r.status_code == 404


@pytest.mark.parametrize("text", ['{"goalId": "goal-1", "parts": [{"part": "gp', "", "[]", "null", '{"goalId": 7}',
                                  '{"goalId": "g", "parts": "no", "checks": [], "events": []}', r'"\ud800"', '{"a": ' * 3000])
def test_build_endpoint_never_500s_on_a_half_written_or_odd_file(tmp_path, text):
    r = _build_client(tmp_path, text).get("/v1/build")
    assert r.status_code in (404, 503), r.status_code


def test_build_endpoint_survives_a_lone_surrogate_inside_a_valid_view(tmp_path):
    view = _full_view()
    view["parts"][0]["champion"]["persona"] = "\ud800"
    r = _build_client(tmp_path, json.dumps(view)).get("/v1/build")  # json.dumps escapes it, so the file itself is valid
    assert r.status_code in (200, 503)


def test_build_endpoint_skips_rows_of_the_wrong_type(tmp_path):
    view = _full_view()
    view["parts"].append("junk")
    view["events"].append(5)
    view["checks"].append(None)
    r = _build_client(tmp_path, json.dumps(view)).get("/v1/build")
    assert r.status_code == 200 and len(r.json()["parts"]) == 1


def test_build_endpoint_dir_comes_from_BUILD_VIEW_DIR(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    (tmp_path / "build-view.json").write_text(json.dumps(_full_view()), encoding="utf-8")
    monkeypatch.setenv("BUILD_VIEW_DIR", str(tmp_path))
    assert TestClient(F.create_app(tmp_path / "run")).get("/v1/build").status_code == 200


def test_build_endpoint_default_dir_is_the_one_build_py_writes():
    from demo import build as B
    spec_dir = F.default_build_dir()
    assert spec_dir == B.OUT_DIR and F.BUILD_VIEW_FILE == B.VIEW_FILE


def test_build_endpoint_serves_a_real_dry_run_view_the_panel_can_parse(tmp_path):
    """demo/build.py --dry-run --out-dir writes the real BuildView offline; the feed serves it stripped, and the committed web
    fixture (web/src/lib/fixtures/build-feed.served.json, parsed by web/src/lib/buildView.test.ts) is that shape."""
    import subprocess
    root = SCRIPTS.parent
    done = subprocess.run([sys.executable, str(root / "demo" / "build.py"), "--dry-run", "--out-dir", str(tmp_path)],
                          cwd=root, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-500:]
    raw = json.loads((tmp_path / "build-view.json").read_text())
    r = _build_client(tmp_path).get("/v1/build")
    assert r.status_code == 200
    body = r.json()
    assert body == F.buyer_view(raw)
    assert body["goalId"] == raw["goalId"] and len(body["parts"]) == len(raw["parts"])
    assert "mandates" not in body["approval"]
    fixture = json.loads((root / "web" / "src" / "lib" / "fixtures" / "build-feed.served.json").read_text())
    assert F.buyer_view(fixture) == fixture  # the web test's fixture is exactly what the feed serves
    assert set(fixture) == set(body)
