"""docyx/pc-part-dataset rows -> SpecCards with attrs (contracts/SpecCard.schema.json)."""
import re

from .tables import CASE_TYPE_BOARDS, GPU_POWER, MICROARCH_SOCKET, SOCKET_MEMORY, SOCKETS_WITH_M2

CATEGORY = {"video-card": "gpu", "power-supply": "psu", "cpu-cooler": "cooler", "internal-hard-drive": "storage"}
SOURCE = "dataset:docyx/pc-part-dataset"
NOT_DESKTOP = re.compile(r"Threadripper|EPYC|Xeon|\bi[79]-\d{4,5}XE?\b", re.I)
CHIPSET = re.compile(r"(?<![A-Z0-9])([ABHXZQ])(\d)(\d\d)(E?)(?=[^0-9]|$)")


def board_form_factor(ff):
    return {"Thin Mini ITX": "Mini ITX", "E-ATX": "EATX"}.get(ff, ff)


def gpu_key(chipset):
    key = re.sub(r"^(GeForce|Radeon)\s+", "", chipset or "")
    return re.sub(r"\s+\d+\s?GB$", "", key).strip()


def chipset_of(name):
    m = CHIPSET.search(name or "")
    return (m.group(0), int(m.group(2))) if m else (None, None)


def memory_type_from_name(name):
    if re.search(r"\bD(?:DR)?4\b", name or ""):
        return "DDR4"
    if re.search(r"\bD(?:DR)?5\b", name or ""):
        return "DDR5"
    if re.search(r"\bDDR3", name or ""):
        return "DDR3"
    return None


def _attrs(cat, row):
    name = row.get("name", "")
    if cat == "cpu":
        arch = row.get("microarchitecture")
        socket = None if NOT_DESKTOP.search(name) else MICROARCH_SOCKET.get(arch)
        vendor = "AMD" if "AMD" in name or "Ryzen" in name else "Intel" if "Intel" in name or "Core" in name else None
        return {"socket": socket, "microarchitecture": arch, "tdp_w": row.get("tdp"), "vendor": vendor}
    if cat == "motherboard":
        socket = row.get("socket")
        chipset, series = chipset_of(name)
        return {"socket": socket, "chipset": chipset, "chipset_series": series,
                "form_factor": board_form_factor(row.get("form_factor")),
                "memory_type": memory_type_from_name(name) or SOCKET_MEMORY.get(socket),
                "memory_slots": row.get("memory_slots"), "max_memory_gb": row.get("max_memory"),
                "m2_slots": 1 if socket in SOCKETS_WITH_M2 else None}
    if cat == "memory":
        gen, speed = (row.get("speed") or [None, None])[:2]
        modules, size = (row.get("modules") or [None, None])[:2]
        return {"type": f"DDR{gen}" if gen else None, "speed_mhz": speed, "modules": modules, "module_gb": size}
    if cat == "gpu":
        key = gpu_key(row.get("chipset"))
        power = GPU_POWER.get(key, {})
        return {"chipset": key, "length_mm": row.get("length"), "board_power_w": power.get("board_power_w"),
                "rec_psu_w": power.get("rec_psu_w"), "power_connector": power.get("connector")}
    if cat == "psu":
        return {"wattage": row.get("wattage"), "form_factor": row.get("type")}
    if cat == "case":
        boards = CASE_TYPE_BOARDS.get(row.get("type"))
        return {"type": row.get("type"), "motherboard_form_factors": sorted(boards) if boards else None}
    if cat == "cooler":
        size = row.get("size")
        return {"type": "aio", "radiator_mm": size} if size else {"type": "air"}
    if cat == "storage":
        return {"interface": row.get("interface"), "form_factor": row.get("form_factor")}
    return {}


def from_dataset(dataset_category, row):
    cat = CATEGORY.get(dataset_category, dataset_category)
    attrs = {k: v for k, v in _attrs(cat, row).items() if v is not None}
    return {"id": f"{cat}:{row.get('name', '')}", "category": cat, "name": row.get("name", ""),
            "condition": "unknown", "attrs": attrs, "price": row.get("price"), "currency": "USD",
            "origin": "MIRROR", "source": SOURCE}
