"""An AI agent pays Apify for one claim-check run with stablecoin, no Apify account (Lane C, issues #270, #347; in data/claim_check, not scripts/, per #276).

SPENDS REAL MONEY. Anoop runs it on his own machine with his Coinbase agentic wallet (awal, x402 on Base,
about $10 USDC); Vidyut approved $5 to $10 and reimburses from the receipt. Cap: $1 to $10 per run (--amount).
Terms (agi.apify.com/AGENTS.md): minimum $1, the token balance is a hard spend cap, the token expires 14 days after
purchase, and unused balance is not refunded.

RUNBOOK FOR ANOOP (#347, from the repo root)

1. Install and sign in to awal (Coinbase Agentic Wallet; npx fetches it, Node.js needed):
       npx awal auth login <email>          sign in
       npx awal auth verify <otp>           confirm the code from the email
       npx awal status                      check you are signed in
   The wallet key stays in Coinbase's wallet (or your own env as AGENT_WALLET_KEY), never in git, chat or a doc.
   This script never reads, prints or stores it.

2. Fund it with USDC on Base and check the balance:
       npx awal show                        funding UI: add USDC on Base (or send to: npx awal address)
       npx awal balance                     check the USDC balance
   Fund about $10 USDC on Base (at least --amount), plus a little ETH on Base (about 0.000001 ETH) for the
   one-time wallet deployment gas on the first payment. Write down the USDC balance BEFORE.

3. Run the free probe (no payment, no key, no token):
       python3 -m data.claim_check.agent_pay_probe
   Expect "reached, not paid" and HTTP 402 for x402 prepaid-tokens at $5.00 in USDC (Base). If not, stop.

4. Start the 30 s screen recording now, then run the paid command:
       python3 -m data.claim_check.agent_pay --payer awal --amount 5
   It shows what it will spend and asks you to type PAY (anything else stops it, nothing paid). Then it:
     a. buys a prepaid Apify token at agi.apify.com through awal:
          npx awal x402 pay <agi url> --max-amount 5000000   (USDC units, 5000000 = $5.00)
     b. prints the Base transaction hash and https://basescan.org/tx/<hash> when awal's output has one;
     c. saves the token as APIFY_AGENT_TOKEN in .env (gitignored, file mode 600); prints only its last 4 characters;
        if .env cannot be written, it saves the token to a mode 600 file .agent_pay_token.<UTC time> (gitignored)
        instead and stops with a NOT LIVE receipt that names that file (see step 7);
     d. prints the Apify prepaid balance before the run (expect about $5);
     e. runs the claim-check Actor once on the demo listing (waits up to 120 s) and prints the run id;
     f. prints the Apify prepaid balance after (expect a little less: the run's metered cost),
        and writes the receipt data/claim_check/agent_pay_run.json.

5. What to screen-record (30 s): the PAY prompt and typing PAY, the tx hash and basescan link, the balance
   before, the run id and its status, the balance after, and the receipt label. Then, if time allows, open
   the basescan link. Never show .env or the full token.

6. Check the wallet AFTER: npx awal balance. Expect the USDC balance down by $5 (plus the one-time gas in ETH).

7. Read the receipt label (printed, and "label" in data/claim_check/agent_pay_run.json) and act:
   LIVE
       Paid in this run, the Actor run SUCCEEDED, and the token balance dropped. Done: go to step 8.
   LIVE (payment unverified by balance)
       Paid and the run SUCCEEDED, but the balance could not be read or did not drop yet. Check it later with
       GET https://agi.apify.com/prepaid-tokens/balance (Bearer APIFY_AGENT_TOKEN); do not pay again. Go to step 8.
   NOT LIVE: paid, but the Actor run did not succeed (<status>)
       Money is spent and the token is saved. Do not pay again: fix the cause (status_message in the receipt), then
       rerun with the saved token: python3 -m data.claim_check.agent_pay --token-from-env
   NOT LIVE: paid, but the run request failed (<error>)
       Token saved. A run may have started: check the Apify console, then rerun with --token-from-env.
   NOT LIVE: paid, but .env could not be written (token in a fallback file)
       Money is spent and the token is in the file named by "token_file" in the receipt (.agent_pay_token.<UTC time>
       in the repo root or your home, mode 600, gitignored). Do not pay again: fix .env (read-only, a directory, disk
       full or not UTF-8), move the APIFY_AGENT_TOKEN line from that file into .env, delete the file, then rerun with
       --token-from-env.
   NOT LIVE: paid, but the token could not be saved anywhere
       Money is spent, and neither .env nor the fallback file could hold the token. The token could not be saved,
       and it is not shown on screen (the payer output is captured, never printed). Do NOT pay again. Keep the
       receipt and the tx hash (with its basescan link), check the npx awal history (npx awal show) for the
       payment, and ask Apify support with the tx hash.
   NOT LIVE: payment may have happened, no token returned (payer exit <code>)
   NOT LIVE: payment may have happened, the payer CLI timed out
   NOT LIVE: payment may have happened, the payer CLI failed (<error>)
       Payment may have happened: check the wallet and .env. Compare npx awal balance with step 2. If .env has
       APIFY_AGENT_TOKEN, rerun with --token-from-env. If the wallet dropped and there is no token, do not pay
       again; keep the receipt and the tx hash and ask Apify. If the wallet did not drop, nothing was paid and
       step 4 can be retried.
   NOT LIVE: no payment in this run (saved token)
   NOT LIVE: no payment in this run, and the run request failed (<error>)
       A --token-from-env rerun; never LIVE because nothing was paid in that run. The earlier paid receipt stands.
   FAKE (test)
       Only from the tests (fakes); never from a real run.
   No receipt, and a message "Not paid: you did not type PAY." or "The payer CLI for awal is not installed
   (see step 1). Nothing was paid." means nothing was spent: fix and repeat step 4.
   The exit code is 0 only when the Actor run SUCCEEDED.
   If the receipt says "tx hash not captured: copy it from the wallet history", awal printed no hash: copy it
   from the wallet history (npx awal show) or from basescan for your wallet address.

8. What to commit (branch from main, PR into main; author AnoopIbrampur, no AI attribution):
       data/claim_check/agent_pay_run.json      the receipt: amounts, run id, tx hash, timestamps; no token or key
   Never commit .env. Before committing, check the staged diff has no apify_api_ token and no wallet key.

9. After the run, update the Actor README section "Agents can pay per call" (data/claim_check/actor/README.md)
   with what really happened, labelled LIVE: the date, $5 via awal x402 on Base, the real tx hash with its
   basescan link, the Apify run id, and the balance before and after. Only if the label was LIVE.

10. Post on issue #347: the tx hash (with the basescan link), the Apify run id, the receipt label, and the
    30 s screen recording.

A rerun with the token already saved skips the purchase (never LIVE):
       python3 -m data.claim_check.agent_pay --token-from-env
Other payers also work (not the #347 plan): --payer mppx (MPP on Tempo: npm i -g mppx; mppx account create;
mppx account view; fund USDC.e or pathUSD) and --payer pay.sh (x402 on Solana: npm install -g @solana/pay;
pay setup; pay whoami; fund USDC or USDT). Their tx is not on Base, so no basescan link is printed.

A human types PAY every time; no flag skips the prompt, so an agent cannot spend on its own. The $1 to $10 cap is
per run. The payer CLI holds the wallet and signs the 402 challenge (awal signs in by email, mppx keeps its account
in the OS keychain, pay.sh uses the OS keystore), so a key never passes through this code or a command line. The
receipt is scrubbed of the token, every .env value and every secret-named environment variable before it is written.
"""
# Sources checked 2026-10-24 for steps 1 and 2 and the terms: https://agi.apify.com/AGENTS.md,
# https://docs.apify.com/integrations/x402.md (awal, USDC plus a little ETH on Base), https://docs.apify.com/integrations/mpp.md
# (mppx on Tempo), https://docs.cdp.coinbase.com/agentic-wallet/cli/skills/pay-for-service.md and .../skills/fund.md
# (awal status, show, address, x402 pay --max-amount). Those docs do not say where awal prints the settlement tx, so
# tx_from_output reads JSON fields (txHash, transaction as in an x402 settle response, transactionHash) and then the text.
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
TX_RE = re.compile(r"0x[0-9a-fA-F]{64}(?![0-9a-fA-F])")  # an EVM transaction hash: 32 bytes as 0x plus 64 hex
TX_KEYS = {"txhash", "tx_hash", "transactionhash", "transaction_hash", "transaction", "tx", "settlementtxhash"}
TX_WORDS = re.compile(r"\b(tx|txhash|transaction|hash|basescan)", re.I)
NOT_TX_WORDS = re.compile(r"nonce|key|secret|seed|signature|private|mnemonic", re.I)  # an EIP-3009 nonce is also 0x plus 64 hex
NO_TX = "tx hash not captured: copy it from the wallet history"
BASESCAN = "https://basescan.org/tx/"
SECRET_ENV = re.compile(r"KEY|SECRET|TOKEN|SEED|PRIVATE|MNEMONIC|PASSWORD", re.I)

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


def _tx_in(data) -> str | None:
    """A tx hash under a tx-like key anywhere in parsed JSON (x402 settle responses call it "transaction")."""
    if isinstance(data, dict):
        for k, v in data.items():
            if str(k).lower() in TX_KEYS and isinstance(v, str) and TX_RE.fullmatch(v.strip()):
                return v.strip()
        data = list(data.values())
    if isinstance(data, list):
        for v in data:
            found = _tx_in(v)
            if found:
                return found
    return None


def tx_from_output(out) -> str | None:
    """The on-chain transaction hash in the payer's output (#347), else None. JSON fields first (txHash, transaction,
    transactionHash, ...), then a 0x plus 64 hex string on a line that names a tx or hash. A line that mentions a nonce,
    key, secret, seed or signature is never read, so a nonce or key is never taken for a tx hash."""
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    out = out or ""
    for chunk in [out.strip()] + list(reversed(out.strip().splitlines())):
        try:
            found = _tx_in(json.loads(chunk))
        except ValueError:
            continue
        if found:
            return found
    for line in out.splitlines():
        if TX_WORDS.search(line) and not NOT_TX_WORDS.search(line):
            m = TX_RE.search(line)
            if m:
                return m.group(0)
    return None


def record_tx(receipt: dict, payer: str, stdout, out) -> None:
    """Put the tx hash (and a Base explorer link for awal) in the receipt and print them; or say it was not captured."""
    tx = tx_from_output(stdout)
    receipt["tx_hash"] = tx or NO_TX
    if tx and payer == "awal":
        receipt["tx_explorer"] = BASESCAN + tx
    out(f"Transaction: {tx}" + (f"  {BASESCAN}{tx}" if payer == "awal" else "") if tx else f"Transaction: {NO_TX}.")


FALLBACK_PREFIX = ".agent_pay_token."  # gitignored; holds the token only when .env cannot be written (#354)
ENV_NOT_WRITTEN = "NOT LIVE: paid, but .env could not be written (token in a fallback file)"
TOKEN_NOT_SAVED = "NOT LIVE: paid, but the token could not be saved anywhere"


class TokenNotSaved(Exception):
    """Neither .env nor a fallback file could hold the minted token (#354)."""


def _write_env(env_file: Path, token: str) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    lines = [l for l in lines if not l.startswith("APIFY_AGENT_TOKEN=")] + [f"APIFY_AGENT_TOKEN={token}"]
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(fd, 0o600)  # an existing .env keeps its old mode on open; tighten it before the token goes in
        f.write("\n".join(lines) + "\n")


def fallback_dirs(env_file: Path) -> list[Path]:
    """Where a token goes when .env cannot be written: next to .env (the repo root), then the user's home."""
    dirs = [env_file.parent]
    try:
        dirs.append(Path.home())
    except (RuntimeError, KeyError, OSError):
        pass
    return dirs


def save_token(env_file: Path, token: str) -> tuple[Path, str] | None:
    """Write APIFY_AGENT_TOKEN into the gitignored .env (replacing an older one), readable by this user only.
    The file is created with mode 600, and an existing one is set to 600 before the token is written (#329).
    Returns None when .env holds the token. If .env cannot be read or written (read-only, a directory, disk full,
    not UTF-8), the token goes to a new mode 600 file .agent_pay_token.<UTC time> (gitignored) and this returns
    (that path, the .env error); if that fails too, it raises TokenNotSaved (#354)."""
    try:
        _write_env(env_file, token)
        return None
    except (OSError, UnicodeDecodeError) as e:
        env_error = type(e).__name__
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for d in fallback_dirs(env_file):
        path = Path(d) / f"{FALLBACK_PREFIX}{stamp}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never world-readable, never overwrites
            with os.fdopen(fd, "w") as f:
                f.write(f"APIFY_AGENT_TOKEN={token}\n")
            return path, env_error
        except OSError:
            continue
    raise TokenNotSaved(env_error)


def keep_token(env_file: Path, token: str, receipt: dict, receipt_file: Path, out, paid_note: str = "") -> None:
    """Save a minted token; if .env cannot hold it, stop with a NOT LIVE receipt that names where it went (#354).
    The receipt never holds the token: it names only the fallback path."""
    try:
        where = save_token(env_file, token)
    except TokenNotSaved as e:
        receipt["token_file"] = "none: the token could not be saved"
        fail_with_receipt(receipt, receipt_file, out, TOKEN_NOT_SAVED,
                          f"{paid_note}Paid, but the token could not be saved: {env_file.name} failed ({e}) and so did the "
                          f"fallback file. The token is not shown on screen. Do NOT pay again. Keep this receipt and the tx "
                          f"hash (with its basescan link), check the npx awal history (npx awal show) for the payment, and "
                          f"ask Apify support with the tx hash.",
                          safe_secret_values(env_file) | {token})
    if where is None:
        return
    path, env_error = where
    receipt["token_file"] = str(path)
    fail_with_receipt(receipt, receipt_file, out, ENV_NOT_WRITTEN,
                      f"{paid_note}Paid, but {env_file.name} could not be written ({env_error}). The token {mask(token)} was "
                      f"saved to {path} (mode 600). Move that line into .env as APIFY_AGENT_TOKEN, delete {path.name}, then "
                      f"rerun with --token-from-env. Do not pay again.", safe_secret_values(env_file) | {token})


def masked_tail(text, n: int = 300) -> str:
    """The end of the payer's output with any token masked and any long hex or key-like run redacted, so a user can see
    what went wrong without a leak (#347: a tx hash goes in its own receipt field, never through here)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    tail = (text or "").strip()[-n:]
    tail = TOKEN_RE.sub(lambda m: mask(m.group(0)), tail)
    tail = re.sub(r"(0x)?[0-9a-fA-F]{40,}", "[redacted hex]", tail)
    tail = re.sub(r"(?<![A-Za-z0-9_./-])[A-Za-z0-9+/_-]{40,}={0,2}", "[redacted]", tail)
    return tail or "(no output)"


def safe_secret_values(env_file: Path) -> set[str]:
    """secret_values, but an unreadable .env (a directory, no permission, not UTF-8) never costs the receipt (#354)."""
    try:
        return secret_values(env_file)
    except (OSError, UnicodeDecodeError):
        return {v for k, v in os.environ.items() if SECRET_ENV.search(k) and len(v) >= 8}


def secret_values(env_file: Path) -> set[str]:
    """Every value in .env and every secret-named environment variable, so the receipt can be scrubbed of them."""
    vals = {v for k, v in os.environ.items() if SECRET_ENV.search(k)}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                vals.add(line.split("=", 1)[1].strip().strip("'\""))
    return {v for v in vals if len(v) >= 8}


def scrub(obj, secrets: set[str]):
    """The receipt holds no secrets (#347): drop any token, .env value or secret env value from every string in it."""
    if isinstance(obj, dict):
        return {k: scrub(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, secrets) for v in obj]
    if isinstance(obj, str):
        obj = re.sub(r"apify_api_[.A-Za-z0-9]*", "[redacted token]", obj)  # even the masked last 4 stay out
        for v in secrets:
            obj = obj.replace(v, "[redacted]")
    return obj


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


def write_receipt(receipt: dict, receipt_file: Path, out, secrets: set[str] = frozenset()) -> None:
    receipt["written_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    receipt_file.write_text(json.dumps(scrub(receipt, set(secrets)), indent=1) + "\n")
    out(f"Receipt written to {receipt_file.relative_to(ROOT) if receipt_file.is_relative_to(ROOT) else receipt_file} ({receipt['label']}).")


def fail_with_receipt(receipt: dict, receipt_file: Path, out, label: str, message: str, secrets: set[str] = frozenset()):
    """Once money may have been spent, never exit without an honest receipt (#329). These labels are never LIVE."""
    out(message)
    receipt["label"] = label
    receipt["error"] = message
    write_receipt(receipt, receipt_file, out, secrets)
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
            raise SystemExit(f"The payer CLI for {args.payer} is not installed (see step 1). Nothing was paid.") from None
        except subprocess.TimeoutExpired as e:  # it may have paid before it hung; keep a token if it printed one (#329)
            partial = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            token = token_from_output(partial)
            record_tx(receipt, args.payer, partial, out)
            if token:
                keep_token(env_file, token, receipt, receipt_file, out, "The payer CLI timed out after it returned a token. ")
            fail_with_receipt(receipt, receipt_file, out, "NOT LIVE: payment may have happened, the payer CLI timed out",
                              f"The payer CLI timed out after {e.timeout:g} s. {MAYBE_PAID}"
                              + (f" Its token {mask(token)} was saved as APIFY_AGENT_TOKEN in {env_file.name}." if token else ""),
                              safe_secret_values(env_file))
        except (Exception, KeyboardInterrupt) as e:  # a Ctrl-C mid-payment also leaves the money question open
            receipt["tx_hash"] = NO_TX
            fail_with_receipt(receipt, receipt_file, out, f"NOT LIVE: payment may have happened, the payer CLI failed ({type(e).__name__})",
                              f"The payer CLI failed ({type(e).__name__}). {MAYBE_PAID}", safe_secret_values(env_file))
        receipt["payer_exit"] = code
        record_tx(receipt, args.payer, stdout, out)
        token = token_from_output(stdout or "")
        if not token:
            fail_with_receipt(receipt, receipt_file, out, f"NOT LIVE: payment may have happened, no token returned (payer exit {code})",
                              f"The payer CLI did not return a token (exit {code}). Nothing was saved. {MAYBE_PAID} "
                              f"End of its output (tokens masked): {masked_tail(stdout)}", safe_secret_values(env_file))
        keep_token(env_file, token, receipt, receipt_file, out)  # a minted token means the money is spent: keep it even on a non-zero exit (#329)
        paid_now = True
        if code != 0:
            out(f"Warning: the payer CLI exited {code} but returned a token, so it paid; the token was kept. "
                f"End of its output (tokens masked): {masked_tail(stdout)}")
        out(f"a. Bought a prepaid token {mask(token)}; saved as APIFY_AGENT_TOKEN in {env_file.name} (mode 600).")
    secrets = safe_secret_values(env_file) | {token}
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
                              f"A run may have started; check the Apify console. {MAYBE_PAID}", secrets)
        fail_with_receipt(receipt, receipt_file, out, f"NOT LIVE: no payment in this run, and the run request failed ({why})",
                          f"The run request failed ({why}). A run may have started; check the Apify console.", secrets)
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
    write_receipt(receipt, receipt_file, out, secrets)
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
