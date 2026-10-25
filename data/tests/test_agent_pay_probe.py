"""The free agent pay probe (#262, #270 Tier A, #276) parses Apify's real 402 challenges and never sends a payment."""
import base64
import json
from pathlib import Path

from data.claim_check import agent_pay_probe as probe_mod

HERE = Path(__file__).resolve().parents[1] / "claim_check"
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
    send, _ = fake_agi()
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
    saved = json.loads((HERE / "agent_pay_probe.json").read_text())
    assert saved["paid"] is False and saved["all_pay_walls_reached"] and saved["label"].startswith("reached, not paid")
    assert "HTTP 402, pay wall reached" in (HERE / "agent_pay_probe.txt").read_text()


def test_the_readme_names_only_files_that_exist():  # #276
    readme = (HERE / "actor" / "README.md").read_text()
    root = HERE.parents[1]
    import re
    for path in re.findall(r"blob/main/([\w./-]+)", readme):
        assert (root / path).exists(), path
