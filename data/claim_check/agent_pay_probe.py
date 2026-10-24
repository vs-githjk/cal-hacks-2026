"""Free probe: can an AI agent reach Apify's pay wall for our Actors? (Lane C, issues #262, #270 Tier A and #276.)

    python3 -m data.claim_check.agent_pay_probe                         # prints the result
    python3 -m data.claim_check.agent_pay_probe --out data/claim_check/agent_pay_probe.json

It sends only unpaid requests to agi.apify.com (Apify's Agent General Interface, https://agi.apify.com/AGENTS.md):
  1. GET /protocols, the protocols Apify accepts;
  2. GET /protocols/x402/prepaid-tokens and /protocols/mpp/prepaid-tokens, which answer HTTP 402 with the payment challenge
     an agent would pay for a prepaid, spend-capped Apify token;
  3. POST /api-proxy/actors/<our Actor>/runs, which answers 402 with the x402 challenge for one proxied run of that Actor.
No request carries a payment, a signature, a wallet or an Apify token, so nothing can be paid. Every result is labelled
"reached, not paid" (payment path verified, not exercised).
"""
from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

AGI = "https://agi.apify.com"
ACTORS = {"anoopibrampur/tech-bazaar-claim-check": "U4g8XPRpuGhDa97cM",
          "anoopibrampur/pc-build-compatibility-checker": "djo1yhWs81xud1DkO"}
AMOUNT_USD = 5  # the prepaid size #270 plans to buy; the probe only asks what it would cost
LABEL = "reached, not paid (payment path verified, not exercised)"
NETWORKS = {"eip155:8453": "Base", "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "Solana mainnet", "4217": "Tempo mainnet",
            "mainnet": "Solana mainnet"}
ASSETS = {k.lower(): v for k, v in {  # token addresses as Apify's challenges list them
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913": "USDC (Base)",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC (Solana)",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT (Solana)",
    "0x20c000000000000000000000b9537d11c60e8b50": "USDC.e (Tempo)",
    "0x20c0000000000000000000000000000000000000": "pathUSD (Tempo)"}.items()}
try:  # python.org builds on macOS ship without a CA bundle; certifi supplies one when it is installed
    import certifi
    TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS = ssl.create_default_context()
DECIMALS = 6  # every asset Apify lists here (USDC, USDT, USDC.e, pathUSD) has 6 decimals


def http(method: str, url: str, body: bytes | None = None, timeout: float = 20.0) -> tuple[int, dict, bytes]:
    """One unpaid request: no Authorization, no payment headers."""
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json", "User-Agent": "tech-bazaar-probe/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=TLS) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def _usd(atomic) -> float | None:
    try:
        return round(int(atomic) / 10 ** DECIMALS, 2)
    except (TypeError, ValueError):
        return None


def _x402(body: bytes, headers: dict) -> list[dict]:
    """x402 lists its offers in `accepts` (the body, and base64 JSON in the payment-required header)."""
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if not data.get("accepts") and headers.get("payment-required"):
        try:
            data = json.loads(base64.b64decode(headers["payment-required"]))
        except (ValueError, TypeError):
            data = {}
    return [{"protocol": "x402", "scheme": a.get("scheme"), "network": NETWORKS.get(a.get("network"), a.get("network")),
             "asset": ASSETS.get(str(a.get("asset", "")).lower(), a.get("asset")), "amount_usd": _usd(a.get("amount"))}
            for a in data.get("accepts") or [] if isinstance(a, dict)]


def _mpp(body: bytes) -> list[dict]:
    """MPP lists one challenge per network and currency in `challenges`."""
    try:
        data = json.loads(body)
    except ValueError:
        return []
    out = []
    for c in data.get("challenges") or []:
        req = c.get("request") or {}
        det = req.get("methodDetails") or {}
        net = str(det.get("chainId") or det.get("network") or "")
        out.append({"protocol": "mpp", "scheme": c.get("intent"), "method": c.get("method"), "network": NETWORKS.get(net, net),
                    "asset": ASSETS.get(str(req.get("currency", "")).lower(), req.get("currency")), "amount_usd": _usd(req.get("amount")),
                    "modes": det.get("supportedModes")})
    return out


def probe(send=http, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    steps = []
    status, _, body = send("GET", f"{AGI}/protocols")
    try:
        protocols = [p.get("name") for p in json.loads(body).get("protocols", [])]
    except (ValueError, AttributeError):
        protocols = []
    steps.append({"step": "list protocols", "request": "GET /protocols", "http": status, "protocols": protocols})
    for proto in ("x402", "mpp"):
        url = f"{AGI}/protocols/{proto}/prepaid-tokens?amount={AMOUNT_USD}&currency=usd"
        status, headers, body = send("GET", url)
        offers = _x402(body, headers) if proto == "x402" else _mpp(body)
        steps.append({"step": f"prepaid token via {proto}", "request": f"GET /protocols/{proto}/prepaid-tokens?amount={AMOUNT_USD}&currency=usd",
                      "http": status, "reached_pay_wall": status == 402 and bool(offers), "offers": offers, "label": LABEL})
    for name, actor_id in ACTORS.items():
        status, headers, body = send("POST", f"{AGI}/api-proxy/actors/{actor_id}/runs?amount=1&currency=usd", b"{}")
        offers = _x402(body, headers)
        steps.append({"step": f"proxied run of {name}", "request": f"POST /api-proxy/actors/{actor_id}/runs?amount=1&currency=usd",
                      "http": status, "reached_pay_wall": status == 402 and bool(offers), "offers": offers, "label": LABEL})
    walls = [s for s in steps if "reached_pay_wall" in s]
    return {"probed_at": now.isoformat(timespec="seconds"), "label": LABEL, "paid": False,
            "all_pay_walls_reached": all(s["reached_pay_wall"] for s in walls), "steps": steps,
            "note": "Unpaid requests only: no payment, signature, wallet or Apify token was sent, so nothing was charged."}


def report(result: dict) -> str:
    lines = [f"Apify agent pay probe, {result['probed_at']}: {result['label']}"]
    for s in result["steps"]:
        if "protocols" in s:
            lines.append(f"- {s['request']}: HTTP {s['http']}, protocols {', '.join(s['protocols']) or 'none'}")
            continue
        lines.append(f"- {s['request']}: HTTP {s['http']}, pay wall {'reached' if s['reached_pay_wall'] else 'NOT reached'}")
        for o in s["offers"]:
            amount = f"${o['amount_usd']:.2f}" if isinstance(o["amount_usd"], (int, float)) else "unknown amount"
            lines.append(f"    {o['protocol']} {o.get('scheme')}: {amount} in {o['asset']} on {o['network']}")
    lines.append(result["note"])
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="also write the result as JSON to this path")
    args = ap.parse_args(argv)
    result = probe()
    print(report(result))
    if args.out:
        with open(args.out, "w") as f:
            f.write(json.dumps(result, indent=1) + "\n")
    return 0 if result["all_pay_walls_reached"] else 1


if __name__ == "__main__":
    sys.exit(main())
