"""Compatibility check for one PC build given as named parts (Lane C; the PC build compatibility Actor).

check_build(parts) -> {"verdict": pass|fail|uncertain, "complete": bool, "summary", "rules_run", "missing_parts", "problems",
                       "checks": [{rule_id, verdict, reason, parts, sources, origin}],
                       "parts": {category: {"name", "attrs", "maker_data": {attr: source}}}, "notes"}
parts: {"cpu"|"motherboard"|"memory"|"gpu"|"psu"|"case"|"cooler": {"name": str, <spec>: value, ...}, "storage": [{...}]}

Specs the caller gives are used as given (sockets and memory types upper-cased, numbers read from strings). A spec the caller
leaves out is filled from our maker data only when we hold that exact part (RTX 5070 Ti cards by brand and model, and the
coolers, cases and boards in depth_data.json), and the source is cited, with a caveat when the figure is a sibling model's or
a chipset estimate. Anything still unknown makes its check uncertain, never a guess. A part we cannot read, an unknown key or
a bad number makes the whole build uncertain and names it. A build missing parts never says a plain PASS: the summary says
which parts were not given. The rules are check_fit's own.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import check_fit
from .depth import _find
from .normalize import gpu_key
from .power import _chipset
from .tables import GPU_POWER

HERE = Path(__file__).resolve().parent
CATEGORIES = ("cpu", "motherboard", "memory", "gpu", "psu", "case", "cooler")
KNOWN_KEYS = set(CATEGORIES) | {"storage"}
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
NUMBERS = {"tdp_w", "max_power_w", "memory_slots", "memory_max_speed_mhz", "m2_slots", "sata_ports", "modules", "speed_mhz",
           "length_mm", "board_power_w", "rec_psu_w", "wattage", "pcie_16pin", "pcie_8pin", "max_gpu_length_mm", "max_cooler_height_mm",
           "height_mm", "radiator_mm"}
POSITIVE = {"tdp_w", "max_power_w", "memory_slots", "modules", "length_mm", "board_power_w", "rec_psu_w", "wattage",
            "max_gpu_length_mm", "max_cooler_height_mm", "height_mm", "radiator_mm"}  # 0 here means unknown, never a pass
LISTS = {"sockets", "motherboard_form_factors", "psu_form_factors", "radiator_mounts_mm"}
UPPER = {"socket", "memory_type", "type"}  # am5 and AM5 are the same socket; ddr5 and DDR5 the same memory
BRANDS = {"MSI": r"\bmsi\b", "GIGABYTE": r"\bgigabyte\b|\bgv-n", "ASUS": r"\basus\b|\b(prime|proart|tuf)-?rtx", "PNY": r"\bpny\b|\bvcg"}
CHIPSET_ESTIMATE = "chipset reference figure from NVIDIA or AMD (tables.GPU_POWER), an estimate, not this card's maker page"


def _load(name):
    return json.loads((HERE / name).read_text())


def _brand_ok(row: dict, name: str) -> bool:
    """A maker row applies only when the title names that maker (a Zotac 'Prime' is not an ASUS Prime)."""
    brand = (row.get("model") or "").split()[0].upper()
    return bool(re.search(BRANDS.get(brand, r"$^"), name, re.I))


def _cite(row: dict) -> str:
    note = "" if row.get("confidence") == "exact" else f" (figure for a sibling model, confidence: {row.get('confidence')})"
    return row["source"] + note


def _gpu_maker(name: str) -> dict:
    """Maker length and recommended PSU, only for an RTX 5070 Ti title that names the brand and model we hold (power.py's guard)."""
    if _chipset(name) != "RTX 5070 Ti":
        return {}
    out = {}
    row = next((r for r in _load("gpu_lengths.json")["models"] if re.search(r["match"], name, re.I) and _brand_ok(r, name)), None)
    if row and row.get("length_mm"):
        out["length_mm"] = (row["length_mm"], _cite(row))
    row = next((r for r in _load("gpu_power.json")["models"] if re.search(r["match"], name, re.I) and _brand_ok(r, name)), None)
    if row and row.get("rec_psu_w"):
        out["rec_psu_w"] = (row["rec_psu_w"], _cite(row))
    return out


def _maker(cat: str, name: str) -> dict:
    if cat == "gpu":
        return _gpu_maker(name)
    if cat not in DEPTH_FIELDS:
        return {}
    table, fields = DEPTH_FIELDS[cat]
    row = _find(_load("depth_data.json")[table], name)
    return {f: (row[f], row["source"]) for f in fields if row and row.get(f) is not None}


def _clean(attrs: dict, problems: list, cat: str) -> dict:
    out = {}
    for k, v in attrs.items():
        if v in (None, ""):
            continue
        if k in NUMBERS:
            try:
                v = float(v) if isinstance(v, str) else v
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ValueError
                v = int(v) if float(v).is_integer() else v
            except (TypeError, ValueError):
                problems.append(f"{cat}.{k} is not a number ({v!r})")
                continue
            if k in POSITIVE and v <= 0:
                problems.append(f"{cat}.{k} must be above 0 ({v!r}); treated as unknown")
                continue
        if k in LISTS and isinstance(v, str):
            v = [v]
        if k in UPPER and isinstance(v, str):
            v = v.strip().upper()
        if k == "sockets" and isinstance(v, list):
            v = [s.strip().upper() if isinstance(s, str) else s for s in v]
        out[k] = v
    return out


def _resolve(cat: str, given, problems: list) -> dict | None:
    if isinstance(given, str):  # a part named only: read it as its name
        given = {"name": given}
    if not isinstance(given, dict):
        problems.append(f"{cat} could not be read (give an object with a name and specs)")
        return None
    given = dict(given)
    name = str(given.pop("name", "") or "")
    attrs = _clean(given, problems, cat)
    if cat == "gpu" and not attrs.get("chipset") and _chipset(name):
        attrs["chipset"] = _chipset(name)
    maker = {}
    for k, (v, src) in _maker(cat, name).items():
        if k not in attrs:  # the caller's own spec wins
            attrs[k], maker[k] = v, src
    if cat == "gpu" and attrs.get("chipset") and GPU_POWER.get(gpu_key(attrs["chipset"])):
        for k in ("board_power_w", "power_connector", "rec_psu_w"):  # check_fit falls back to the chipset table for these
            if k not in attrs:
                maker.setdefault(k, CHIPSET_ESTIMATE)
    return {"name": name, "attrs": attrs, "maker_data": maker}


def check_build(parts) -> dict:
    problems = []
    if not isinstance(parts, dict):
        parts, problems = {}, ["the build could not be read (give an object of parts)"]
    problems += [f"unknown part key '{k}' (use {', '.join(sorted(KNOWN_KEYS))})" for k in parts if k not in KNOWN_KEYS]
    resolved = {}
    for cat in CATEGORIES:
        if cat in parts:
            r = _resolve(cat, parts[cat], problems)
            if r:
                resolved[cat] = r
    drives_in = parts.get("storage")
    if drives_in is not None and not isinstance(drives_in, list):
        problems.append("storage could not be read (give a list of drives)")
        drives_in = []
    drives = [d for d in (_resolve("storage", d, problems) for d in drives_in or []) if d]
    cards = [{"category": cat, "attrs": p["attrs"]} for cat, p in resolved.items()] + [{"category": "storage", "attrs": d["attrs"]} for d in drives]
    out = check_fit(cards)
    checks = []
    for c in out["checks"]:
        cats = [k for k in RULE_PARTS.get(c["rule_id"], ()) if k in resolved]
        used = RULE_ATTRS.get(c["rule_id"], set())
        sources = sorted({src for k in cats for a, src in resolved[k]["maker_data"].items() if a in used})
        checks.append({**c, "parts": [resolved[k]["name"] or k for k in cats], "sources": sources,
                       "origin": "MIRROR (dated maker data, Oct 24 2026)" if sources else "your input"})
    n = {v: sum(1 for c in checks if c["verdict"] == v) for v in ("pass", "fail", "uncertain")}
    missing = [c for c in CATEGORIES if c not in resolved]
    verdict = out["verdict"]
    if problems and verdict == "pass":
        verdict = "uncertain"
    complete = not missing and not problems
    if verdict == "fail":
        head = f"FAIL: {out['reasons'][0]}"
    elif problems:
        head = f"UNCERTAIN: {problems[0]}"
    elif verdict == "uncertain":
        head = f"UNCERTAIN: {out['reasons'][0]}"
    else:
        head = "PASS" if complete else f"PASS for the {len(checks)} rule(s) that could run; not given: {', '.join(missing)}"
    summary = f"{head} ({len(checks)} checks: {n['pass']} pass, {n['fail']} fail, {n['uncertain']} uncertain)"
    return {"verdict": verdict, "complete": complete, "summary": summary, "rules_run": len(checks), "missing_parts": missing,
            "problems": problems, "checks": checks, "notes": out["notes"], "parts": {**resolved, **({"storage": drives} if drives else {})}}
