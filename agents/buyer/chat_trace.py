"""Small, safe summary of the seller round for the buyer chat."""

import re
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit


def _safe(value: object) -> str:
    value = re.split(r"[\x00-\x1f\x7f]", str(value), maxsplit=1)[0].strip()
    return " ".join(value.split())[:160]


def _source(value: object) -> str:
    raw = str(value) if isinstance(value, str) else ""
    if not raw or len(raw) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        return "source unavailable"
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return "source unavailable"
    except ValueError:
        return "source unavailable"
    return raw


def round_trace(
    sellers: Sequence[object],
    bids: Sequence[Mapping[str, object]],
    cards: Mapping[str, Mapping[str, object]],
    winner: Mapping[str, object] | None,
) -> str:
    """Return one line from round facts, excluding seller text and approval data."""
    asked = [_safe(s) for s in sellers if _safe(s)]
    by_id = {str(b.get("id")): b for b in bids if isinstance(b, Mapping) and b.get("id") is not None}
    card_by_id = {str(k): v for k, v in cards.items() if isinstance(v, Mapping)} if isinstance(cards, Mapping) else {}

    parts = [f"Round: asked {', '.join(asked) or 'no sellers'}"]
    vetoes = []
    for bid_id, card in sorted(card_by_id.items(), key=lambda item: (_safe(by_id.get(item[0], {}).get("supplier_id", "")), item[0])):
        if card.get("recommendation") != "veto":
            continue
        bid = by_id.get(bid_id, {})
        if not bid:
            continue
        seller = _safe(bid.get("supplier_id", "unknown seller"))
        warnings = card.get("warnings", [])
        source = ""
        if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes)):
            for warning in warnings:
                if isinstance(warning, Mapping) and warning.get("source_url"):
                    source = _source(warning["source_url"])
                    break
        vetoes.append(f"{seller} ({source or 'source unavailable'})")
    if vetoes:
        parts.append("vetoed " + ", ".join(vetoes))

    selected = winner if isinstance(winner, Mapping) else None
    if isinstance(selected, Mapping) and selected.get("supplier_id"):
        parts.append(f"recommended {_safe(selected['supplier_id'])}")
    else:
        parts.append("no reviewed recommendation")
    return "; ".join(parts) + "."
