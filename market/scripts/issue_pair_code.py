"""Issue a pairing code for a buyer screen (or a seller screen), as the module owner.

#449 RT-2: the market keeps only the hash of a pairing code and never makes one (its random source is predictable), so the
owner makes the code here and sends it with reissue_pair_code / reissue_seller_screen_code. The code is printed once, to you.
Run it after seed_demo (and after any publish that wipes data), then give the code to the person who pairs.

Usage: python3 market/scripts/issue_pair_code.py [buyer_id]            (default vidyut)
       python3 market/scripts/issue_pair_code.py --seller seller-a
Env: SPACETIMEDB_SERVER (CLI server name, default local), SPACETIMEDB_DB (default tech-bazaar). Needs the spacetime CLI,
logged in as the identity that published the module.
"""
import json
import os
import subprocess
import sys

from stdb import DB, new_pair_code


def issue(subject, code, seller=False, run=subprocess.run, server=None, db=None):
    """Send `code` for one buyer (or seller screen). Raises RuntimeError whose text never holds the code."""
    reducer = "reissue_seller_screen_code" if seller else "reissue_pair_code"
    cmd = ["spacetime", "call", "-s", server or os.environ.get("SPACETIMEDB_SERVER", "local"), db or DB, reducer,
           json.dumps(subject), json.dumps(code)]
    try:
        p = run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"could not run the spacetime CLI: {type(e).__name__}") from None
    if p.returncode != 0:
        first = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()
        raise RuntimeError(f"{reducer} failed (exit {p.returncode}): {(first[0] if first else 'no output').replace(code, '[code]')[:200]}")


def main(argv, run=subprocess.run, server=None, db=None, out=print, err=None):
    err = err or (lambda m: print(m, file=sys.stderr))
    args = list(argv)
    seller = "--seller" in args
    if seller:
        args.remove("--seller")
    if len(args) > 1 or any(a.startswith("-") for a in args):   # --help or a typo must never become a subject id
        (err or (lambda m: print(m, file=sys.stderr)))("Usage: issue_pair_code.py [buyer_id]   |   issue_pair_code.py --seller seller_id")
        return 2
    subject = args[0] if args else ("seller-a" if seller else "vidyut")
    code = new_pair_code()
    try:
        issue(subject, code, seller=seller, run=run, server=server, db=db)
    except RuntimeError as e:
        err(f"pairing code NOT issued: {e}")
        return 1
    out(f"Pairing code for {'seller screen' if seller else 'buyer'} {subject}: {code}")
    out("Shown once, to you. The market keeps only its hash; reissue to get another (that also clears screen locks).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
