"""#449 RT-2: pairing codes are made off-module with `secrets` and issued by the owner; the module stores only their hash."""
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "market" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue_pair_code  # noqa: E402
import stdb  # noqa: E402

SHAPE = re.compile(r"[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}")


def test_new_pair_code_is_ten_crockford_characters_grouped_and_never_repeats():
    codes = {stdb.new_pair_code() for _ in range(300)}
    assert len(codes) == 300
    assert all(SHAPE.fullmatch(c) for c in codes)
    assert not any(ch in c for c in codes for ch in "ILOU")


def test_new_pair_code_comes_from_the_secrets_module(monkeypatch):
    calls = []
    monkeypatch.setattr(secrets, "choice", lambda seq: calls.append(1) or seq[0])
    assert stdb.new_pair_code() == "00000-00000" and len(calls) == 10


def fake_run(rc=0, err=""):
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=err.replace("{code}", cmd[-1].strip('"')))
    run.seen = seen
    return run


def test_issue_calls_reissue_pair_code_as_the_owner_with_the_code_and_prints_it_once_to_the_operator(capsys):
    run = fake_run()
    assert issue_pair_code.main(["vidyut"], run=run, server="local", db="tech-bazaar") == 0
    cmd = run.seen[0]
    assert cmd[:6] == ["spacetime", "call", "-s", "local", "tech-bazaar", "reissue_pair_code"] and cmd[6] == '"vidyut"'
    code = cmd[7].strip('"')
    assert SHAPE.fullmatch(code)
    assert capsys.readouterr().out.count(code) == 1


def test_a_seller_screen_code_goes_to_its_own_reducer(capsys):
    run = fake_run()
    assert issue_pair_code.main(["--seller", "seller-a"], run=run, server="maincloud", db="tech-bazaar") == 0
    assert run.seen[0][3:7] == ["maincloud", "tech-bazaar", "reissue_seller_screen_code", '"seller-a"']


def test_a_failed_call_prints_no_code_and_hides_it_from_the_error(capsys):
    run = fake_run(rc=1, err="Error: invalid argument {code}")
    assert issue_pair_code.main(["vidyut"], run=run, server="local", db="tech-bazaar") == 1
    out = capsys.readouterr()
    code = run.seen[0][7].strip('"')
    assert code not in out.out and code not in out.err
    assert "[code]" in out.err


def test_a_missing_spacetime_cli_is_a_clear_refusal_not_a_traceback(capsys):
    def run(cmd, **kw):
        raise FileNotFoundError("spacetime")
    assert issue_pair_code.main(["vidyut"], run=run, server="local", db="tech-bazaar") == 1
    assert "spacetime" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--help"], ["-h"], ["--sellr", "seller-a"], ["vidyut", "extra"], ["--seller", "-x"]])
def test_an_unknown_flag_or_extra_argument_issues_nothing(argv, capsys):
    run = fake_run()
    assert issue_pair_code.main(argv, run=run, server="local", db="tech-bazaar") == 2
    assert run.seen == [] and "Usage" in capsys.readouterr().err


def test_launch_up_tells_the_operator_how_to_get_the_pair_code():
    """seed_demo makes no code any more, so `launch.py up` must say how to get one (it must not write the code to a run log)."""
    src = (Path(__file__).resolve().parents[2] / "scripts" / "launch.py").read_text()
    assert "market/scripts/issue_pair_code.py" in src
    steps = src.split("steps = [")[1].split("warns = []")[0]
    assert "setup_roles" in steps
    assert "issue_pair_code" not in steps                                          # a run_step writes its output to a log file
