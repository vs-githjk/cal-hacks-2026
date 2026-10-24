#!/usr/bin/env python3
"""Tech Bazaar seller kit client. The tech-bazaar-seller skill calls this after it has interviewed a shop owner.

    python3 seller_kit_client.py answers.json          build a SellerConfig from the answers, POST it, print the run command
    python3 seller_kit_client.py - < answers.json      same, answers from stdin
    python3 seller_kit_client.py answers.json --dry-run   print the SellerConfig, call nothing
    python3 seller_kit_client.py --needs               list the open needs a shop could bid on (each carries LIVE, MIRROR or SIM)

Answers file (JSON, plain words): store, owner, archetype, pricing {mode: fixed_margin + margin_pct | discount + discount_pct},
shipping, returns, perks[], claims[], items[] each {sku, condition, price (discount mode) or cost (fixed_margin mode),
floor (lowest price for that condition) or floors {condition: lowest price}, url, attrs, also[]}.

The client builds the config and passes every value through untouched. It never repairs a floor, price, condition or URL:
the Seller Kit API (seller_kit/api.py, port 8791) is the guard and refuses a bad one with field errors. Origin is always SIM
because the kit cannot verify a real shop. Standard library only. Exit codes: 0 ok, 1 refused or bad input, 2 kit not running.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

DEFAULT_URL = "http://127.0.0.1:8791"
TIMEOUT = 10


class ClientError(Exception):
    """Bad input, or an answer from the kit that is not its normal shape."""


class KitDown(ClientError):
    """The Seller Kit API cannot be reached."""


class KitRefused(ClientError):
    """The kit answered with a refusal (422 field errors, 409 taken id, ...)."""

    def __init__(self, status: int, errors: list[dict]):
        self.status, self.errors = status, errors
        super().__init__("; ".join(f"{e.get('field', 'config')}: {e.get('message', '')}" for e in errors) or f"refused ({status})")


Transport = Callable[..., tuple]  # (method, url, body bytes or None) -> (status, parsed JSON or None)


def http_transport(method: str, url: str, body: bytes | None = None) -> tuple:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"content-type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:  # a refusal still has a body worth reading
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40]


def _sku(text: Any) -> Any:
    return re.sub(r"\s+", " ", text.strip().lower()) if isinstance(text, str) else text


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _pricing(p: Any) -> Any:
    if not isinstance(p, dict):
        return p
    out = {k: v for k, v in p.items() if k != "discount_pct"}
    if "discount_pct" in p:  # owners say 5 percent; the kit reads the fraction 0.05
        out["discount"] = round(p["discount_pct"] / 100, 6) if _num(p["discount_pct"]) else p["discount_pct"]
    return out


_MARKET_DAYS = re.compile(r"(\d+)[- ]day returns?", re.I)  # how the market reads return days (market/rules/scoring.ts returnsDays)
_TIED_DAYS = re.compile(r"(\d+)\s*-?\s*days?\s*(?:returns?|refund|money)\b", re.I)
_DAYS = re.compile(r"(\d+)\s*-?\s*days?\b", re.I)
_NO_RETURNS = re.compile(r"\bno\s+returns?\b|\bfinal\s+sale\b|\bnon-?\s?refundable\b|\bno\s+refunds?\b", re.I)
_NOT_RETURNS = re.compile(r"warrant|guarant|support", re.I)
_CLAUSE_END = re.compile(r"[,;]|\.(?=\s+(?![a-z])|\s*$)")  # a period ends a clause unless a lowercase word follows ('mfr. warranty')


def _return_days(text: Any) -> int:
    """The day count the owner tied to returns ('30 days returns', '7 day money back'), or the one day count in the
    answer ('30 days, no restocking fee') when nothing in the answer says there are no returns; day counts in a clause
    (the text between commas, semicolons and periods not followed by a lowercase word, so 'mfr. warranty' stays one clause) about a warranty, guarantee or support never count; 0 otherwise."""
    text = str(text)
    if _MARKET_DAYS.search(text):
        return 0  # the market already reads the owner's own words
    tied = _TIED_DAYS.findall(text)
    if tied:
        return int(tied[0])
    if _NO_RETURNS.search(text):
        return 0
    found = [n for c in _CLAUSE_END.split(text) if not _NOT_RETURNS.search(c) for n in _DAYS.findall(c)]
    return int(found[0]) if len(found) == 1 else 0


def _listing(item: dict) -> dict:
    ls: dict[str, Any] = {}
    for key in ("condition", "page_condition", "variant", "price", "cost", "attrs"):
        if key in item:
            ls[key] = item[key]
    if "url" in item:
        ls["listing_url"] = item["url"]
    if "floors" in item:
        ls["floor_by_condition"] = item["floors"]
    elif "floor" in item:
        ls["floor_by_condition"] = {item.get("condition"): item["floor"]}
    if item.get("also"):
        ls["alt_lines"] = [{("listing_url" if k == "url" else k): v for k, v in alt.items()} if isinstance(alt, dict) else alt
                           for alt in item["also"]]
    return ls


def build_config(answers: Any) -> dict:
    """SellerConfig (contracts/SellerConfig.schema.json) from the owner's answers. Missing answers are left out so the
    kit names the missing fields; present ones are passed through as given."""
    if not isinstance(answers, dict):
        raise ClientError("the answers must be a JSON object")
    cfg: dict[str, Any] = {}
    store = answers.get("store", answers.get("name"))
    if answers.get("id") is not None:
        cfg["id"] = answers["id"]
    elif isinstance(store, str) and _slug(store):
        cfg["id"] = _slug(store)
    if store is not None:
        cfg["name"] = store
    for key in ("owner", "archetype", "shipping", "port"):
        if key in answers:
            cfg[key] = answers[key]
    cfg["origin"] = "SIM"
    if "pricing" in answers:
        cfg["pricing"] = _pricing(answers["pricing"])
    perks = list(answers.get("perks") or [])
    if answers.get("returns"):
        text, days = str(answers["returns"]), _return_days(answers["returns"])
        if days and any(m.group(1) == str(days) for p in perks if (m := _MARKET_DAYS.search(str(p)))):
            days = 0  # the owner already gave this day count as a perk
        if days and len(f"{days}-day returns: {text}") <= 120:
            perks.append(f"{days}-day returns: {text}")  # one perk: the owner's words behind the form the market reads
        else:
            perks.append(f"returns: {text}")
            if days:  # the owner's words are too long to fold, so the day count is a second perk
                if len(perks) > 9:
                    raise ClientError(
                        f"the returns answer is too long to fold into one perk, so it needs 2 of the 10 perk slots, and {len(perks) - 1} "
                        f"other perks are given. Give at most 8 other perks or shorten the returns answer to {106 - len(str(days))} characters.")
                perks.append(f"{days}-day returns")
    if perks:
        cfg["perks"] = perks
    if answers.get("claims"):
        cfg["claims"] = list(answers["claims"])
    listings: dict[str, Any] = {}
    seen: dict[Any, tuple[int, dict]] = {}
    for n, item in enumerate(answers.get("items") or [], 1):
        if isinstance(item, dict):
            key = _sku(item.get("sku", ""))
            if key in seen:
                m, first = seen[key]
                raise ClientError(
                    f"item {m} (sku {first.get('sku')!r}, condition {first.get('condition')!r}) and item {n} (sku {item.get('sku')!r}, "
                    f"condition {item.get('condition')!r}) are the same part. One part can have only one entry. Put the extra "
                    f"condition under 'also' on item {m}, with its own lowest price in 'floors' ({{condition: floor}}).")
            seen[key] = (n, item)
            listings[key] = _listing(item)
    cfg["listings"] = listings
    return cfg


def _base(url: str) -> str:
    if not re.match(r"^https?://[^\s/]+", url or ""):
        raise ClientError(f"the Seller Kit address must start with http:// or https:// (got {url!r})")
    return url.rstrip("/")


def _call(method: str, url: str, body: bytes | None, transport: Transport | None, base: str) -> tuple:
    try:
        return (transport or http_transport)(method, url, body)
    except (OSError, urllib.error.URLError) as e:  # refused, DNS, timeout
        raise KitDown(f"The Seller Kit is not running at {base} ({e.__class__.__name__}). Nothing was saved. "
                      f"Start the Tech Bazaar stack with `python3 scripts/launch.py up` from the repo, "
                      f"or set SELLER_KIT_URL (or pass --url) to where the kit runs.") from e


def post_config(cfg: dict, base_url: str = DEFAULT_URL, *, transport: Transport | None = None, replace: bool = False) -> dict:
    base = _base(base_url)
    url = f"{base}/v1/sellers" + ("?replace=true" if replace else "")
    status, payload = _call("POST", url, json.dumps(cfg).encode("utf-8"), transport, base)
    if status in (200, 201) and isinstance(payload, dict) and "config_path" in payload and "run_command" in payload:
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("errors"), list) and payload["errors"]:
        raise KitRefused(status, payload["errors"])
    raise ClientError(f"the Seller Kit answered {status} without a config_path and run_command, so nothing is confirmed saved")


def open_needs(base_url: str = DEFAULT_URL, *, transport: Transport | None = None) -> list[dict]:
    base = _base(base_url)
    status, payload = _call("GET", f"{base}/v1/needs/open", None, transport, base)
    if status != 200 or not isinstance(payload, list):
        raise ClientError(f"the Seller Kit answered {status} to GET /v1/needs/open instead of a list")
    return payload


def _read_answers(path: str, stdin) -> Any:
    try:
        text = stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError) as e:
        raise ClientError(f"cannot read {path}: {e.__class__.__name__}") from e
    try:
        return json.loads(text)
    except ValueError as e:
        raise ClientError(f"{path} is not valid JSON ({e})") from e


def main(argv: list[str] | None = None, *, transport: Transport | None = None, stdout=None, stderr=None, stdin=None) -> int:
    out, err, inp = stdout or sys.stdout, stderr or sys.stderr, stdin or sys.stdin
    ap = argparse.ArgumentParser(prog="seller_kit_client.py", description="Set up a Tech Bazaar seller agent from interview answers.")
    ap.add_argument("answers", nargs="?", help="answers JSON file, or - for stdin")
    ap.add_argument("--url", default=None, help=f"Seller Kit address (default SELLER_KIT_URL or {DEFAULT_URL})")
    ap.add_argument("--dry-run", action="store_true", help="print the SellerConfig and call nothing")
    ap.add_argument("--replace", action="store_true", help="overwrite a shop that already has this id")
    ap.add_argument("--needs", action="store_true", help="list open needs instead of adding a shop")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    url = args.url or os.environ.get("SELLER_KIT_URL") or DEFAULT_URL
    try:
        if args.needs:
            needs = open_needs(url, transport=transport)
            for n in needs:
                conds = "/".join(n.get("allowed_conditions") or []) or "any"
                print(f"- {n.get('sku_spec')} x{n.get('quantity', 1)} ({conds}), {n.get('delivery_window', 'no window given')} "
                      f"[{n.get('origin', 'SIM')}]", file=out)
            if not needs:
                print("No open needs right now.", file=out)
            return 0
        if not args.answers:
            raise ClientError("give the answers file (or - for stdin), or use --needs")
        cfg = build_config(_read_answers(args.answers, inp))
        if args.dry_run:
            print(json.dumps(cfg, indent=2), file=out)
            return 0
        res = post_config(cfg, url, transport=transport, replace=args.replace)
    except KitDown as e:
        print(str(e), file=err)
        return 2
    except KitRefused as e:
        print("The Seller Kit refused this shop. Nothing was saved. Fix these and run it again:", file=err)
        for item in e.errors:
            print(f"  {item.get('field', 'config')}: {item.get('message', '')}", file=err)
        if e.status == 409:
            print("  (to overwrite the existing shop, run again with --replace)", file=err)
        return 1
    except ClientError as e:
        print(str(e), file=err)
        return 1
    print(f"Your seller agent is set up: {res.get('name') or res['id']} (id {res['id']}, {res.get('origin', 'SIM')}).", file=out)
    print(f"Config written to: {res['config_path']}", file=out)
    print("Start it with:", file=out)
    print(f"  {res['run_command']}", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
