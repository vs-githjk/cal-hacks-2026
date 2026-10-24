"""Fit depth for build goals (Lane C, issue #159): cooler height vs case clearance, and RAM generation and form vs the board.

    cooler_vs_case(cooler_name, case_name)            -> {verdict, reason, source}
    ram_vs_board(board_name, memory_type, form="DIMM") -> {verdict, reason, source}

Maker data (mm and memory type) is in depth_data.json, taken from parts confirmed on maker domains. A name we do not hold is
"uncertain", never a guess. The rules themselves are the checker's own (fit.cooler_height, fit.ram_type, fit.ram_form).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import UNCERTAIN, check_fit

DATA = Path(__file__).resolve().parent / "depth_data.json"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _find(rows: list[dict], name: str) -> dict | None:
    """Exact match on the normalized name (lowercase, whitespace collapsed); no substring or loose matching."""
    n = _norm(name)
    return next((r for r in rows if _norm(r["name"]) == n), None)


def _card(cat: str, name: str, **attrs) -> dict:
    return {"id": f"{cat}:{name}", "category": cat, "name": name, "attrs": attrs, "origin": "MIRROR", "source": "data/fit_checker/depth_data.json"}


def _result(out: dict, rule_id: str, source: str | None) -> dict:
    c = next(c for c in out["checks"] if c["rule_id"] == rule_id)
    return {"verdict": c["verdict"], "reason": c["reason"], "source": source}


def cooler_vs_case(cooler_name: str, case_name: str) -> dict:
    data = json.loads(DATA.read_text())
    cooler, case = _find(data["coolers"], cooler_name), _find(data["cases"], case_name)
    if not cooler or not case:
        who = "cooler" if not cooler else "case"
        return {"verdict": UNCERTAIN, "reason": f"{who} not in our maker data", "source": None}
    out = check_fit([_card("cooler", cooler["name"], type="air", height_mm=cooler["height_mm"], sockets=cooler["sockets"]),
                     _card("case", case["name"], max_cooler_height_mm=case["max_cooler_height_mm"])])
    return _result(out, "fit.cooler_height", f"{cooler['source']} | {case['source']}")


def ram_vs_board(board_name: str, memory_type: str | None, form: str | None = "DIMM") -> dict:
    board = _find(json.loads(DATA.read_text())["boards"], board_name)
    if not board:
        return {"verdict": UNCERTAIN, "reason": "board not in our maker data", "source": None}
    mem_attrs = {k: v for k, v in (("type", memory_type), ("form", form)) if v}
    out = check_fit([_card("motherboard", board["name"], memory_type=board["memory_type"], memory_form=board["memory_form"]),
                     _card("memory", "kit", **mem_attrs)])
    rules = [c for c in out["checks"] if c["rule_id"] in ("fit.ram_type", "fit.ram_form")]
    worst = next((c for c in rules if c["verdict"] == "fail"), None) or next((c for c in rules if c["verdict"] == UNCERTAIN), None) or rules[0]
    return {"verdict": worst["verdict"], "reason": worst["reason"], "source": board["source"]}
