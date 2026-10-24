"""Agent pays Apify (#270 Tier B): the paid script runs end to end on fakes only; nothing here can spend money."""
import argparse
import json
import stat

import pytest

from data.claim_check import agent_pay as pay_mod  # the free probe and its tests ship with #239


TOKEN = "apify_api_FAKEFAKEFAKE1234"


def fake_apify(before=5.0, after=4.99, run_status="SUCCEEDED"):
    calls, bal = [], iter([before, after, after])

    def send(method, url, token=None, body=None, timeout=150):
        calls.append((method, url, token, body))
        if url.endswith("/prepaid-tokens/balance"):
            return 200, {"remainingBalanceUsd": next(bal), "expiresAt": "2026-11-07T00:00:00Z"}
        if "/runs?" in url:
            return 201, {"data": {"id": "RUNFAKE1", "status": run_status, "statusMessage": "3 claim(s): 2 verified, 1 false, 0 unverified",
                                  "defaultDatasetId": "DSFAKE"}}
        if "/datasets/" in url:
            return 200, [{"id": "c1", "text": "new", "result": "verified", "reason": "the page shows new"}]
        return 404, None
    return send, calls


def args(**kw):
    return argparse.Namespace(**{"payer": "awal", "amount": 5.0, "token_from_env": False, **kw})


def run_paid(tmp_path, send, sh=None, answer="PAY", live=False, **kw):
    printed = []
    r = pay_mod.run(args(**kw), send=send, sh=sh or (lambda cmd: (0, json.dumps({"token": TOKEN, "remainingBalanceUsd": 5}))),
                    ask=lambda prompt: answer, sleep=lambda s: None, out=printed.append,
                    env_file=tmp_path / ".env", receipt_file=tmp_path / "agent_pay_run.json", live=live)
    return r, printed


def test_a_paid_run_buys_saves_runs_and_reports_balance_before_and_after(tmp_path):
    send, calls = fake_apify()
    r, printed = run_paid(tmp_path, send)
    assert r["run_id"] == "RUNFAKE1" and r["balance_before_usd"] == 5.0 and r["balance_after_usd"] == 4.99 and r["spent_usd"] == 0.01
    assert r["label"] == "FAKE (test)" and r["results"][0]["result"] == "verified"
    env = tmp_path / ".env"
    assert f"APIFY_AGENT_TOKEN={TOKEN}" in env.read_text() and stat.S_IMODE(env.stat().st_mode) == 0o600
    run_call = next(c for c in calls if "/runs?" in c[1])
    assert run_call[2] == TOKEN and run_call[3] == pay_mod.DEMO_INPUT and "tech-bazaar-claim-check" in run_call[1]
    assert json.loads((tmp_path / "agent_pay_run.json").read_text())["run_id"] == "RUNFAKE1"


def test_the_token_is_never_printed_or_written_to_the_receipt(tmp_path):
    send, _ = fake_apify()
    r, printed = run_paid(tmp_path, send)
    assert TOKEN not in "\n".join(printed) and TOKEN not in (tmp_path / "agent_pay_run.json").read_text()
    assert r["token"] == "apify_api_...1234"


def test_nothing_is_paid_without_typing_pay(tmp_path):
    send, calls = fake_apify()
    paid = []
    with pytest.raises(SystemExit, match="Not paid"):
        run_paid(tmp_path, send, sh=lambda cmd: paid.append(cmd) or (0, ""), answer="yes")
    assert paid == [] and calls == [] and not (tmp_path / ".env").exists()


@pytest.mark.parametrize("amount", [0.5, 11, 100])
def test_the_amount_is_capped_at_the_approved_range(tmp_path, amount):
    send, _ = fake_apify()
    with pytest.raises(SystemExit, match="between 1 and 10"):
        run_paid(tmp_path, send, amount=amount)


def test_a_payer_that_returns_no_token_saves_nothing(tmp_path):
    send, calls = fake_apify()
    with pytest.raises(SystemExit, match="did not return a token"):
        run_paid(tmp_path, send, sh=lambda cmd: (1, "insufficient funds"))
    assert calls == [] and not (tmp_path / ".env").exists()


def test_payer_commands_cap_the_spend_and_hit_the_right_protocol():
    url = "https://agi.apify.com/protocols/x402/prepaid-tokens?amount=5&currency=usd"
    assert pay_mod.PAYERS["awal"][1](url, 5) == ["npx", "awal", "x402", "pay", url, "--max-amount", "5000000"]
    assert pay_mod.PAYERS["pay.sh"][1](url, 5)[:3] == ["pay", "--mainnet", "--x402"]


def test_mppx_buys_from_the_mpp_endpoint(tmp_path):
    send, _ = fake_apify()
    seen = []
    run_paid(tmp_path, send, sh=lambda cmd: seen.append(cmd) or (0, json.dumps({"token": TOKEN})), payer="mppx")
    assert seen[0][0] == "mppx" and "/protocols/mpp/prepaid-tokens?amount=5&currency=usd" in seen[0][1]


def test_a_rerun_uses_the_saved_token_without_paying(tmp_path, monkeypatch):
    monkeypatch.delenv("APIFY_AGENT_TOKEN", raising=False)
    (tmp_path / ".env").write_text(f"APIFY_TOKEN=x\nAPIFY_AGENT_TOKEN={TOKEN}\n")
    send, calls = fake_apify()
    r, _ = run_paid(tmp_path, send, sh=lambda cmd: pytest.fail("must not pay"), token_from_env=True)
    assert r["run_id"] == "RUNFAKE1" and r["paid_via"] == "prepaid token bought earlier"


def test_a_token_is_read_from_the_payer_json_or_text():
    assert pay_mod.token_from_output('noise\n{"token": "apify_api_abc123", "remainingBalanceUsd": 5}\n') == "apify_api_abc123"
    assert pay_mod.token_from_output("minted apify_api_xyz789 ok") == "apify_api_xyz789"
    assert pay_mod.token_from_output("no token here") is None


@pytest.mark.parametrize("flag", ["--yes", "-y", "--no-confirm", "--force"])
def test_no_flag_skips_the_pay_prompt(flag):
    with pytest.raises(SystemExit):
        pay_mod.main([flag, "--amount", "5"])  # argparse rejects it before anything runs


def test_the_prompt_is_asked_even_if_a_caller_sets_yes(tmp_path):
    send, calls = fake_apify()
    with pytest.raises(SystemExit, match="Not paid"):
        run_paid(tmp_path, send, answer="", yes=True)
    assert calls == []


def test_a_failed_run_is_never_labelled_live(tmp_path):
    send, _ = fake_apify(run_status="FAILED")
    r, _ = run_paid(tmp_path, send, live=True)
    assert r["label"] != "LIVE" and r["label"].startswith("NOT LIVE") and "FAILED" in r["label"]


def test_a_rerun_with_a_saved_token_is_never_labelled_live(tmp_path, monkeypatch):
    monkeypatch.delenv("APIFY_AGENT_TOKEN", raising=False)
    (tmp_path / ".env").write_text(f"APIFY_AGENT_TOKEN={TOKEN}\n")
    send, _ = fake_apify()
    r, _ = run_paid(tmp_path, send, live=True, token_from_env=True)
    assert r["label"] != "LIVE" and "no payment in this run" in r["label"]


def test_only_a_paid_succeeded_run_is_live(tmp_path):
    send, _ = fake_apify()
    r, _ = run_paid(tmp_path, send, live=True)
    assert r["label"] == "LIVE"
    assert json.loads((tmp_path / "agent_pay_run.json").read_text())["label"] == "LIVE"


# #329: once money may have been spent, the token is never lost and a receipt is always written (never LIVE)
def receipt_of(tmp_path):
    return json.loads((tmp_path / "agent_pay_run.json").read_text())


def test_a_token_on_a_non_zero_payer_exit_is_saved_with_a_warning(tmp_path):
    send, calls = fake_apify()
    r, printed = run_paid(tmp_path, send, sh=lambda cmd: (1, json.dumps({"token": TOKEN})), live=True)
    assert f"APIFY_AGENT_TOKEN={TOKEN}" in (tmp_path / ".env").read_text()
    assert any(p.startswith("Warning: the payer CLI exited 1") for p in printed) and TOKEN not in "\n".join(printed)
    assert r["payer_exit"] == 1 and r["run_id"] == "RUNFAKE1" and any("/runs?" in c[1] for c in calls)


def test_no_token_writes_a_maybe_paid_receipt_and_shows_a_masked_tail(tmp_path):
    send, calls = fake_apify()
    printed = []
    with pytest.raises(SystemExit, match="did not return a token"):
        pay_mod.run(args(), send=send, sh=lambda cmd: (1, "paid tx 0xabc then crashed"), ask=lambda p: "PAY",
                    sleep=lambda s: None, out=printed.append, env_file=tmp_path / ".env",
                    receipt_file=tmp_path / "agent_pay_run.json", live=True)
    rec = receipt_of(tmp_path)
    assert rec["label"].startswith("NOT LIVE") and "may have happened" in rec["label"] and rec["payer_exit"] == 1
    assert "check the wallet and .env" in rec["error"] and "paid tx 0xabc then crashed" in "\n".join(printed)
    assert calls == [] and not (tmp_path / ".env").exists()


def test_the_masked_tail_never_shows_a_token():
    assert pay_mod.masked_tail("x apify_api_SECRETABCD y") == "x apify_api_...ABCD y"
    assert pay_mod.masked_tail(b"") == "(no output)"


@pytest.mark.parametrize("partial", [None, json.dumps({"token": TOKEN}).encode()])
def test_a_payer_timeout_writes_a_not_live_receipt_and_keeps_any_token(tmp_path, partial):
    import subprocess

    def sh(cmd):
        raise subprocess.TimeoutExpired(cmd, 300, output=partial)
    send, calls = fake_apify()
    printed = []
    with pytest.raises(SystemExit, match="Payment may have happened"):
        pay_mod.run(args(), send=send, sh=sh, ask=lambda p: "PAY", sleep=lambda s: None, out=printed.append,
                    env_file=tmp_path / ".env", receipt_file=tmp_path / "agent_pay_run.json", live=True)
    rec = receipt_of(tmp_path)
    assert rec["label"].startswith("NOT LIVE") and "timed out" in rec["label"] and calls == []
    assert TOKEN not in "\n".join(printed) and TOKEN not in json.dumps(rec)
    env = tmp_path / ".env"
    assert (f"APIFY_AGENT_TOKEN={TOKEN}" in env.read_text()) if partial else not env.exists()


def test_a_url_error_on_the_run_after_paying_writes_a_not_live_receipt(tmp_path):
    import urllib.error
    send0, _ = fake_apify()

    def send(method, url, token=None, body=None, timeout=150):
        if "/runs?" in url:
            raise urllib.error.URLError("timed out")
        return send0(method, url, token, body, timeout)
    with pytest.raises(SystemExit, match="check the wallet and .env"):
        run_paid(tmp_path, send, live=True)
    rec = receipt_of(tmp_path)
    assert rec["label"] == "NOT LIVE: paid, but the run request failed (URLError)" and rec["token"] == "apify_api_...1234"
    assert f"APIFY_AGENT_TOKEN={TOKEN}" in (tmp_path / ".env").read_text()


def test_a_balance_read_error_does_not_lose_the_receipt(tmp_path):
    send0, _ = fake_apify()

    def send(method, url, token=None, body=None, timeout=150):
        if url.endswith("/balance"):
            raise TimeoutError("read timed out")
        return send0(method, url, token, body, timeout)
    r, _ = run_paid(tmp_path, send, live=True)
    assert r["label"] == "LIVE (payment unverified by balance)" and receipt_of(tmp_path)["label"] == r["label"]


def test_live_says_unverified_when_the_balance_is_unknown(tmp_path):
    send0, _ = fake_apify()

    def send(method, url, token=None, body=None, timeout=150):
        return (500, None) if url.endswith("/balance") else send0(method, url, token, body, timeout)
    r, _ = run_paid(tmp_path, send, live=True)
    assert r["balance_before_usd"] is None and r["label"] == "LIVE (payment unverified by balance)"


def test_the_env_file_is_never_world_readable_even_for_a_moment(tmp_path, monkeypatch):
    monkeypatch.setattr(pay_mod.os, "chmod", lambda *a, **k: None)  # the mode must come from the create, not a later chmod
    env = tmp_path / ".env"
    pay_mod.save_token(env, TOKEN)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    env.chmod(0o644)
    pay_mod.save_token(env, TOKEN)  # an existing, wider .env is tightened too
    assert stat.S_IMODE(env.stat().st_mode) == 0o600 and env.read_text().count("APIFY_AGENT_TOKEN=") == 1


def test_help_is_the_paid_run_runbook_and_spends_nothing(capsys, monkeypatch):
    """#342: --help is the 18:30 runbook. It names every step and every receipt label with its next action,
    and it exits before any network call, payer CLI or prompt."""
    def boom(*a, **kw):
        raise AssertionError("--help must not touch the network, a payer CLI or the prompt")
    monkeypatch.setattr(pay_mod, "http", boom)
    monkeypatch.setattr(pay_mod, "shell", boom)
    monkeypatch.setattr(pay_mod, "run", boom)
    monkeypatch.setattr("builtins.input", boom)
    with pytest.raises(SystemExit) as e:
        pay_mod.main(["--help"])
    assert e.value.code == 0
    text = capsys.readouterr().out
    for step in ("type PAY", "python3 -m data.claim_check.agent_pay_probe",
                 "python3 -m data.claim_check.agent_pay --payer awal --amount 5",
                 "python3 -m data.claim_check.agent_pay --payer mppx --amount 5",
                 "python3 -m data.claim_check.agent_pay --token-from-env",
                 "npx awal auth login", "npx awal balance", "npm i -g mppx", "mppx account create", "mppx account view",
                 "data/claim_check/agent_pay_run.json", "$1 to $10", "mode 600", "BEFORE", "AFTER"):
        assert step in text, step
    labels = {  # each receipt label the code can write, and the next action the runbook gives for it
        "LIVE\n": "share the run id",
        "LIVE (payment unverified by balance)": "do not pay again",
        "NOT LIVE: paid, but the Actor run did not succeed": "--token-from-env",
        "NOT LIVE: paid, but the run request failed": "check the Apify console",
        "NOT LIVE: payment may have happened, no token returned": "check the wallet and .env",
        "NOT LIVE: payment may have happened, the payer CLI timed out": "check the wallet and .env",
        "NOT LIVE: payment may have happened, the payer CLI failed": "check the wallet and .env",
        "NOT LIVE: no payment in this run (saved token)": "never LIVE",
        "NOT LIVE: no payment in this run, and the run request failed": "never LIVE",
        "FAKE (test)": "never from a real run",
    }
    for label, action in labels.items():
        assert label in text, label
        assert action in text[text.index(label):], (label, action)
    assert pay_mod.MAYBE_PAID.rstrip(".").lower() in text.lower()
    assert "–" not in text and "—" not in text


def test_every_not_live_label_the_code_writes_is_in_the_help():
    import inspect
    import re
    found = re.findall(r'"(NOT LIVE: [^"({]+)', inspect.getsource(pay_mod))
    assert len(found) >= 6
    for label in found:
        assert label.strip().rstrip(",") in pay_mod.__doc__, label
