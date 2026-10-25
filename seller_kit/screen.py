"""The Listing Injection Screen on a new shop's text (Lane C, #412 item 3b).

Before the Seller Kit writes a shop, or hands it to agents/sellers/factory.py, every piece of text a buyer agent could read from
it goes through data.injection_screen_actor.src.screen.screen_text: Bazaar Shield's rules, the classifier off, no key, no network.
Any rule that fires rejects the shop with the rule id and a fixed reason. Any error, or text the screen did not read, rejects it
too (fail closed). The text itself is never echoed, and neither is a field name taken from the shop: the errors name only the
config's own top-level fields.

screen_shop(cfg, screener) -> [] when clean, else [{"field", "message"}]; raises ShopScreenUnavailable when the screen could not run and TooDeep when the text nests too deeply to read.
"""
from __future__ import annotations

from typing import Any, Callable

MAX_DEPTH = 30
FREE_TEXT = ("title", "description", "sellerNotes", "seller_notes")  # not in the schema (the factory refuses them), screened anyway
REASON = ("This text reads as an instruction to a shopping agent or a request for a secret. "
          "Edit the text and send the shop again.")
UNAVAILABLE = "The injection screen could not run, so the shop was not written (it fails closed). Try again."


class ShopScreenUnavailable(Exception):
    pass


class TooDeep(Exception):
    """Free-form text nested past MAX_DEPTH: refused the way the factory refuses it, so no text is left unscreened."""


def default_screener() -> Callable[[str], dict]:
    from data.injection_screen_actor.src.screen import screen_text
    return screen_text


def _walk(value: Any, field: str, out: list[tuple[str, str]], depth: int = 0) -> None:
    """Every string in a free-form value, dict keys included (a key is text too)."""
    if depth > MAX_DEPTH:
        raise TooDeep()
    if isinstance(value, str):
        out.append((field, value))
    elif isinstance(value, dict):
        for k, v in value.items():
            _walk(str(k), field, out, depth + 1)
            _walk(v, field, out, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _walk(v, field, out, depth + 1)


def shop_texts(cfg: Any) -> list[tuple[str, str]]:
    """[(field, text)]: the title-like fields (name, sku keys, variant), the description-like ones (archetype, attrs) and the
    seller notes (owner, perks, claims), plus any title, description or sellerNotes key. `field` is a top-level name from the
    config schema, never shop-controlled text."""
    if not isinstance(cfg, dict):
        return []
    out: list[tuple[str, str]] = []
    for key in ("name", "owner", "archetype", "perks", "claims", *FREE_TEXT):
        if key in cfg:
            _walk(cfg[key], key, out)
    listings = cfg.get("listings")
    if isinstance(listings, dict):
        for sku, ls in listings.items():
            _walk(str(sku), "listings", out)
            if isinstance(ls, dict):
                for key in ("variant", "attrs", *FREE_TEXT):
                    if key in ls:
                        _walk(ls[key], "listings", out)
    return out


def screen_shop(cfg: Any, screener: Callable[[str], dict] | None = None) -> list[dict]:
    try:
        texts = shop_texts(cfg)
        if not texts:
            return []
        screen = screener or default_screener()
        errors: list[dict] = []
        seen: set = set()
        for field, text in texts:
            if not text.strip():
                continue
            r = screen(text)
            if not isinstance(r, dict) or r.get("screened") is not True:
                raise ShopScreenUnavailable("the screen did not read the text")
            rules = [str(x) for x in r.get("rule_ids") or []]
            if rules and (field, tuple(rules)) not in seen:
                seen.add((field, tuple(rules)))
                errors.append({"field": field, "message": f"Rejected by the injection screen (rule {', '.join(rules)}). {REASON}"})
        return errors
    except (ShopScreenUnavailable, TooDeep):
        raise
    except Exception as e:  # any failure of the screen: nothing is known, so nothing is written
        raise ShopScreenUnavailable(type(e).__name__) from None
