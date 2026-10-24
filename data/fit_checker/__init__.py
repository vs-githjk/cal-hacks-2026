"""Fit checker (Lane C, c2). MOCK: same I/O as the final version.

check_fit(spec_cards) -> {"verdict": "pass"|"fail"|"uncertain", "reasons": [str], "rule_id": str, "checks": [...]}
Input is a list of SpecCards (contracts/SpecCard.schema.json) with `attrs`.
The mock only compares cpu.attrs.socket with motherboard.attrs.socket; everything else is uncertain.
"""


def check_fit(spec_cards):
    by_cat = {c.get("category"): c.get("attrs", {}) for c in spec_cards}
    cpu, board = by_cat.get("cpu"), by_cat.get("motherboard")
    if cpu and board and cpu.get("socket") and board.get("socket"):
        if cpu["socket"] != board["socket"]:
            reason = f"CPU socket {cpu['socket']} does not match board socket {board['socket']}"
            check = {"rule_id": "fit.cpu_socket", "verdict": "fail", "reason": reason}
            return {"verdict": "fail", "reasons": [reason], "rule_id": "fit.cpu_socket", "checks": [check]}
    reason = "mock fit checker: not checked yet"
    return {"verdict": "uncertain", "reasons": [reason], "rule_id": "fit.mock",
            "checks": [{"rule_id": "fit.mock", "verdict": "uncertain", "reason": reason}]}
