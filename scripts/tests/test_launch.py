"""Launcher tests: no network beyond localhost, fake services only. Run: python3 -m pytest scripts/tests -q"""
import importlib.util
import io
import os
import socket
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("launch", Path(__file__).resolve().parents[1] / "launch.py")
L = importlib.util.module_from_spec(_spec)
sys.modules["launch"] = L
_spec.loader.exec_module(L)

SECRET = "sk_test_SUPERSECRETVALUE123"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fake_http(port: int) -> L.Service:
    code = f"import http.server;http.server.HTTPServer(('127.0.0.1',{port}),http.server.SimpleHTTPRequestHandler).serve_forever()"
    return L.Service("fake-http", port, [sys.executable, "-c", code], Path.cwd(), health="http", health_path="/")


def fake_tcp(port: int, name="fake-agent") -> L.Service:
    code = (f"import socket,time;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
            f"s.bind(('127.0.0.1',{port}));s.listen();"
            "print('seller_1 address: agent1q' + 'a'*58, flush=True);time.sleep(600)")
    return L.Service(name, port, [sys.executable, "-c", code], Path.cwd(), health="tcp")


def wait_up(rec, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if L.evaluate(rec)[0] == "UP":
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def run_dir(tmp_path):
    return tmp_path / ".run"


@pytest.fixture
def started(run_dir):
    """Start fake services, always stop them at the end."""
    recs = {}

    def start(svc):
        recs[svc.name] = L.start_process(svc, dict(os.environ), run_dir)
        return recs[svc.name]

    yield start
    for r in recs.values():
        L.stop_record(r, grace=1)


# ---- preflight parsing

def test_parse_env_text_handles_quotes_comments_export_and_bad_lines():
    text = f'# c\n\nA=1\nexport B="two words"\nC=\'x\'\nEMPTY=\nthis is not a pair\n9BAD=1\nKEY={SECRET}\n'
    vals, bad = L.parse_env_text(text)
    assert vals == {"A": "1", "B": "two words", "C": "x", "EMPTY": "", "KEY": SECRET}
    assert bad == [7, 8]  # line numbers only


def test_load_env_file_drops_empty_values_and_note_has_no_values(tmp_path):
    f = tmp_path / "e"
    f.write_text(f"STRIPE_SECRET_KEY={SECRET}\nANTHROPIC_API_KEY=\nbroken {SECRET}\n")
    env, note = L.load_env_file(f)
    assert env == {"STRIPE_SECRET_KEY": SECRET}
    assert SECRET not in note and "unparseable line numbers [3]" in note


def test_missing_env_file_is_reported_not_raised(tmp_path):
    env, note = L.load_env_file(tmp_path / "nope")
    assert env == {} and "not found" in note


def test_key_report_names_only():
    present, missing = L.key_report(["A", "B", "C"], {"A": "v", "B": ""})
    assert present == ["A"] and missing == ["B", "C"]


def make_args(**kw):
    d = dict(shield_port=8787, web_port=3100, stdb_port=3000, only=None, run_dir=".run", env_file="x", strict=False)
    d.update(kw)
    return Namespace(**d)


def preflight(tmp_repo, which, env=None, **kw):
    a = make_args()
    svcs = L.build_services(a, tmp_repo)
    checks = L.run_preflight(a, svcs, env if env is not None else {"ANTHROPIC_API_KEY": SECRET}, "note", repo=tmp_repo, which=which,
                             can_import=kw.get("can_import", lambda m: True), port_busy=kw.get("port_busy", lambda p: False),
                             home_bin=kw.get("home_bin", tmp_repo / "nobin"))
    return svcs, checks


def test_preflight_prints_ok_and_missing_with_fix_and_never_values(tmp_path):
    svcs, checks = preflight(tmp_path, which=lambda n: None)
    buf = io.StringIO()
    L.print_preflight(checks, buf)
    text = buf.getvalue()
    assert "[MISSING] spacetime CLI" in text and "curl -sSf https://install.spacetimedb.com | sh" in text
    assert "[MISSING] node" in text and "brew install node" in text
    assert "[OK     ] keys present (names only): ANTHROPIC_API_KEY" in text
    assert "keys missing (names only)" in text
    assert SECRET not in text


def test_missing_spacetime_skips_market_with_install_command_and_others_untouched(tmp_path):
    (tmp_path / "agents" / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / "agents" / ".venv" / "bin" / "python").write_text("")
    svcs, checks = preflight(tmp_path, which=lambda n: None if n == "spacetime" else f"/bin/{n}")
    L.decide_skips(svcs, checks)
    by = {s.name: s for s in svcs}
    assert "install.spacetimedb.com" in by["market-stdb"].skip_reason
    assert by["shield"].skip_reason is None and by["web"].skip_reason is None and by["buyer"].skip_reason is None


def test_missing_shield_deps_and_node_skip_their_services(tmp_path):
    svcs, checks = preflight(tmp_path, which=lambda n: None if n in ("node", "npm") else "/bin/x",
                             can_import=lambda m: m != "fastapi")
    L.decide_skips(svcs, checks)
    by = {s.name: s for s in svcs}
    assert "fastapi" in by["shield"].skip_reason and "node" in by["web"].skip_reason


def test_busy_port_reported_unless_owned(tmp_path):
    a = make_args()
    svcs = L.build_services(a, tmp_path)
    kw = dict(repo=tmp_path, home_bin=tmp_path / "nobin", which=lambda n: "/bin/x", can_import=lambda m: True, port_busy=lambda p: p == 8787)
    checks = L.run_preflight(a, svcs, {}, "n", **kw)
    assert [c for c in checks if c.name.startswith("port 8787")][0].ok is False
    checks = L.run_preflight(a, svcs, {}, "n", owned_ports={8787}, **kw)
    assert [c for c in checks if c.name.startswith("port 8787")][0].ok is True


def test_ports_come_from_flags():
    p = L.make_parser().parse_args(["up", "--shield-port", "9001", "--web-port", "9002", "--stdb-port", "9003"])
    svcs = {s.name: s for s in L.build_services(p)}
    assert svcs["shield"].port == 9001 and "9001" in svcs["shield"].cmd
    assert svcs["web"].port == 9002 and "9002" in svcs["web"].cmd
    assert svcs["market-stdb"].port == 9003
    assert svcs["buyer"].extra_env["SHIELD_URL"].endswith(":9001")


# ---- env handling

def test_web_gets_only_public_and_stdb_names_others_get_all():
    fe = {"STRIPE_SECRET_KEY": SECRET, "NEXT_PUBLIC_SPACETIMEDB_DB": "db", "SPACETIMEDB_URI": "u"}
    svcs = {s.name: s for s in L.build_services(make_args())}
    web = L.env_for(svcs["web"], fe)
    assert "STRIPE_SECRET_KEY" not in web and web["NEXT_PUBLIC_SPACETIMEDB_DB"] == "db" and web["SPACETIMEDB_URI"] == "u"
    assert L.env_for(svcs["shield"], fe)["STRIPE_SECRET_KEY"] == SECRET


def test_env_loading_never_echoes_values(run_dir, started, tmp_path, capsys):
    envf = tmp_path / "e"
    envf.write_text(f"STRIPE_SECRET_KEY={SECRET}\n")
    env, note = L.load_env_file(envf)
    print(note)
    buf = io.StringIO()
    L.print_preflight(L.run_preflight(make_args(), [], env, note, repo=tmp_path, which=lambda n: None, home_bin=tmp_path / "nobin",
                                      can_import=lambda m: True, port_busy=lambda p: False), buf)
    print(buf.getvalue())
    assert SECRET not in capsys.readouterr().out
    # the child receives it
    svc = L.Service("envprobe", None, [sys.executable, "-c", "import os;print(len(os.environ.get('STRIPE_SECRET_KEY','')))"],
                    tmp_path, health="tcp")
    rec = L.start_process(svc, L.env_for(svc, env), run_dir)
    time.sleep(1)
    assert Path(rec["log"]).read_text().strip() == str(len(SECRET))


def test_redact_hides_values_in_echoed_log_tail(tmp_path):
    p = tmp_path / "l.log"
    p.write_text(f"boom with {SECRET} inside\n")
    out = L.tail(p, secrets={"K": SECRET})
    assert SECRET not in out and "***" in out


# ---- pidfile and down

def test_pidfile_roundtrip_and_corrupt_file(run_dir):
    pf = L.PidFile(run_dir)
    assert pf.load() == {}
    pf.save({"services": {"a": {"pid": 1}}})
    assert pf.load()["services"]["a"]["pid"] == 1
    pf.path.write_text("{not json")
    assert pf.load() == {}
    pf.clear()
    assert not pf.path.exists()


def test_stop_record_kills_only_our_process(started):
    rec = started(fake_tcp(free_port()))
    assert wait_up(rec)
    msg = L.stop_record(rec, grace=3)
    assert "stopped" in msg or "killed" in msg
    assert not L.pid_is_ours(rec)


def test_stop_record_leaves_reused_pid_alone(started):
    rec = started(fake_tcp(free_port()))
    assert wait_up(rec)
    forged = dict(rec, lstart="Thu Jan  1 00:00:00 1970")  # same pid, different start time: not ours
    assert "left alone" in L.stop_record(forged, grace=1)
    assert L.pid_is_ours(rec)  # still running


def test_down_stops_started_services_and_clears_pidfile(run_dir, started, capsys):
    rec = started(fake_tcp(free_port()))
    L.PidFile(run_dir).save({"services": {"fake-agent": rec, "market-stdb": {"state": "skipped", "reason": "x"}}})
    assert L.cmd_down(Namespace(run_dir=str(run_dir))) == 0
    out = capsys.readouterr().out
    assert "fake-agent" in out and "market-stdb" not in out
    assert not L.pid_is_ours(rec) and not L.PidFile(run_dir).path.exists()


# ---- status

def test_status_up_exit_zero_with_skipped_and_address(run_dir, started):
    http_rec = started(fake_http(free_port()))
    agent_rec = started(fake_tcp(free_port()))
    assert wait_up(http_rec) and wait_up(agent_rec)
    L.PidFile(run_dir).save({"services": {"fake-http": http_rec, "fake-agent": agent_rec,
                                          "market-stdb": {"state": "skipped", "port": 3000, "reason": "spacetime CLI not installed"}}})
    buf = io.StringIO()
    code = L.cmd_status(run_dir, out=buf)
    text = buf.getvalue()
    assert code == 0
    assert "SKIPPED" in text and "spacetime CLI not installed" in text
    assert "agent1q" + "a" * 58 in text and "seller_1" in text
    assert L.cmd_status(run_dir, strict=True, out=io.StringIO()) == 1


def test_status_exit_one_when_a_service_is_down(run_dir, started):
    rec = started(fake_tcp(free_port()))
    assert wait_up(rec)
    L.stop_record(rec, grace=3)
    L.PidFile(run_dir).save({"services": {"fake-agent": rec}})
    buf = io.StringIO()
    assert L.cmd_status(run_dir, out=buf) == 1
    assert "DOWN" in buf.getvalue()


def test_status_down_when_pid_alive_but_port_dead(run_dir, started):
    rec = started(fake_tcp(free_port()))
    assert wait_up(rec)
    rec = dict(rec, port=free_port())  # nothing listens there
    assert L.evaluate(rec)[0] == "DOWN"


def test_status_with_no_pidfile_is_nonzero(run_dir):
    buf = io.StringIO()
    assert L.cmd_status(run_dir, out=buf) == 1 and "Nothing started" in buf.getvalue()


def test_failed_service_is_nonzero(run_dir):
    L.PidFile(run_dir).save({"services": {"shield": {"state": "failed", "port": 8787, "reason": "port 8787 busy"}}})
    buf = io.StringIO()
    assert L.cmd_status(run_dir, out=buf) == 1 and "FAILED" in buf.getvalue()


def test_http_5xx_is_not_healthy(run_dir):
    assert L.evaluate({"state": "running"})[0] == "DOWN"
    assert L.http_ok(free_port(), "/") is False


def test_web_note_when_market_not_running(run_dir):
    st = {"services": {"web": {"state": "running", "note": ""}, "market-stdb": {"state": "skipped"}}}
    L.web_note(st)
    assert "no live data" in st["services"]["web"]["note"]


def test_addresses_parsed_from_log(tmp_path):
    p = tmp_path / "x.log"
    a, b = "agent1q" + "b" * 58, "agent1q" + "c" * 58
    p.write_text(f"seller_2 address: {a}\nINFO Starting agent with address: {b}\n")
    assert L.addresses_from_log(str(p), "advocate") == [f"seller_2: {a}", f"advocate: {b}"]


def test_log_marker_warning_surfaces_in_status(run_dir, started):
    rec = started(fake_tcp(free_port()))
    assert wait_up(rec)
    with open(rec["log"], "a") as f:
        f.write("WARNING: [x]: Unable to publish manifest: Cannot connect to host agentverse.ai:443\n")
    L.PidFile(run_dir).save({"services": {"fake-agent": rec}})
    buf = io.StringIO()
    assert L.cmd_status(run_dir, out=buf) == 0
    assert "WARNING Agentverse not reachable" in buf.getvalue()


def test_find_tool_falls_back_to_home_bin(tmp_path):
    (tmp_path / "spacetime").write_text("#!/bin/sh\n")
    assert L.find_tool("spacetime", lambda n: None, tmp_path) == str(tmp_path / "spacetime")
    assert L.find_tool("spacetime", lambda n: "/usr/bin/spacetime", tmp_path) == "/usr/bin/spacetime"
    assert L.find_tool("spacetime", lambda n: None, tmp_path / "empty") is None


def test_spacetime_found_in_home_bin_means_market_not_skipped(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "spacetime").write_text("")
    svcs, checks = preflight(tmp_path, which=lambda n: None if n == "spacetime" else "/bin/x", home_bin=tmp_path / "bin")
    L.decide_skips(svcs, checks)
    assert {s.name: s for s in svcs}["market-stdb"].skip_reason is None
    assert any(c.name == "spacetime CLI" and c.ok for c in checks)


def test_static_setup_warning_surfaces_in_status(run_dir, started):
    rec = started(fake_tcp(free_port()))
    assert wait_up(rec)
    rec["static_warnings"] = ["module tech-bazaar is not published (the market has no tables)"]
    L.PidFile(run_dir).save({"services": {"fake-agent": rec}})
    buf = io.StringIO()
    L.cmd_status(run_dir, out=buf)
    assert "WARNING module tech-bazaar is not published" in buf.getvalue()


def test_up_only_keeps_records_of_other_live_services():
    live = {"buyer": {"pid": 123, "lstart": "x", "state": "running"}}
    state = L.carry_live({"services": {}}, live)
    assert state["services"]["buyer"]["pid"] == 123


def test_pid_without_start_marker_is_not_ours():
    assert L.pid_is_ours({"pid": os.getpid(), "lstart": None}) is False


def test_process_marker_round_trips_for_owned_child(started):
    rec = started(fake_tcp(free_port()))
    assert rec["lstart"]
    assert L.pid_is_ours(rec)
    assert L.proc_start_marker(0xFFFFFFFF) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows direct-process fallback")
def test_windows_timeout_terminates_only_verified_direct_process(started):
    port = free_port()
    code = ("import signal,socket,time;signal.signal(signal.SIGBREAK,signal.SIG_IGN);"
            f"s=socket.socket();s.bind(('127.0.0.1',{port}));s.listen();time.sleep(600)")
    rec = started(L.Service("stubborn", port, [sys.executable, "-c", code], Path.cwd(), health="tcp"))
    assert wait_up(rec)
    assert "verified process" in L.stop_record(rec, grace=0.1)
    assert not L.pid_is_ours(rec)


def test_web_starts_next_directly_without_npm_wrapper(tmp_path):
    web = next(s for s in L.build_services(make_args(), tmp_path) if s.name == "web")
    assert "next" in web.cmd[1].lower()
    assert "npm" not in web.cmd[0].lower()


def test_mailbox_flag_sets_agent_env_only_when_asked(tmp_path):
    base = dict(shield_port=8787, stdb_port=3000, web_port=3100)
    off = {s.name: s for s in L.build_services(Namespace(**base, mailbox=False), tmp_path)}
    on = {s.name: s for s in L.build_services(Namespace(**base, mailbox=True), tmp_path)}
    assert "BUYER_MAILBOX" not in off["buyer"].extra_env
    assert on["buyer"].extra_env["BUYER_MAILBOX"] == "1"
    assert on["advocate"].extra_env["ADVOCATE_MAILBOX"] == "1"
    assert on["sellers"].extra_env["SELLERS_MAILBOX"] == "1"


def test_windows_interpreter_path_uses_scripts_python(tmp_path):
    assert L.venv_python(tmp_path, platform="nt") == tmp_path / "agents" / ".venv" / "Scripts" / "python.exe"
    assert L.venv_python(tmp_path, platform="posix") == tmp_path / "agents" / ".venv" / "bin" / "python"
