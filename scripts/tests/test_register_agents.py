"""scripts/register_agents.sh: one agents/connect.py <port> per agent, refuses without AGENTVERSE_API_KEY, never prints the key.
A fake connect.py stands in: no network, no real key."""
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
SCRIPT = SCRIPTS / "register_agents.sh"
KEY = "av-test-key-SUPERSECRET-123456"
PORTS = {"buyer": 8001, "advocate": 8003, "shield": 8004, "caller": 8006, "seller_1": 8011, "seller_3": 8013, "seller_5": 8015,
         "seller_6": 8016, "pulse": 8018}

FAKE = """import os, sys
log = os.environ["FAKE_LOG"]
port = sys.argv[1]
open(log, "a").write(port + " key=" + ("yes" if os.environ.get("AGENTVERSE_API_KEY") else "no") + "\\n")
mode = os.environ.get("FAKE_MODE", "ok")
if port in os.environ.get("FAKE_FAIL_PORTS", "").split(","):
    print("urllib.error.URLError: connection refused")
    sys.exit(1)
if mode == "echo_key":
    print('{"success": true, "detail": "' + os.environ["AGENTVERSE_API_KEY"] + '"}')
elif mode == "not_success":
    print('{"success": false, "detail": "no"}')
else:
    print('{"success": true, "detail": "connected"}')
"""


@pytest.fixture
def fake(tmp_path):
    connect = tmp_path / "connect.py"
    connect.write_text(FAKE)
    return connect, tmp_path / "calls.log"


def run(fake, *args, key=KEY, extra=None):
    connect, log = fake
    env = {"PATH": os.environ["PATH"], "REGISTER_PYTHON": sys.executable, "REGISTER_CONNECT": str(connect), "FAKE_LOG": str(log)}
    if key is not None:
        env["AGENTVERSE_API_KEY"] = key
    env.update(extra or {})
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)


def calls(fake):
    return fake[1].read_text().splitlines() if fake[1].exists() else []


def test_the_script_is_executable_and_uses_the_venv_python_by_default():
    assert SCRIPT.stat().st_mode & stat.S_IXUSR
    text = SCRIPT.read_text()
    assert "agents/.venv/bin/python" in text and "agents/connect.py" in text and text.startswith("#!/usr/bin/env bash")


def test_it_registers_all_nine_agents_one_port_each(fake):
    out = run(fake)
    assert out.returncode == 0, out.stderr
    assert [c.split()[0] for c in calls(fake)] == [str(p) for p in PORTS.values()]
    assert all(c.endswith("key=yes") for c in calls(fake))
    assert out.stdout.count("ok ") == 9 and "all registered" in out.stdout


def test_it_refuses_clearly_without_the_key_and_runs_nothing(fake):
    for key in (None, ""):
        out = run(fake, key=key)
        assert out.returncode == 2 and "AGENTVERSE_API_KEY is not set" in out.stderr and "nothing was registered" in out.stderr
        assert calls(fake) == []


def test_named_agents_only_and_an_unknown_name_is_refused_before_anything_runs(fake):
    out = run(fake, "caller", "pulse")
    assert out.returncode == 0 and [c.split()[0] for c in calls(fake)] == ["8006", "8018"]
    fake[1].unlink()
    bad = run(fake, "caller", "nobody")
    assert bad.returncode == 2 and "unknown agent 'nobody'" in bad.stderr and calls(fake) == []


def test_one_failing_agent_does_not_stop_the_rest_and_the_exit_code_says_so(fake):
    out = run(fake, extra={"FAKE_FAIL_PORTS": "8004,8013"})
    assert out.returncode == 1 and len(calls(fake)) == 9
    assert out.stdout.count("FAILED") == 2 and out.stdout.count("ok ") == 7 and "2 agent(s) not registered" in out.stderr


def test_a_reply_that_is_not_success_true_is_a_failure(fake):
    out = run(fake, "buyer", extra={"FAKE_MODE": "not_success"})
    assert out.returncode == 1 and "FAILED  buyer" in out.stdout


def test_the_key_is_never_printed_even_if_connect_echoes_it(fake):
    out = run(fake, "buyer", extra={"FAKE_MODE": "echo_key"})
    assert KEY not in out.stdout and KEY not in out.stderr and "[hidden]" in out.stdout
    refused = run(fake, key=None)
    assert KEY not in refused.stdout + refused.stderr


def test_list_prints_the_agents_and_ports_without_a_key_or_a_call(fake):
    out = run(fake, "--list", key=None)
    assert out.returncode == 0 and calls(fake) == []
    for name, port in PORTS.items():
        assert f"{name}" in out.stdout and str(port) in out.stdout


def test_a_missing_python_is_a_refusal_not_a_traceback(fake):
    out = run(fake, extra={"REGISTER_PYTHON": "/nonexistent/python"})
    assert out.returncode == 2 and "no python at" in out.stderr and calls(fake) == []


def test_the_ports_match_the_launcher_and_the_seller_ports_in_common():
    spec = importlib.util.spec_from_file_location("launch", SCRIPTS / "launch.py")
    L = importlib.util.module_from_spec(spec)
    sys.modules["launch"] = L
    spec.loader.exec_module(L)
    from argparse import Namespace
    svcs = {s.name: s.port for s in L.build_services(Namespace(shield_port=8787, stdb_port=3000, web_port=3100, mailbox=False))}
    assert (svcs["buyer"], svcs["advocate"], svcs["shield-agent"], svcs["caller"], svcs["pulse"]) == (
        PORTS["buyer"], PORTS["advocate"], PORTS["shield"], PORTS["caller"], PORTS["pulse"])
    common_text = (SCRIPTS.parent / "agents" / "common.py").read_text()
    for seller in ("seller_1", "seller_3", "seller_5", "seller_6"):
        assert f'"{seller}": {PORTS[seller]}' in common_text.replace("\n                ", " ")
