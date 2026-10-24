"""Agent pays Apify (#262, #270): the free probe parses real 402 challenges, and the paid script runs end to end on fakes only."""
import argparse
import base64
import importlib.util
import json
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe_mod, pay_mod = load("apify_agent_pay_probe"), load("apify_agent_pay")

# shapes taken from agi.apify.com's real 402 answers on Oct 24 2026 (data/claim_check/agent_pay_probe.json)
X402 = {"x402Version": 2, "accepts": [{"scheme": "exact", "network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "amount": "5000000"},
                                      {"scheme": "exact", "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "asset": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "amount": "5000000"}]}
MPP = {"challenges": [{"intent": "charge", "method": "tempo", "request": {"currency": "0x20c0000000000000000000000000000000000000", "amount": "5000000",
                                                                          "methodDetails": {"chainId": 4217, "supportedModes": ["push", "pull"]}}}]}
PROXY = {"x402Version": 2, "accepts": [{"scheme": "batch-settlement", "network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "amount": "1000000"}]}


def fake_agi(paywall=True):
    calls = []

    def send(method, url, body=None, timeout=20):
        calls.append((method, url, body))
        if url.endswith("/protocols"):
            return 200, {}, json.dumps({"protocols": [{"name": "x402"}, {"name": "mpp"}]}).encode()
        if not paywall:
            return 200, {}, b"{}"
        if "/x402/" in url:  # the body is empty here; the challenge only rides in the base64 header
            return 402, {"payment-required": base64.b64encode(json.dumps(X402).encode()).decode()}, b""
        if "/mpp/" in url:
            return 402, {}, json.dumps(MPP).encode()
        return 402, {}, json.dumps(PROXY).encode()
    return send, calls


def test_the_probe_reaches_every_pay_wall_and_names_the_offers():
    send, calls = fake_agi()
    r = probe_mod.probe(send=send)
    assert r["all_pay_walls_reached"] and r["paid"] is False and r["label"].startswith("reached, not paid")
    x402 = next(s for s in r["steps"] if s["step"] == "prepaid token via x402")["offers"]
    assert x402[0] == {"protocol": "x402", "scheme": "exact", "network": "Base", "asset": "USDC (Base)", "amount_usd": 5.0}
    assert x402[1]["asset"] == "USDT (Solana)" and x402[1]["network"] == "Solana mainnet"
    mpp = next(s for s in r["steps"] if s["step"] == "prepaid token via mpp")["offers"][0]
    assert mpp["network"] == "Tempo mainnet" and mpp["asset"] == "pathUSD (Tempo)" and mpp["modes"] == ["push", "pull"]
    proxied = [s for s in r["steps"] if s["step"].startswith("proxied run")]
    assert len(proxied) == 2 and all(s["offers"][0]["amount_usd"] == 1.0 for s in proxied)


def test_the_probe_never_sends_a_payment_or_credential():
    send, calls = fake_agi()
    probe_mod.probe(send=send)
    assert all("payment" not in repr(c).lower() and "token=" not in c[1] for c in calls)
    assert probe_mod.http.__code__.co_varnames[:4] == ("method", "url", "body", "timeout")  # no headers parameter to leak through


def test_no_pay_wall_is_reported_as_not_reached():
    send, _ = fake_agi(paywall=False)
    r = probe_mod.probe(send=send)
    assert not r["all_pay_walls_reached"] and "NOT reached" in probe_mod.report(r)


def test_the_committed_probe_output_is_the_real_free_run():
    saved = json.loads((ROOT / "data" / "claim_check" / "agent_pay_probe.json").read_text())
    assert saved["paid"] is False and saved["all_pay_walls_reached"] and saved["label"].startswith("reached, not paid")


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
