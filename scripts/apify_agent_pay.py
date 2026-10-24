"""An AI agent pays Apify for one claim-check run with stablecoin, no Apify account (Lane C, issue #270, Tier B).

SPENDS REAL MONEY. Run it only on the machine whose wallet Vidyut approved ($5 to $10).

Run steps, in order:
  0. Fund a wallet that the payer CLI controls, then sign in to it:
       awal (Coinbase, x402 on Base):  npx awal auth login <email>; npx awal auth verify <otp>; npx awal balance
       mppx (MPP on Tempo):            npm i -g mppx; mppx account create; mppx account view   (fund USDC.e or pathUSD)
       pay.sh (Solana, x402):          npm install -g @solana/pay; pay setup; pay whoami       (fund USDC or USDT)
  1. Free check that the pay wall answers:   python3 scripts/apify_agent_pay_probe.py
  2. Pay and run:                            python3 scripts/apify_agent_pay.py --payer awal --amount 5
     It shows what it will spend and asks you to type PAY. Then it:
       a. buys a prepaid, spend-capped Apify token for --amount USD at agi.apify.com through the payer CLI;
       b. saves the token as APIFY_AGENT_TOKEN in .env (gitignored, file mode 600); it never prints it, only its last 4 characters;
       c. prints the token's balance (GET https://agi.apify.com/prepaid-tokens/balance);
       d. runs the claim-check Actor once on the demo listing with that token;
       e. prints the balance again and the run id, and writes data/claim_check/agent_pay_run.json labelled LIVE.
  3. A rerun with the token already saved skips the purchase:   python3 scripts/apify_agent_pay.py --token-from-env

The script never reads, prints or stores a wallet key. The payer CLI holds the wallet and signs the 402 challenge
(awal signs in by email, mppx keeps its account in the OS keychain, pay.sh uses the OS keystore), so a key never passes
through this code or a command line. Terms (agi.apify.com/AGENTS.md): minimum $1, the token is a hard spend cap, it expires
after 14 days, and unused balance is not refunded.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGI = "https://agi.apify.com"
API = "https://api.apify.com/v2"
ACTOR = "anoopibrampur~tech-bazaar-claim-check"
DEMO_INPUT = {"listingUrl": "https://www.canadacomputers.com/en/powered-by-nvidia/269441/msi-rtx-5070-ti-16g-shadow-3x-oc-gddr7-triple-fans-rtx-5070-ti-16g-shadow-3x-oc.html",
              "claimTexts": ["price $1,749.99", "new", "in stock"]}
MIN_USD, MAX_USD = 1, 10  # Apify's minimum; Vidyut approved up to $10
PAYERS = {  # (protocol, command) per payer CLI; each one runs the whole 402 handshake and prints the minted token as JSON
    "awal": ("x402 on Base", lambda url, usd: ["npx", "awal", "x402", "pay", url, "--max-amount", str(int(round(usd * 1_000_000)))]),
    "mppx": ("MPP on Tempo", lambda url, usd: ["mppx", url]),
    "pay.sh": ("x402 on Solana", lambda url, usd: ["pay", "--mainnet", "--x402", "curl", url]),
}
TOKEN_RE = re.compile(r"apify_api_[A-Za-z0-9]+")

try:  # python.org builds on macOS ship without a CA bundle; certifi supplies one when it is installed
    import certifi
    TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS = ssl.create_default_context()


def http(method: str, url: str, token: str | None = None, body: dict | None = None, timeout: float = 150.0) -> tuple[int, dict | list | None]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=TLS) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, None


def shell(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout


def mask(token: str) -> str:
    return f"apify_api_...{token[-4:]}" if token else "(none)"


def token_from_output(out: str) -> str | None:
    """The payer CLI prints {"token": "apify_api_...", ...}; read it from the last JSON object, else from the text."""
    for line in reversed(out.strip().splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and TOKEN_RE.fullmatch(str(data.get("token", ""))):
            return data["token"]
    m = TOKEN_RE.search(out)
    return m.group(0) if m else None


def save_token(env_file: Path, token: str) -> None:
    """Write APIFY_AGENT_TOKEN into the gitignored .env (replacing an older one), readable by this user only."""
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    lines = [l for l in lines if not l.startswith("APIFY_AGENT_TOKEN=")] + [f"APIFY_AGENT_TOKEN={token}"]
    env_file.write_text("\n".join(lines) + "\n")
    os.chmod(env_file, 0o600)


def read_token(env_file: Path) -> str | None:
    if os.environ.get("APIFY_AGENT_TOKEN"):
        return os.environ["APIFY_AGENT_TOKEN"]
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("APIFY_AGENT_TOKEN="):
                return line.split("=", 1)[1].strip() or None
    return None


def balance(send, token: str) -> float | None:
    status, data = send("GET", f"{AGI}/prepaid-tokens/balance", token=token)
    return data.get("remainingBalanceUsd") if status == 200 and isinstance(data, dict) else None


def run(args, send=http, sh=shell, ask=input, sleep=time.sleep, out=print, env_file: Path | None = None,
        receipt_file: Path | None = None, live: bool = True) -> dict:
    env_file = env_file or ROOT / ".env"
    receipt_file = receipt_file or ROOT / "data" / "claim_check" / "agent_pay_run.json"
    receipt = {"label": "LIVE" if live else "FAKE (test)", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "actor": ACTOR.replace("~", "/"), "input": DEMO_INPUT}
    if args.token_from_env:
        token = read_token(env_file)
        if not token:
            raise SystemExit("No APIFY_AGENT_TOKEN in the environment or .env; run without --token-from-env to buy one.")
        receipt["paid_via"] = "prepaid token bought earlier"
    else:
        if not MIN_USD <= args.amount <= MAX_USD:
            raise SystemExit(f"--amount must be between {MIN_USD} and {MAX_USD} USD (Apify's minimum is $1; the approved cap is $10).")
        protocol, cmd = PAYERS[args.payer]
        url = f"{AGI}/protocols/{'mpp' if args.payer == 'mppx' else 'x402'}/prepaid-tokens?amount={args.amount:g}&currency=usd"
        out(f"About to spend ${args.amount:.2f} of real stablecoin ({protocol}, via {args.payer}) for a prepaid Apify token.")
        out("Terms: the token is a hard spend cap, expires in 14 days, and unused balance is not refunded.")
        if not args.yes and ask("Type PAY to continue: ").strip() != "PAY":
            raise SystemExit("Not paid: you did not type PAY.")
        code, stdout = sh(cmd(url, args.amount))
        token = token_from_output(stdout)
        if code != 0 or not token:
            raise SystemExit(f"The payer CLI did not return a token (exit {code}). Nothing was saved; check its own output above.")
        save_token(env_file, token)
        receipt["paid_via"] = f"{protocol} via {args.payer}"
        receipt["amount_usd"] = args.amount
        out(f"a. Bought a prepaid token {mask(token)}; saved as APIFY_AGENT_TOKEN in {env_file.name} (mode 600).")
    receipt["token"] = mask(token)
    before = balance(send, token)
    receipt["balance_before_usd"] = before
    out(f"c. Balance before the run: ${before}" if before is not None else "c. Balance before the run: could not be read")
    status, data = send("POST", f"{API}/acts/{ACTOR}/runs?waitForFinish=120", token=token, body=DEMO_INPUT)
    run_data = (data or {}).get("data") or {} if isinstance(data, dict) else {}
    receipt.update(run_http=status, run_id=run_data.get("id"), run_status=run_data.get("status"), status_message=run_data.get("statusMessage"))
    if run_data.get("defaultDatasetId"):
        _, items = send("GET", f"{API}/datasets/{run_data['defaultDatasetId']}/items?clean=1", token=token)
        receipt["results"] = [{k: r.get(k) for k in ("id", "text", "result", "reason")} for r in items or [] if isinstance(r, dict)]
    out(f"d. Claim-check run {receipt['run_id']}: {receipt['run_status']} ({receipt['status_message']})")
    after = balance(send, token)
    for _ in range(3):  # metering can lag the run by a little; wait briefly for the balance to move
        if after is None or before is None or after < before:
            break
        sleep(10)
        after = balance(send, token)
    receipt["balance_after_usd"] = after
    if before is not None and after is not None:
        receipt["spent_usd"] = round(before - after, 5)
    out(f"e. Balance after the run: ${after} (spent ${receipt.get('spent_usd')}); run id {receipt['run_id']}")
    receipt_file.write_text(json.dumps(receipt, indent=1) + "\n")
    out(f"Receipt written to {receipt_file.relative_to(ROOT) if receipt_file.is_relative_to(ROOT) else receipt_file} ({receipt['label']}).")
    return receipt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--payer", choices=sorted(PAYERS), default="awal", help="the wallet CLI that pays the 402 challenge (default awal)")
    ap.add_argument("--amount", type=float, default=5.0, help=f"USD to prepay, {MIN_USD} to {MAX_USD} (default 5)")
    ap.add_argument("--token-from-env", action="store_true", help="skip the purchase and use a saved APIFY_AGENT_TOKEN")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation (for the orchestrator)")
    args = ap.parse_args(argv)
    r = run(args)
    return 0 if r.get("run_status") == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
