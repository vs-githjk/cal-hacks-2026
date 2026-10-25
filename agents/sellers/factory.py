"""SellerConfig loading and checking (contracts/SellerConfig.schema.json) and the seller dict policy.make_bid reads.

Light on purpose: only jsonschema and the standard library, so the Seller Kit API can import it without uagents.
A refused config raises ConfigError (a ValueError) whose `.errors` is a list of {field, message}; the message text
names every field so a /sell form or a Claude skill can show them.
"""
import copy
import json
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "SellerConfig.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(SCHEMA)

SKU_RE = re.compile(r"^[a-z0-9][a-z0-9 .+/-]{0,79}$")
# Ports already used by the repo's services and agents; custom sellers start looking at 8016 and skip these.
RESERVED_PORTS = {3000, 3100, 8001, 8003, 8004, 8010, 8011, 8012, 8013, 8014, 8015, 8016,
                  8787, 8788, 8789, 8790, 8791}
# What each reserved port is for, so a refused config says which service it would collide with.
PORT_OWNERS = {3000: "SpacetimeDB", 3100: "the web app", 8001: "the buyer agent", 8003: "the advocate agent",
               8010: "the seller Bureau", 8011: "seller_1", 8012: "seller_2",
               8013: "seller_3", 8014: "seller_4", 8015: "seller_5",
               8016: "seller_6 (Central Computers MIRROR)", 8787: "the shield service"}
# Ids of the Tech Bazaar agents; a custom seller must not sign with their keys. Hardcoded so factory stays uagents-free.
RESERVED_IDS = {"buyer", "advocate", "shield"}
SELLER_ID_RE = re.compile(r"^seller_\d+$")


class ConfigError(ValueError):
    """A SellerConfig that cannot be used. `errors` is [{field, message}], `str()` lists them all."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("; ".join(f"{e['field']}: {e['message']}" for e in errors))


def _dotted(path) -> str:
    return ".".join(str(p) for p in path) or "config"


def _bad_url(url) -> str | None:
    if not isinstance(url, str) or any(ch.isspace() or ord(ch) < 32 for ch in url):
        return "must be a plain http or https URL"
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return "is not a valid URL"
    if parsed.scheme not in ("http", "https") or not host:
        return "must be an http or https URL with a host"
    return None


def validate_config(cfg, *, catalog: bool = False) -> dict:
    """Return a normalized deep copy of cfg, or raise ConfigError naming every bad field.
    `catalog=True` is only for the built-in sellers (sellers.json), which own the reserved seller_N ids."""
    if not isinstance(cfg, dict):
        raise ConfigError([{"field": "config", "message": "must be a JSON object"}])
    errors = [{"field": _dotted(e.absolute_path), "message": e.message}
              for e in sorted(_VALIDATOR.iter_errors(cfg), key=lambda e: [str(p) for p in e.absolute_path])]
    if errors:
        raise ConfigError(errors)

    cfg = copy.deepcopy(cfg)
    err = lambda field, message: errors.append({"field": field, "message": message})
    # Compare the id the way common.register_custom_seller builds its seed env name (- becomes _), so 'seller-1'
    # cannot read seller_1's seed through SELLER_1_AGENT_SEED.
    # A trailing '_agent' is stripped too: 'seller_1_agent' and 'buyer_agent' fall back to the built-in's
    # <NAME>_AGENT_SEED, so they are the same reserved ids.
    folded_id = cfg["id"].replace("-", "_").removesuffix("_agent")
    if not catalog and (folded_id in RESERVED_IDS or SELLER_ID_RE.match(folded_id)):
        err("id", "is reserved for a Fish Market agent")
    port = cfg.get("port")
    if port in RESERVED_PORTS:
        err("port", f"{port} is used by {PORT_OWNERS.get(port, 'a Fish Market service')}")
    pricing = cfg["pricing"]
    mode = pricing["mode"]
    if mode == "fixed_margin":
        if "margin_pct" not in pricing:
            err("pricing.margin_pct", "is required when pricing.mode is fixed_margin")
        if "discount" in pricing:
            err("pricing.discount", "is not used when pricing.mode is fixed_margin")
    else:
        if "discount" not in pricing:
            err("pricing.discount", "is required when pricing.mode is discount (use 0 for none)")
        if "margin_pct" in pricing:
            err("pricing.margin_pct", "is not used when pricing.mode is discount")
    base_key, other_key = ("cost", "price") if mode == "fixed_margin" else ("price", "cost")
    margin = pricing.get("margin_pct", 0)

    def bid_ceiling(raw: float) -> float:
        return round(raw * (1 + margin / 100), 2) if mode == "fixed_margin" else raw

    cfg.setdefault("shipping", 0)
    cfg.setdefault("perks", [])
    cfg.setdefault("claims", [])
    for sku, ls in cfg["listings"].items():
        at = f"listings.{sku}"
        if not SKU_RE.match(sku):
            err(at, "sku must be lowercase letters, digits, spaces or . + / - (80 characters at most)")
        if bad := _bad_url(ls["listing_url"]):
            err(f"{at}.listing_url", bad)
        ls.setdefault("page_condition", ls["condition"])
        ls.setdefault("variant", "retail")
        ls.setdefault("attrs", {})
        ls.setdefault("alt_lines", [])
        floors = ls["floor_by_condition"]

        lines = [(f"{at}", ls)]
        seen = {ls["condition"]}
        for i, alt in enumerate(ls["alt_lines"]):
            alt_at = f"{at}.alt_lines.{i}"
            if alt["condition"] in seen:
                err(f"{alt_at}.condition", f"{alt['condition']} is already offered for this sku")
            seen.add(alt["condition"])
            alt.setdefault("page_condition", alt["condition"])
            alt.setdefault("listing_url", ls["listing_url"])
            if bad := _bad_url(alt["listing_url"]):
                err(f"{alt_at}.listing_url", bad)
            lines.append((alt_at, alt))

        for where, line in lines:
            if base_key not in line:
                err(f"{where}.{base_key}", f"is required when pricing.mode is {mode}")
                continue
            if other_key in line:
                err(f"{where}.{other_key}", f"is not used when pricing.mode is {mode}")
            cond = line["condition"]
            if cond not in floors:
                err(f"{at}.floor_by_condition", f"needs a floor for {cond}, which this sku is offered in")
                continue
            ceiling = bid_ceiling(line[base_key])
            if floors[cond] > ceiling:
                err(f"{at}.floor_by_condition.{cond}",
                    f"floor {floors[cond]:.2f} is above the {'marked-up' if mode == 'fixed_margin' else 'list'} "
                    f"price {ceiling:.2f}, so the agent could never bid")
        for cond in floors:
            if cond not in seen:
                err(f"{at}.floor_by_condition.{cond}", f"has a floor but no line offers {cond}")
    if errors:
        raise ConfigError(errors)
    return cfg


def load_config(path) -> dict:
    """Read a SellerConfig JSON file, validate and normalize it. ValueError on any problem."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError([{"field": "config", "message": f"cannot read {path}: {e.__class__.__name__}"}]) from e
    except json.JSONDecodeError as e:
        raise ConfigError([{"field": "config", "message": f"not valid JSON ({e.msg} at line {e.lineno})"}]) from e
    return validate_config(raw)


def seller_from_config(cfg: dict, *, catalog: bool = False) -> dict:
    """The dict policy.make_bid reads. Validates first (so a hand-built dict gets the same checks).

    Each listing gets `price` (list price; for fixed_margin cost marked up), `floor` for its primary condition and
    `alt_lines` (each with condition, page_condition, price, floor, listing_url). `discount` is applied by the policy."""
    cfg = validate_config(cfg, catalog=catalog)
    pricing = cfg["pricing"]
    fixed = pricing["mode"] == "fixed_margin"
    margin = pricing.get("margin_pct", 0)

    def listed(line: dict) -> float:
        return round(line["cost"] * (1 + margin / 100), 2) if fixed else line["price"]

    listings = {}
    for sku, ls in cfg["listings"].items():
        floors = ls["floor_by_condition"]
        listings[sku] = {
            "price": listed(ls), "floor": floors[ls["condition"]], "condition": ls["condition"],
            "page_condition": ls["page_condition"], "variant": ls["variant"], "listing_url": ls["listing_url"],
            "attrs": ls["attrs"],
            "alt_lines": [{"condition": a["condition"], "page_condition": a["page_condition"], "price": listed(a),
                           "floor": floors[a["condition"]], "listing_url": a["listing_url"]}
                          for a in ls["alt_lines"]]}
    return {"id": cfg["id"], "name": cfg["name"], "owner": cfg.get("owner"), "archetype": cfg["archetype"],
            "origin": cfg["origin"], "discount": 0 if fixed else pricing["discount"],
            "margin_pct": margin if fixed else None, "shipping": cfg["shipping"],
            "perks": cfg["perks"], "claims": cfg["claims"], "listings": listings}


def pick_port(cfg: dict, start: int = 8016) -> int:
    """The config's own port, else the first free local port from `start` that no repo service uses."""
    if cfg.get("port"):
        return int(cfg["port"])  # validate_config already refused reserved ports
    for port in range(start, start + 200):
        if port in RESERVED_PORTS:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"no free port between {start} and {start + 199}")
