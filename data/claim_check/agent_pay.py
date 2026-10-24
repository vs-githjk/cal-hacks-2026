"""An AI agent pays Apify for one claim-check run with stablecoin, no Apify account (Lane C, issues #270, #342; in data/claim_check, not scripts/, per #276).

SPENDS REAL MONEY. Run it only on the machine whose wallet Vidyut approved. Cap: $1 to $10 per run (--amount).
Terms (agi.apify.com/AGENTS.md): minimum $1, the token balance is a hard spend cap, the token expires 14 days after
purchase, and unused balance is not refunded.

RUNBOOK (from the repo root; pick ONE payer: awal or mppx)

1. Set up and fund the wallet (one time). The payer CLI holds the wallet; this script never sees a key.
   awal (Coinbase Agentic Wallet, x402, USDC on Base):
       npx awal auth login <email>          sign in
       npx awal auth verify <otp>           confirm the code from the email
       npx awal show                        funding UI: add USDC on Base (or: npx awal address)
       npx awal balance                     check the USDC balance
     Fund: at least --amount in USDC on Base, plus a little ETH on Base (about 0.000001 ETH) for the
     one-time wallet deployment gas on the first payment.
   mppx (MPP, USDC.e or pathUSD on Tempo):
       npm i -g mppx
       mppx account create                  the account lives in the OS keychain
       mppx account view                    prints the address to fund
     Fund: at least --amount in USDC.e or pathUSD on Tempo mainnet, plus a little extra for the network
     fee (Apify does not sponsor it).
   (pay.sh, x402 on Solana, also works: npm install -g @solana/pay; pay setup; pay whoami; fund USDC or USDT.)

2. Note the wallet balance BEFORE:  npx awal balance   or   mppx account view
   Expect at least --amount (default $5) plus the fee money from step 1.

3. Free check that the pay wall answers (no payment, no key, no token):
       python3 -m data.claim_check.agent_pay_probe
   Expect "reached, not paid" and HTTP 402 for x402 and mpp prepaid-tokens at $5.00. If not, stop.

4. Pay and run (pick one):
       python3 -m data.claim_check.agent_pay --payer awal --amount 5
       python3 -m data.claim_check.agent_pay --payer mppx --amount 5
   It shows what it will spend and asks you to type PAY (anything else stops it, nothing paid). Then:
     a. the payer CLI buys a prepaid Apify token at agi.apify.com:
          awal: npx awal x402 pay <agi url> --max-amount <amount in USDC units, 5000000 = $5>
          mppx: mppx <agi url>   (the amount is in the URL; mppx takes no separate cap)
     b. saves it as APIFY_AGENT_TOKEN in .env (gitignored, file mode 600); prints only its last 4 characters;
     c. prints the token balance before the run (expect about --amount, e.g. $5);
     d. runs the claim-check Actor once on the demo listing (waits up to 120 s);
     e. prints the token balance after (expect a little less: the run's metered cost) and the run id,
        and writes the receipt data/claim_check/agent_pay_run.json (token masked, no secret in it).

5. Note the wallet balance AFTER (same command as step 2). Expect it down by --amount (plus the network fee).

6. Read the receipt label (printed, and "label" in data/claim_check/agent_pay_run.json) and act:
   LIVE
       Paid in this run, the Actor run SUCCEEDED, and the token balance dropped. Done: share the run id and receipt.
   LIVE (payment unverified by balance)
       Paid and the run SUCCEEDED, but the balance could not be read or did not drop yet. Check it later with
       GET https://agi.apify.com/prepaid-tokens/balance (Bearer APIFY_AGENT_TOKEN); do not pay again.
   NOT LIVE: paid, but the Actor run did not succeed (<status>)
       Money is spent and the token is saved. Do not pay again: fix the cause (status_message in the receipt), then
       rerun with the saved token: python3 -m data.claim_check.agent_pay --token-from-env
   NOT LIVE: paid, but the run request failed (<error>)
       Token saved. A run may have started: check the Apify console, then rerun with --token-from-env.
   NOT LIVE: payment may have happened, no token returned (payer exit <code>)
   NOT LIVE: payment may have happened, the payer CLI timed out
   NOT LIVE: payment may have happened, the payer CLI failed (<error>)
       Payment may have happened: check the wallet and .env. Compare the wallet balance with step 2. If .env has
       APIFY_AGENT_TOKEN, rerun with --token-from-env. If the wallet dropped and there is no token, do not pay
       again; keep the receipt (it holds the payer output, tokens masked) and ask Apify. If the wallet did not
       drop, nothing was paid and step 4 can be retried.
   NOT LIVE: no payment in this run (saved token)
   NOT LIVE: no payment in this run, and the run request failed (<error>)
       A --token-from-env rerun; never LIVE because nothing was paid in that run. The earlier paid receipt stands.
   FAKE (test)
       Only from the tests (fakes); never from a real run.
   No receipt, and a message "Not paid: you did not type PAY." or "The payer CLI for <payer> is not installed
   (see step 1). Nothing was paid." means nothing was spent: fix and repeat step 4.
   The exit code is 0 only when the Actor run SUCCEEDED.

7. A rerun with the token already saved skips the purchase (never LIVE):
       python3 -m data.claim_check.agent_pay --token-from-env

A human types PAY every time; no flag skips the prompt, so an agent cannot spend on its own. The $1 to $10 cap is
per run. The script never reads, prints or stores a wallet key: the payer CLI holds the wallet and signs the 402
challenge (awal signs in by email, mppx keeps its account in the OS keychain, pay.sh uses the OS keystore).
"""
# Sources checked 2026-10-24 for step 1 and the terms: https://agi.apify.com/AGENTS.md,
# https://docs.apify.com/integrations/x402.md (awal, USDC plus a little ETH on Base), https://docs.apify.com/integrations/mpp.md (mppx on Tempo).
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

ROOT = Path(__file__).resolve().parents[2]
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
    """Write APIFY_AGENT_TOKEN into the gitignored .env (replacing an older one), readable by this user only.
    The file is created with mode 600, and an existing one is set to 600 before the token is written (#329)."""
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    lines = [l for l in lines if not l.startswith("APIFY_AGENT_TOKEN=")] + [f"APIFY_AGENT_TOKEN={token}"]
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(fd, 0o600)  # an existing .env keeps its old mode on open; tighten it before the token goes in
        f.write("\n".join(lines) + "\n")


def masked_tail(text, n: int = 300) -> str:
    """The end of the payer's output with any token masked, so a user can see what went wrong without a leak."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    tail = (text or "").strip()[-n:]
    return TOKEN_RE.sub(lambda m: mask(m.group(0)), tail) or "(no output)"


def read_token(env_file: Path) -> str | None:
    if os.environ.get("APIFY_AGENT_TOKEN"):
        return os.environ["APIFY_AGENT_TOKEN"]
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("APIFY_AGENT_TOKEN="):
                return line.split("=", 1)[1].strip() or None
    return None


def balance(send, token: str) -> float | None:
    try:  # a balance read is informational; a network error must not cost the receipt (#329)
        status, data = send("GET", f"{AGI}/prepaid-tokens/balance", token=token)
    except Exception:
        return None
    return data.get("remainingBalanceUsd") if status == 200 and isinstance(data, dict) else None


def label_for(live: bool, paid_now: bool, run_status: str | None, balance_moved: bool = True) -> str:
    """LIVE only for a real run that paid in this run and whose Actor run SUCCEEDED (#290). When the balance could not
    be read or did not drop, the label says the payment is unverified by balance (#329)."""
    if not live:
        return "FAKE (test)"
    if not paid_now:
        return "NOT LIVE: no payment in this run (saved token)"
    if run_status != "SUCCEEDED":
        return f"NOT LIVE: paid, but the Actor run did not succeed ({run_status or 'no status'})"
    return "LIVE" if balance_moved else "LIVE (payment unverified by balance)"


MAYBE_PAID = "Payment may have happened: check the wallet and .env."


def write_receipt(receipt: dict, receipt_file: Path, out) -> None:
    receipt_file.write_text(json.dumps(receipt, indent=1) + "\n")
    out(f"Receipt written to {receipt_file.relative_to(ROOT) if receipt_file.is_relative_to(ROOT) else receipt_file} ({receipt['label']}).")


def fail_with_receipt(receipt: dict, receipt_file: Path, out, label: str, message: str):
    """Once money may have been spent, never exit without an honest receipt (#329). These labels are never LIVE."""
    out(message)
    receipt["label"] = label
    receipt["error"] = message
    write_receipt(receipt, receipt_file, out)
    raise SystemExit(message)


def run(args, send=http, sh=shell, ask=input, sleep=time.sleep, out=print, env_file: Path | None = None,
        receipt_file: Path | None = None, live: bool = True) -> dict:
    env_file = env_file or ROOT / ".env"
    receipt_file = receipt_file or ROOT / "data" / "claim_check" / "agent_pay_run.json"
    paid_now = False
    receipt = {"label": None, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
        if ask("Type PAY to continue: ").strip() != "PAY":  # always asked; there is no flag that skips it (#290)
            raise SystemExit("Not paid: you did not type PAY.")
        receipt["paid_via"] = f"{protocol} via {args.payer}"
        receipt["amount_usd"] = args.amount
        try:
            code, stdout = sh(cmd(url, args.amount))
        except FileNotFoundError:  # the CLI never started, so nothing was paid
            raise SystemExit(f"The payer CLI for {args.payer} is not installed (see step 0). Nothing was paid.") from None
        except subprocess.TimeoutExpired as e:  # it may have paid before it hung; keep a token if it printed one (#329)
            partial = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            token = token_from_output(partial)
            if token:
                save_token(env_file, token)
                receipt["token"] = mask(token)
            fail_with_receipt(receipt, receipt_file, out, "NOT LIVE: payment may have happened, the payer CLI timed out",
                              f"The payer CLI timed out after {e.timeout:g} s. {MAYBE_PAID}"
                              + (f" Its token {mask(token)} was saved as APIFY_AGENT_TOKEN in {env_file.name}." if token else ""))
        except (Exception, KeyboardInterrupt) as e:  # a Ctrl-C mid-payment also leaves the money question open
            fail_with_receipt(receipt, receipt_file, out, f"NOT LIVE: payment may have happened, the payer CLI failed ({type(e).__name__})",
                              f"The payer CLI failed ({type(e).__name__}). {MAYBE_PAID}")
        receipt["payer_exit"] = code
        token = token_from_output(stdout or "")
        if not token:
            fail_with_receipt(receipt, receipt_file, out, f"NOT LIVE: payment may have happened, no token returned (payer exit {code})",
                              f"The payer CLI did not return a token (exit {code}). Nothing was saved. {MAYBE_PAID} "
                              f"End of its output (tokens masked): {masked_tail(stdout)}")
        save_token(env_file, token)  # a minted token means the money is spent: keep it even on a non-zero exit (#329)
        paid_now = True
        if code != 0:
            out(f"Warning: the payer CLI exited {code} but returned a token, so it paid; the token was kept. "
                f"End of its output (tokens masked): {masked_tail(stdout)}")
        out(f"a. Bought a prepaid token {mask(token)}; saved as APIFY_AGENT_TOKEN in {env_file.name} (mode 600).")
    receipt["token"] = mask(token)
    before = balance(send, token)
    receipt["balance_before_usd"] = before
    out(f"c. Balance before the run: ${before}" if before is not None else "c. Balance before the run: could not be read")
    try:
        status, data = send("POST", f"{API}/acts/{ACTOR}/runs?waitForFinish=120", token=token, body=DEMO_INPUT)
    except Exception as e:  # URLError, a timeout or a reset after paying: a receipt, never a bare traceback (#329)
        why = type(e).__name__
        if paid_now:
            fail_with_receipt(receipt, receipt_file, out, f"NOT LIVE: paid, but the run request failed ({why})",
                              f"Paid, and the token {mask(token)} is saved in {env_file.name}, but the run request failed ({why}). "
                              f"A run may have started; check the Apify console. {MAYBE_PAID}")
        fail_with_receipt(receipt, receipt_file, out, f"NOT LIVE: no payment in this run, and the run request failed ({why})",
                          f"The run request failed ({why}). A run may have started; check the Apify console.")
    run_data = (data or {}).get("data") or {} if isinstance(data, dict) else {}
    receipt.update(run_http=status, run_id=run_data.get("id"), run_status=run_data.get("status"), status_message=run_data.get("statusMessage"))
    if run_data.get("defaultDatasetId"):
        try:
            _, items = send("GET", f"{API}/datasets/{run_data['defaultDatasetId']}/items?clean=1", token=token)
        except Exception as e:  # the run already happened; record that its rows could not be read
            items, receipt["results_error"] = None, type(e).__name__
        items = items if isinstance(items, list) else []
        receipt["results"] = [{k: r.get(k) for k in ("id", "text", "result", "reason")} for r in items if isinstance(r, dict)]
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
    moved = before is not None and after is not None and after < before
    receipt["label"] = label_for(live, paid_now, receipt.get("run_status"), balance_moved=moved)
    write_receipt(receipt, receipt_file, out)
    return receipt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--payer", choices=sorted(PAYERS), default="awal", help="the wallet CLI that pays the 402 challenge (default awal)")
    ap.add_argument("--amount", type=float, default=5.0, help=f"USD to prepay, {MIN_USD} to {MAX_USD} (default 5)")
    ap.add_argument("--token-from-env", action="store_true", help="skip the purchase and use a saved APIFY_AGENT_TOKEN")
    args = ap.parse_args(argv)
    r = run(args)
    return 0 if r.get("run_status") == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
