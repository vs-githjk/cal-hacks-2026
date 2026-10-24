"""Compatibility check for one PC build given as named parts (Lane C; the PC build compatibility Actor).

check_build(parts) -> {"verdict": pass|fail|uncertain, "summary", "checks": [{rule_id, verdict, reason, parts, sources}],
                       "parts": {category: {"name", "attrs", "maker_data": {attr: source}}}, "notes"}
parts: {"cpu"|"motherboard"|"memory"|"gpu"|"psu"|"case"|"cooler": {"name": str, <spec>: value, ...}, "storage": [{...}]}

Specs the caller gives are used as given. A spec the caller leaves out is filled from our maker data only when we hold that
exact part (RTX 5070 Ti cards by model, and the coolers, cases and boards in depth_data.json), and the maker page is cited.
Anything still unknown makes its check uncertain, never a guess. The rules are check_fit's own.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import check_fit
from .depth import _find
from .power import _chipset

HERE = Path(__file__).resolve().parent
CATEGORIES = ("cpu", "motherboard", "memory", "gpu", "psu", "case", "cooler")
RULE_PARTS = {"fit.cpu_socket": ("cpu", "motherboard"), "fit.ram_type": ("motherboard", "memory"), "fit.ram_form": ("motherboard", "memory"),
              "fit.ram_slots": ("motherboard", "memory"), "fit.psu_wattage": ("cpu", "gpu", "psu"), "fit.gpu_connectors": ("gpu", "psu"),
              "fit.gpu_length": ("gpu", "case"), "fit.cooler_socket": ("cpu", "cooler"), "fit.cooler_height": ("cooler", "case"),
              "fit.form_factor": ("motherboard", "case"), "fit.psu_form_factor": ("psu", "case"), "fit.storage": ("motherboard", "storage")}
RULE_ATTRS = {"fit.cpu_socket": {"socket", "chipset_series"}, "fit.ram_type": {"memory_type", "type", "memory_max_speed_mhz", "speed_mhz"},
              "fit.ram_form": {"memory_form", "form"}, "fit.ram_slots": {"modules", "memory_slots"},
              "fit.psu_wattage": {"wattage", "rec_psu_w", "board_power_w", "tdp_w", "max_power_w"},
              "fit.gpu_connectors": {"power_connector", "pcie_16pin", "pcie_8pin"}, "fit.gpu_length": {"length_mm", "max_gpu_length_mm"},
              "fit.cooler_socket": {"sockets", "socket"}, "fit.cooler_height": {"height_mm", "max_cooler_height_mm", "radiator_mm", "radiator_mounts_mm"},
              "fit.form_factor": {"form_factor", "motherboard_form_factors"}, "fit.psu_form_factor": {"form_factor", "psu_form_factors"},
              "fit.storage": {"m2_slots", "sata_ports", "interface"}}  # a check cites a maker page only for a spec it used
DEPTH_FIELDS = {"cooler": ("coolers", ("height_mm", "sockets")), "case": ("cases", ("max_cooler_height_mm", "max_gpu_length_mm")),
                "motherboard": ("boards", ("memory_type", "memory_form"))}


def _load(name):
    return json.loads((HERE / name).read_text())


def _gpu_maker(name: str) -> dict:
    """Maker length and recommended PSU, only for an RTX 5070 Ti title that names a model we hold (power.py's guard)."""
    if _chipset(name) != "RTX 5070 Ti":
        return {}
    out = {}
    row = next((r for r in _load("gpu_lengths.json")["models"] if re.search(r["match"], name, re.I)), None)
    if row and row.get("length_mm"):
        out["length_mm"] = (row["length_mm"], row["source"])
    row = next((r for r in _load("gpu_power.json")["models"] if re.search(r["match"], name, re.I)), None)
    if row and row.get("rec_psu_w"):
        out["rec_psu_w"] = (row["rec_psu_w"], row["source"])
    return out


def _maker(cat: str, name: str) -> dict:
    if cat == "gpu":
        return _gpu_maker(name)
    if cat not in DEPTH_FIELDS:
        return {}
    table, fields = DEPTH_FIELDS[cat]
    row = _find(_load("depth_data.json")[table], name)
    return {f: (row[f], row["source"]) for f in fields if row and row.get(f) is not None}


def _resolve(cat: str, given) -> dict:
    given = dict(given or {})
    name = str(given.pop("name", "") or "")
    attrs = {k: v for k, v in given.items() if v not in (None, "")}
    if cat == "gpu" and not attrs.get("chipset") and _chipset(name):
        attrs["chipset"] = _chipset(name)
    maker = {}
    for k, (v, src) in _maker(cat, name).items():
        if k not in attrs:  # the caller's own spec wins
            attrs[k], maker[k] = v, src
    return {"name": name, "attrs": attrs, "maker_data": maker}


def check_build(parts: dict) -> dict:
    parts = parts or {}
    resolved = {cat: _resolve(cat, parts[cat]) for cat in CATEGORIES if isinstance(parts.get(cat), dict)}
    drives = [_resolve("storage", d) for d in parts.get("storage") or [] if isinstance(d, dict)]
    cards = [{"category": cat, "attrs": p["attrs"]} for cat, p in resolved.items()] + [{"category": "storage", "attrs": d["attrs"]} for d in drives]
    out = check_fit(cards)
    checks = []
    for c in out["checks"]:
        cats = [k for k in RULE_PARTS.get(c["rule_id"], ()) if k in resolved or (k == "storage" and drives)]
        used = RULE_ATTRS.get(c["rule_id"], set())
        sources = sorted({src for k in cats for a, src in (resolved.get(k) or {}).get("maker_data", {}).items() if a in used})
        checks.append({**c, "parts": [resolved[k]["name"] or k for k in cats if k in resolved], "sources": sources})
    n = {v: sum(1 for c in checks if c["verdict"] == v) for v in ("pass", "fail", "uncertain")}
    summary = f"{out['verdict'].upper()}: {out['reasons'][0]} ({len(checks)} checks: {n['pass']} pass, {n['fail']} fail, {n['uncertain']} uncertain)"
    return {"verdict": out["verdict"], "summary": summary, "checks": checks, "notes": out["notes"],
            "parts": {**resolved, **({"storage": drives} if drives else {})}}
