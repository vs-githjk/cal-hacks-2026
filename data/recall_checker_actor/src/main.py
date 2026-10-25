"""Apify Actor entry: is this product recalled? One dataset row per product, from the U.S. CPSC recall API.

Pricing (pay-per-event): one "product-checked" event per product the CPSC API answered for (recalled, possible or none),
charged before its row is delivered. "unverified" (no brand, or the lookup failed) is free. A spent limit or a failed charge
stops the run and the summary says how many products were not checked. The state marks a product paid before delivery,
so a restarted run never charges a product twice.
"""
import asyncio
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the bundled src/data/ imports as data.*

from apify import Actor  # noqa: E402

from data.recall_checker import check_product  # noqa: E402

EVENT = "product-checked"
STATE_KEY = "STATE_next_product"
CACHE = Path("/tmp/recalls_cache")
CPSC = "https://www.saferproducts.gov/RestWebServices/"
MAX_BYTES = 8_000_000


def fetch(url: str) -> bytes:
    """GET one CPSC API URL (the only host this Actor calls), with a timeout and a size cap."""
    if not url.startswith(CPSC):
        raise ValueError("only the CPSC recall API is fetched")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; recall-checker/1.0)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
        body = r.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("answer too large")
    return body


def products_from(inp: dict) -> list[dict]:
    """The single product form plus the batch list ("Brand | Product | UPC", one per line), each as {id, brand, product, upc}."""
    inp = inp or {}
    out = []
    if str(inp.get("brand") or "").strip() or str(inp.get("product") or "").strip():
        out.append({"brand": str(inp.get("brand") or "").strip(), "product": str(inp.get("product") or "").strip(),
                    "upc": str(inp.get("upc") or "").strip() or None})
    lines = inp.get("products") or []
    lines = lines.splitlines() if isinstance(lines, str) else lines
    for line in lines:
        if isinstance(line, dict):
            out.append({"brand": str(line.get("brand") or "").strip(), "product": str(line.get("product") or "").strip(),
                        "upc": str(line.get("upc") or "").strip() or None})
        elif isinstance(line, str) and line.strip():
            parts = [p.strip() for p in line.split("|")]
            out.append({"brand": parts[0], "product": parts[1] if len(parts) > 1 else "", "upc": (parts[2] if len(parts) > 2 else "") or None})
    return [{"id": f"p{i}", **p} for i, p in enumerate(out, 1)]


def row_of(p: dict, r: dict) -> dict:
    top = (r["matches"] or r["possible"] or [{}])[0]
    return {"id": p["id"], "brand": r["brand"], "product": r["product"], "upc": r["upc"], "status": r["status"], "summary": r["summary"],
            "recall_title": top.get("title"), "recall_date": top.get("date"), "recall_url": top.get("url"), "hazard": top.get("hazard"),
            "remedy": top.get("remedy"), "units": top.get("units"), "match_on": top.get("match_on"),
            "matches": r["matches"], "possible": r["possible"], "checked_at": r["checked_at"], "source_url": r["source_url"],
            "origin": r["origin"]}


def _state(v) -> tuple[int, bool]:
    if isinstance(v, dict):
        v, paid = v.get("index"), bool(v.get("paid"))
    else:
        paid = False
    try:
        return max(0, int(v or 0)), paid
    except (TypeError, ValueError):
        return 0, False


def summary(rows: list, total: int, stopped: str | None = None) -> str:
    if len(rows) == 1 and total == 1:
        return rows[0]["summary"]
    n = {s: sum(1 for r in rows if r["status"] == s) for s in ("recalled", "possible", "none", "unverified")}
    out = f"{len(rows)} product(s): {n['recalled']} recalled, {n['possible']} possible, {n['none']} none, {n['unverified']} unverified"
    if len(rows) < total:
        out += f"; {total - len(rows)} not checked: {stopped or 'stopped early'}"
    return out


async def run_products(products, check, push, charge, log=print, get_state=None, set_state=None, prior=None):
    """Check each product, charge it (only when the API answered), then deliver its row. Returns (rows, stopped)."""
    index, paid = _state(await get_state()) if get_state else (0, False)
    rows, stopped = list(prior or [])[:index], None
    for i in range(index, len(products)):
        p = products[i]
        try:
            r = check(p["product"], p["brand"], p["upc"])
        except Exception as e:  # one bad product never stops the batch, and never reads as "none"
            r = {"product": p["product"], "brand": p["brand"], "upc": p["upc"], "status": "unverified", "matches": [], "possible": [],
                 "checked_at": None, "source_url": None, "origin": "MIRROR", "summary": f"UNVERIFIED: could not check ({type(e).__name__})"}
        res = None
        if r["status"] != "unverified" and not (paid and i == index):
            try:
                res = await charge(event_name=EVENT, count=1)
            except Exception as e:
                log(f"charge failed ({type(e).__name__}); stopping so no result is delivered unpaid")
                stopped = "the charge failed"
                break
            if getattr(res, "event_charge_limit_reached", False) and not getattr(res, "charged_count", 1):
                stopped = "your charge limit was reached"
                break
            if set_state:
                await set_state({"index": i, "paid": True})
        row = row_of(p, r)
        await push(row)
        rows.append(row)
        if set_state:
            await set_state({"index": i + 1, "paid": False})
        if getattr(res, "event_charge_limit_reached", False):
            stopped = "your charge limit was reached"
            break
    return rows, stopped


async def main():
    async with Actor:
        products = products_from(await Actor.get_input())
        if not products:
            await Actor.set_status_message("No product given: add a brand and a product name", is_terminal=True)
            return
        prior = ((await Actor.get_value("OUTPUT")) or {}).get("results") or []

        def check(product, brand, upc):
            return check_product(product, brand, upc, fetch=fetch, cache_dir=CACHE)
        rows, stopped = await run_products(products, check, Actor.push_data, Actor.charge, log=Actor.log.warning, prior=prior,
                                           get_state=lambda: Actor.get_value(STATE_KEY), set_state=lambda v: Actor.set_value(STATE_KEY, v))
        line = summary(rows, len(products), stopped)
        await Actor.set_value("OUTPUT", {"summary": line, "checked": len(rows), "total": len(products), "results": rows})
        await Actor.set_status_message(line, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
