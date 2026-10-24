"""Fit checker (Lane C, c2). Pure functions; the model never decides fit.

check_fit(spec_cards) -> {"verdict": "pass"|"fail"|"uncertain", "reasons": [str], "rule_id": str,
                          "checks": [{"rule_id", "verdict", "reason"}], "notes": [str]}
Input: SpecCards (contracts/SpecCard.schema.json). A check runs only when both its parts are in the build.
Any unknown attr makes that check "uncertain", never a guess. Verdict: any fail -> fail, else any
uncertain -> uncertain, else pass. rule_id is the first failing (then first uncertain) check.
"""
import math

from .normalize import gpu_key
from .tables import (AMD_PPT_FACTOR, BIOS_RULES, CASE_TYPE_BOARDS, CASE_TYPE_PSU, GPU_POWER, INTEL_125W_BUDGET_W, LGA1151_CHIPSET_SERIES,
                     PSU_HEADROOM, REST_OF_SYSTEM_W)

PASS, FAIL, UNCERTAIN = "pass", "fail", "uncertain"
LARGE_BOARDS = {"EATX", "XL ATX", "SSI EEB", "SSI CEB", "HPTX"}


def _r(rule_id, verdict, reason, note=None):
    return {"rule_id": rule_id, "verdict": verdict, "reason": reason, "note": note}


def cpu_socket(cpu, board):
    cs, bs, arch = cpu.get("socket"), board.get("socket"), cpu.get("microarchitecture")
    if not cs or not bs:
        return _r("fit.cpu_socket", UNCERTAIN, "CPU or board socket unknown")
    if cs != bs:
        return _r("fit.cpu_socket", FAIL, f"CPU socket {cs} does not match board socket {bs}")
    series = board.get("chipset_series")
    if cs == "LGA1151" and arch in LGA1151_CHIPSET_SERIES:
        if series is None:
            return _r("fit.cpu_socket", UNCERTAIN, f"LGA1151 has two generations; board chipset unknown for {arch}")
        if series not in LGA1151_CHIPSET_SERIES[arch]:
            return _r("fit.cpu_socket", FAIL, f"{arch} does not run on a {board.get('chipset')} LGA1151 board")
    bios = BIOS_RULES.get((cs, series, arch))
    if bios and bios[0] == UNCERTAIN:
        return _r("fit.cpu_socket", UNCERTAIN, bios[1])
    return _r("fit.cpu_socket", PASS, f"socket {cs} matches", note=f"BIOS: {bios[1]}" if bios else None)


def ram_type(board, mem):
    bt, mt = board.get("memory_type"), mem.get("type")
    if not bt or not mt:
        return _r("fit.ram_type", UNCERTAIN, "board or memory type unknown")
    if bt != mt:
        return _r("fit.ram_type", FAIL, f"{mt} memory does not fit a {bt} board")
    note = None
    top, speed = board.get("memory_max_speed_mhz"), mem.get("speed_mhz")
    if top and speed and speed > top:
        note = f"RAM rated {speed} MT/s runs at the board's max {top} MT/s"
    return _r("fit.ram_type", PASS, f"{mt} matches", note=note)


def ram_slots(board, mem):
    modules, slots = mem.get("modules"), board.get("memory_slots")
    if not modules:
        return None
    if slots is None:
        if modules <= 2:  # every desktop board form factor has at least 2 DIMM slots
            return _r("fit.ram_slots", PASS, f"{modules} modules; boards have at least 2 slots")
        return _r("fit.ram_slots", UNCERTAIN, f"{modules} modules; board slot count unknown")
    if modules > slots:
        return _r("fit.ram_slots", FAIL, f"{modules} modules but the board has {slots} slots")
    return _r("fit.ram_slots", PASS, f"{modules} modules in {slots} slots")


def _gpu_power(gpu):
    row = GPU_POWER.get(gpu_key(gpu.get("chipset")), {})
    return (gpu.get("board_power_w") or row.get("board_power_w"), gpu.get("rec_psu_w") or row.get("rec_psu_w"),
            gpu.get("power_connector") or row.get("connector"))


def _cpu_power(cpu):
    if cpu.get("max_power_w"):
        return cpu["max_power_w"]
    tdp = cpu.get("tdp_w")
    if not tdp or cpu.get("vendor") not in ("AMD", "Intel"):
        return None
    if cpu["vendor"] == "AMD":
        return math.ceil(tdp * AMD_PPT_FACTOR)
    return INTEL_125W_BUDGET_W if tdp >= 125 else tdp * 2


def psu_wattage(cpu, gpu, psu):
    watts = psu.get("wattage")
    if not watts:
        return _r("fit.psu_wattage", UNCERTAIN, "PSU wattage unknown")
    gpu_w, rec_w, _ = _gpu_power(gpu) if gpu is not None else (0, None, None)
    cpu_w = _cpu_power(cpu) if cpu is not None else None
    if gpu is not None and not gpu_w:
        return _r("fit.psu_wattage", UNCERTAIN, f"board power unknown for GPU {gpu.get('chipset', '?')}")
    if cpu is not None and cpu_w is None:
        return _r("fit.psu_wattage", UNCERTAIN, "CPU power unknown (no TDP or vendor on the CPU card)")
    if cpu_w is None:
        if rec_w:
            verdict = PASS if watts >= rec_w else FAIL
            return _r("fit.psu_wattage", verdict, f"{watts} W PSU vs GPU maker's recommended {rec_w} W (CPU not given)")
        return _r("fit.psu_wattage", UNCERTAIN, "CPU power unknown")
    load = cpu_w + (gpu_w or 0) + REST_OF_SYSTEM_W
    need = max(rec_w or 0, math.ceil(load * PSU_HEADROOM / 10) * 10)
    why = f"est. load {load} W, need {need} W ({int((PSU_HEADROOM - 1) * 100)}% headroom" + (f", maker recommends {rec_w} W)" if rec_w else ")")
    if watts < need:
        return _r("fit.psu_wattage", FAIL, f"{watts} W PSU is underpowered: {why}")
    return _r("fit.psu_wattage", PASS, f"{watts} W PSU covers {why}")


def gpu_connectors(gpu, psu):
    _, _, conn = _gpu_power(gpu)
    if not conn:
        return _r("fit.gpu_connectors", UNCERTAIN, "GPU power connectors vary by card; not given")
    kind, n = conn
    p16, p8 = psu.get("pcie_16pin"), psu.get("pcie_8pin")
    if kind == "16pin":
        if p16:
            return _r("fit.gpu_connectors", PASS, "PSU has a native 16-pin (12V-2x6) cable")
        if p8 is not None and p8 >= n:
            return _r("fit.gpu_connectors", PASS, f"16-pin via the card's adapter from {n}x 8-pin", note="uses the card's 16-pin adapter")
        if p16 is None or p8 is None:
            return _r("fit.gpu_connectors", UNCERTAIN, "PSU connector counts unknown")
        return _r("fit.gpu_connectors", FAIL, f"card needs a 16-pin or {n}x 8-pin; PSU has {p8}x 8-pin and no 16-pin")
    if p8 is None:
        return _r("fit.gpu_connectors", UNCERTAIN, "PSU 8-pin count unknown")
    if p8 < n:
        return _r("fit.gpu_connectors", FAIL, f"card needs {n}x 8-pin; PSU has {p8}")
    return _r("fit.gpu_connectors", PASS, f"{n}x 8-pin available")


def _clearance(rule_id, what, size, room):
    if size is None or room is None:
        return _r(rule_id, UNCERTAIN, f"{what} or case clearance unknown")
    if size > room:
        return _r(rule_id, FAIL, f"{what} {size} mm exceeds case clearance {room} mm")
    return _r(rule_id, PASS, f"{what} {size} mm within case clearance {room} mm")


def gpu_length(gpu, case):
    return _clearance("fit.gpu_length", "GPU length", gpu.get("length_mm"), case.get("max_gpu_length_mm"))


def cooler_height(cooler, case):
    if cooler.get("type") == "aio":
        rad, mounts = cooler.get("radiator_mm"), case.get("radiator_mounts_mm")
        if rad is None or mounts is None:
            return _r("fit.cooler_height", UNCERTAIN, "radiator size or case radiator mounts unknown")
        ok = rad in mounts
        return _r("fit.cooler_height", PASS if ok else FAIL, f"{rad} mm radiator {'fits' if ok else 'has no mount in'} the case")
    return _clearance("fit.cooler_height", "cooler height", cooler.get("height_mm"), case.get("max_cooler_height_mm"))


def cooler_socket(cpu, cooler):
    sockets, cs = cooler.get("sockets"), cpu.get("socket")
    if not sockets or not cs:
        return _r("fit.cooler_socket", UNCERTAIN, "cooler sockets or CPU socket unknown")
    ok = cs in sockets
    return _r("fit.cooler_socket", PASS if ok else FAIL, f"cooler {'supports' if ok else 'does not list'} {cs}")


def form_factor(board, case):
    ff = board.get("form_factor")
    takes = case.get("motherboard_form_factors") or CASE_TYPE_BOARDS.get(case.get("type"))
    if not ff or not takes:
        return _r("fit.form_factor", UNCERTAIN, "board form factor or case support unknown")
    ok = ff in takes
    if not ok and ff in LARGE_BOARDS and not case.get("motherboard_form_factors") and (case.get("type") or "").startswith("ATX"):
        return _r("fit.form_factor", UNCERTAIN, f"{ff} support varies by {case.get('type')}; check the case spec")
    return _r("fit.form_factor", PASS if ok else FAIL, f"{ff} board {'fits' if ok else 'does not fit'} a case for {', '.join(sorted(takes))}")


def psu_form_factor(psu, case):
    pf = psu.get("form_factor")
    takes = case.get("psu_form_factors") or (None if "ITX" in (case.get("type") or "") else CASE_TYPE_PSU.get(case.get("type")))
    if not pf or not takes:
        return _r("fit.psu_form_factor", UNCERTAIN, "PSU form factor or case PSU support unknown")
    ok = pf in takes
    if not ok and pf in ("SFX", "SFX-L") and "ATX" in takes:
        return _r("fit.psu_form_factor", UNCERTAIN, f"{pf} PSU in an ATX PSU bay needs an SFX-to-ATX bracket; check it is included")
    return _r("fit.psu_form_factor", PASS if ok else FAIL, f"{pf} PSU {'fits' if ok else 'does not fit'} a case for {', '.join(sorted(takes))}")


def storage(board, drive):
    iface = drive.get("interface") or ""
    if iface.startswith("M.2 PCIe"):
        slots = board.get("m2_slots")
        if slots is None:
            return _r("fit.storage", UNCERTAIN, "board M.2 slot count unknown")
        return _r("fit.storage", PASS if slots else FAIL, f"NVMe drive {'has' if slots else 'needs'} an M.2 slot")
    if iface.startswith("SATA"):
        ports = board.get("sata_ports")
        if ports is None:
            return _r("fit.storage", UNCERTAIN, "board SATA port count unknown")
        return _r("fit.storage", PASS if ports else FAIL, f"SATA drive {'has' if ports else 'needs'} a SATA port")
    return _r("fit.storage", UNCERTAIN, f"interface {iface or 'unknown'} not checked")


def _parts(cards, cat):
    return [c.get("attrs") or {} for c in cards if c.get("category") == cat]


def check_fit(spec_cards):
    one = {cat: (_parts(spec_cards, cat) or [None])[0]
           for cat in ("cpu", "motherboard", "memory", "gpu", "psu", "case", "cooler")}
    cpu, board, mem, gpu, psu, case, cooler = (one[k] for k in ("cpu", "motherboard", "memory", "gpu", "psu", "case", "cooler"))
    has = lambda *xs: all(x is not None for x in xs)
    checks = []
    if has(cpu, board): checks.append(cpu_socket(cpu, board))
    if has(board, mem): checks += [ram_type(board, mem), ram_slots(board, mem)]
    if psu is not None and (cpu is not None or gpu is not None): checks.append(psu_wattage(cpu, gpu, psu))
    if has(gpu, psu): checks.append(gpu_connectors(gpu, psu))
    if has(gpu, case): checks.append(gpu_length(gpu, case))
    if has(cpu, cooler): checks.append(cooler_socket(cpu, cooler))
    if has(cooler, case): checks.append(cooler_height(cooler, case))
    if has(board, case): checks.append(form_factor(board, case))
    if has(psu, case): checks.append(psu_form_factor(psu, case))
    if board is not None: checks += [storage(board, d) for d in _parts(spec_cards, "storage")]
    checks = [c for c in checks if c]
    notes = [c.pop("note") for c in checks if c.get("note")]
    for c in checks: c.pop("note", None)
    fails = [c for c in checks if c["verdict"] == FAIL]
    unsure = [c for c in checks if c["verdict"] == UNCERTAIN]
    if fails:
        verdict, rule_id = FAIL, fails[0]["rule_id"]
    elif unsure or not checks:
        verdict, rule_id = UNCERTAIN, unsure[0]["rule_id"] if unsure else "fit.no_checks"
    else:
        verdict, rule_id = PASS, "fit.ok"
    reasons = [c["reason"] for c in fails + unsure] or [f"all {len(checks)} checks passed"]
    if not checks:
        reasons = ["no pair of parts to check"]
    return {"verdict": verdict, "reasons": reasons, "rule_id": rule_id, "checks": checks, "notes": notes}
