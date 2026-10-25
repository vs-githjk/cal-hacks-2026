"""All nine roster agents are runnable from the launcher: buyer, advocate, Shield client, Caller, Market Pulse and the four
sellers (one Bureau). Each has its own fixed port and, in mailbox mode, its own flag. No process is started here."""
import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("launch", SCRIPTS / "launch.py")
L = importlib.util.module_from_spec(_spec)
sys.modules["launch"] = L
_spec.loader.exec_module(L)

AGENT_SERVICES = {"buyer": 8001, "advocate": 8003, "shield-agent": 8004, "caller": 8006, "sellers": 8010, "pulse": 8018}


def services(tmp_path, **kw):
    args = dict(shield_port=8787, stdb_port=3000, web_port=3100, mailbox=False)
    args.update(kw)
    return {s.name: s for s in L.build_services(Namespace(**args), tmp_path)}


def test_every_agent_service_is_listed_with_its_own_fixed_port(tmp_path):
    svcs = services(tmp_path)
    assert {n: svcs[n].port for n in AGENT_SERVICES} == AGENT_SERVICES
    assert len({s.port for s in svcs.values() if s.port}) == len([s for s in svcs.values() if s.port])      # no shared port
    assert all(svcs[n].group == "agents" and svcs[n].health == "tcp" for n in AGENT_SERVICES)


def test_the_new_agents_start_the_right_programs_from_the_right_folder(tmp_path):
    svcs = services(tmp_path)
    py = str(L.venv_python(tmp_path))
    assert svcs["caller"].cmd == [py, "caller/caller_agent.py"] and svcs["caller"].cwd == tmp_path / "agents"
    assert svcs["shield-agent"].cmd == [py, "shield_client.py"] and svcs["shield-agent"].cwd == tmp_path / "agents"
    assert svcs["pulse"].cmd == [py, "-m", "agents.pulse.orchestrator", "--serve"] and svcs["pulse"].cwd == tmp_path


def test_the_agent_entry_points_exist_in_the_repo():
    repo = SCRIPTS.parent
    assert (repo / "agents" / "caller" / "caller_agent.py").is_file() and (repo / "agents" / "shield_client.py").is_file()
    assert (repo / "agents" / "pulse" / "orchestrator.py").is_file()


@pytest.mark.parametrize("name,flag", [("buyer", "BUYER_MAILBOX"), ("advocate", "ADVOCATE_MAILBOX"), ("sellers", "SELLERS_MAILBOX"),
                                       ("caller", "CALLER_MAILBOX"), ("pulse", "PULSE_MAILBOX"), ("shield-agent", "SHIELD_MAILBOX")])
def test_mailbox_mode_sets_each_agents_own_flag_and_only_then(tmp_path, name, flag):
    off, on = services(tmp_path, mailbox=False), services(tmp_path, mailbox=True)
    assert flag not in off[name].extra_env and on[name].extra_env[flag] == "1"
    assert L.mailbox_record(on[name]) is True and L.mailbox_record(off[name]) is False


def test_every_agent_gets_the_shield_url_so_it_fails_closed_on_the_real_shield(tmp_path):
    svcs = services(tmp_path, shield_port=8999)
    for name in AGENT_SERVICES:
        assert svcs[name].extra_env["SHIELD_URL"] == "http://127.0.0.1:8999", name


def test_the_sellers_note_does_not_claim_a_fixed_three(tmp_path):
    assert "3 seller agents" not in services(tmp_path)["sellers"].note


def test_the_help_lists_the_new_agent_names_and_ports():
    text = L.make_parser().format_help()
    for needle in ("caller", "pulse", "shield-agent", "8006", "8018", "8004"):
        assert needle in text, needle
