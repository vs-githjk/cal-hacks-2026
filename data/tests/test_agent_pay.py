"""Agent pays Apify (#270 Tier B): the paid script runs end to end on fakes only; nothing here can spend money."""
import argparse
import json
import os
import stat
from pathlib import Path

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
    assert "token" not in r and "1234" not in (tmp_path / "agent_pay_run.json").read_text()  # #347: not even the last 4


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
    assert rec["label"] == "NOT LIVE: paid, but the run request failed (URLError)" and "token" not in rec
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
    for step in ("Anoop", "npx awal auth login", "npx awal auth verify", "npx awal show", "npx awal balance",
                 "USDC on Base", "python3 -m data.claim_check.agent_pay_probe", "type PAY",
                 "python3 -m data.claim_check.agent_pay --payer awal --amount 5", "--max-amount 5000000",
                 "https://basescan.org/tx/", "screen-record (30 s)", "What to commit", "Never commit .env",
                 "Agents can pay per call", "labelled LIVE", "Post on issue #347", "tx hash not captured",
                 "python3 -m data.claim_check.agent_pay --token-from-env", "npm i -g mppx", "mppx account create",
                 "data/claim_check/agent_pay_run.json", "$1 to $10", "mode 600", "BEFORE", "AFTER"):
        assert step in text, step
    steps = [text.index(f"\n{n}. ") for n in range(1, 11)]  # ten numbered steps, in order
    assert steps == sorted(steps)
    labels = {  # each receipt label the code can write, and the next action the runbook gives for it
        "LIVE\n": "go to step 8",
        "LIVE (payment unverified by balance)": "do not pay again",
        "NOT LIVE: paid, but the Actor run did not succeed": "--token-from-env",
        "NOT LIVE: paid, but the run request failed": "check the Apify console",
        "NOT LIVE: paid, but .env could not be written (token in a fallback file)": "--token-from-env",
        "NOT LIVE: paid, but the token could not be saved anywhere": "copy it now from the payer output above",
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


TX = "0x" + "ab12" * 16
NONCE = "0x" + "cd34" * 16
WALLET_KEY = "0x" + "ef56" * 16


@pytest.mark.parametrize("output", [
    json.dumps({"token": TOKEN, "remainingBalanceUsd": 5, "txHash": TX}),
    json.dumps({"token": TOKEN, "payment": {"success": True, "transaction": TX, "network": "eip155:8453"}}),
    json.dumps({"token": TOKEN, "transactionHash": TX}),
    '{\n "token": "%s",\n "settlement": {"transaction": "%s"}\n}' % (TOKEN, TX),
    f"Paid. Transaction: {TX}\n" + json.dumps({"token": TOKEN}),
    f"see https://basescan.org/tx/{TX}\n" + json.dumps({"token": TOKEN}),
])
def test_the_tx_hash_is_read_from_awal_json_or_text(output):
    assert pay_mod.tx_from_output(output) == TX


@pytest.mark.parametrize("output", [
    json.dumps({"token": TOKEN, "authorization": {"nonce": NONCE}}),
    f"nonce {NONCE}\n" + json.dumps({"token": TOKEN}),
    f"private key hash {WALLET_KEY}",
    json.dumps({"token": TOKEN, "transaction": "0xabc"}),
    "",
])
def test_a_nonce_a_key_or_a_short_hex_is_never_taken_for_a_tx_hash(output):
    assert pay_mod.tx_from_output(output) is None


def test_a_paid_run_records_the_tx_hash_and_a_basescan_link(tmp_path):
    send, _ = fake_apify()
    out = json.dumps({"token": TOKEN, "remainingBalanceUsd": 5, "txHash": TX})
    r, printed = run_paid(tmp_path, send, sh=lambda cmd: (0, out))
    rec = receipt_of(tmp_path)
    assert rec["tx_hash"] == TX and rec["tx_explorer"] == f"https://basescan.org/tx/{TX}"
    assert any(TX in p and "https://basescan.org/tx/" in p for p in printed)
    assert rec["label"] == r["label"] == "FAKE (test)"


def test_no_tx_hash_says_copy_it_from_the_wallet_history_and_keeps_the_label_rules(tmp_path):
    send, _ = fake_apify()
    r, printed = run_paid(tmp_path, send, live=True)
    rec = receipt_of(tmp_path)
    assert rec["tx_hash"] == "tx hash not captured: copy it from the wallet history" and "tx_explorer" not in rec
    assert rec["label"] == "LIVE" and any("tx hash not captured" in p for p in printed)


def test_mppx_gets_no_basescan_link(tmp_path):
    send, _ = fake_apify()
    run_paid(tmp_path, send, sh=lambda cmd: (0, json.dumps({"token": TOKEN, "txHash": TX})), payer="mppx")
    rec = receipt_of(tmp_path)
    assert rec["tx_hash"] == TX and "tx_explorer" not in rec


@pytest.mark.parametrize("case", ["ok", "no_token", "run_error"])
def test_the_receipt_holds_no_token_key_or_env_value(tmp_path, monkeypatch, case):
    """#347: the receipt is committed, so it must hold amounts, run id, tx hash and timestamps, never a secret."""
    import urllib.error
    env_secret = "sk_test_ENVSECRETVALUE9876"
    monkeypatch.setenv("AGENT_WALLET_KEY", WALLET_KEY)
    monkeypatch.setenv("SOME_API_TOKEN", "envtoken_ABCDEFGH1234")
    (tmp_path / ".env").write_text(f"STRIPE_SECRET_KEY={env_secret}\nAGENT_WALLET_KEY={WALLET_KEY}\n")
    noisy = (f"debug key={WALLET_KEY} nonce={NONCE} sig=0x{'9f' * 65}\n"
             + json.dumps({"txHash": TX, **({} if case == "no_token" else {"token": TOKEN})}))
    send0, _ = fake_apify()

    def send(method, url, token=None, body=None, timeout=150):
        if case == "run_error" and "/runs?" in url:
            raise urllib.error.URLError("reset")
        return send0(method, url, token, body, timeout)
    try:
        run_paid(tmp_path, send, sh=lambda cmd: (1 if case == "no_token" else 0, noisy), live=True)
    except SystemExit:
        pass
    text = (tmp_path / "agent_pay_run.json").read_text()
    for secret in (TOKEN, TOKEN[-12:], "apify_api_", WALLET_KEY, WALLET_KEY[2:], NONCE[2:], "9f" * 40,
                   env_secret, "envtoken_ABCDEFGH1234"):
        assert secret not in text, secret
    assert json.loads(text)["tx_hash"] == TX


# #354: a minted token is never lost when .env cannot be written. As root a chmod 0400 file is still writable, so
# there the read-only case is simulated by making os.open refuse .env, which keeps the test real on CI and locally.
def _refuse(monkeypatch, refuse):
    real_open = pay_mod.os.open

    def fake_open(path, flags, *a, **kw):
        err = refuse(Path(path))
        if err:
            raise err
        return real_open(path, flags, *a, **kw)
    monkeypatch.setattr(pay_mod.os, "open", fake_open)


def _make_env(tmp_path, monkeypatch, how):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # a fallback never lands in the real home
    (tmp_path / "home").mkdir()
    env = tmp_path / ".env"
    if how == "read_only":
        env.write_text("OTHER=1\n")
        env.chmod(0o400)
        if os.geteuid() == 0:
            _refuse(monkeypatch, lambda p: PermissionError(13, "Permission denied") if p == env else None)
    elif how == "directory":
        env.mkdir()
    elif how == "not_utf8":
        env.write_bytes(b"OTHER=\xff\xfe\n")
    return env


def _fallbacks(tmp_path):
    return sorted(tmp_path.glob(pay_mod.FALLBACK_PREFIX + "*")) + sorted((tmp_path / "home").glob(pay_mod.FALLBACK_PREFIX + "*"))


@pytest.mark.parametrize("how", ["read_only", "directory", "not_utf8"])
def test_a_token_that_cannot_go_in_env_goes_to_a_600_fallback_file_with_a_not_live_receipt(tmp_path, monkeypatch, how):
    _make_env(tmp_path, monkeypatch, how)
    send, calls = fake_apify()
    printed = []
    with pytest.raises(SystemExit, match="Do not pay again"):
        pay_mod.run(args(), send=send, sh=lambda cmd: (0, json.dumps({"token": TOKEN, "txHash": TX})), ask=lambda p: "PAY",
                    sleep=lambda s: None, out=printed.append, env_file=tmp_path / ".env",
                    receipt_file=tmp_path / "agent_pay_run.json", live=True)
    files = _fallbacks(tmp_path)
    assert len(files) == 1 and files[0].parent == tmp_path and files[0].read_text() == f"APIFY_AGENT_TOKEN={TOKEN}\n"
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    rec = receipt_of(tmp_path)
    assert rec["label"] == pay_mod.ENV_NOT_WRITTEN and rec["token_file"] == str(files[0]) and rec["tx_hash"] == TX
    raw = (tmp_path / "agent_pay_run.json").read_text()
    assert TOKEN not in raw and "1234" not in raw and str(files[0]) in rec["error"]
    assert TOKEN not in "\n".join(printed) and any(str(files[0]) in p for p in printed)
    assert calls == []  # it stops before the run; the rerun uses --token-from-env
    import subprocess
    ignored = subprocess.run(["git", "check-ignore", "-q", str(pay_mod.ROOT / files[0].name)], cwd=pay_mod.ROOT)
    assert ignored.returncode == 0, "the fallback file name must be gitignored"


def test_when_the_fallback_also_fails_it_prints_the_last_4_and_still_writes_the_receipt(tmp_path, monkeypatch):
    _make_env(tmp_path, monkeypatch, "directory")
    _refuse(monkeypatch, lambda p: OSError(28, "No space left on device") if p.name.startswith(pay_mod.FALLBACK_PREFIX) else None)
    send, calls = fake_apify()
    printed = []
    with pytest.raises(SystemExit, match="Do not pay again"):
        pay_mod.run(args(), send=send, sh=lambda cmd: (0, json.dumps({"token": TOKEN})), ask=lambda p: "PAY",
                    sleep=lambda s: None, out=printed.append, env_file=tmp_path / ".env",
                    receipt_file=tmp_path / "agent_pay_run.json", live=True)
    assert _fallbacks(tmp_path) == []
    rec = receipt_of(tmp_path)
    assert rec["label"] == pay_mod.TOKEN_NOT_SAVED and "--token-from-env" in rec["error"]
    raw = (tmp_path / "agent_pay_run.json").read_text()
    assert TOKEN not in raw and "1234" not in raw
    text = "\n".join(printed)
    assert TOKEN not in text and "ends in 1234" in text and "Copy it now from the payer output above" in text
    assert calls == []


def test_a_payer_timeout_whose_token_cannot_go_in_env_still_keeps_it(tmp_path, monkeypatch):
    import subprocess
    _make_env(tmp_path, monkeypatch, "directory")

    def sh(cmd):
        raise subprocess.TimeoutExpired(cmd, 300, output=json.dumps({"token": TOKEN}).encode())
    send, _ = fake_apify()
    with pytest.raises(SystemExit, match="timed out"):
        pay_mod.run(args(), send=send, sh=sh, ask=lambda p: "PAY", sleep=lambda s: None, out=lambda m: None,
                    env_file=tmp_path / ".env", receipt_file=tmp_path / "agent_pay_run.json", live=True)
    rec = receipt_of(tmp_path)
    files = _fallbacks(tmp_path)
    assert rec["label"] == pay_mod.ENV_NOT_WRITTEN and rec["token_file"] == str(files[0]) and TOKEN not in json.dumps(rec)
