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
    return argparse.Namespace(**{"payer": "awal", "amount": 5.0, "token_from_env": False, "yes": False, **kw})


def run_paid(tmp_path, send, sh=None, answer="PAY", **kw):
    printed = []
    r = pay_mod.run(args(**kw), send=send, sh=sh or (lambda cmd: (0, json.dumps({"token": TOKEN, "remainingBalanceUsd": 5}))),
                    ask=lambda prompt: answer, sleep=lambda s: None, out=printed.append,
                    env_file=tmp_path / ".env", receipt_file=tmp_path / "agent_pay_run.json", live=False)
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
