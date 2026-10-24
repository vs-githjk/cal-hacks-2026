"""Score check_fit on the frozen build set: python -m data.fit_checker.eval_builds [--md]"""
import json
import sys
from pathlib import Path

from . import check_fit

BUILDS = Path(__file__).resolve().parent.parent / "fit_builds.json"


def score(only_checked=False):
    rows = []
    for b in json.loads(BUILDS.read_text())["builds"]:
        if only_checked and not b.get("hand_checked"):
            continue
        out = check_fit(b["parts"])
        rows.append({"id": b["id"], "truth": b["truth"], "verdict": out["verdict"], "rule_id": out["rule_id"]})
    decided = [r for r in rows if r["verdict"] != "uncertain"]
    right = [r for r in decided if (r["verdict"] == "pass") == (r["truth"] == "fits")]
    return {
        "n": len(rows), "decided": len(decided), "correct": len(right),
        "uncertain": len(rows) - len(decided),
        "false_ok": [r for r in rows if r["verdict"] == "pass" and r["truth"] == "does_not_fit"],
        "false_fail": [r for r in rows if r["verdict"] == "fail" and r["truth"] == "fits"],
        "uncertain_rows": [r for r in rows if r["verdict"] == "uncertain"],
    }


def markdown(s, label="frozen set in data/fit_builds.json"):
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"
    lines = [
        f"- builds: {s['n']} (SIM, {label})",
        f"- decided (pass or fail): {s['decided']}, correct {s['correct']} ({pct(s['correct'], s['decided'])})",
        f"- uncertain: {s['uncertain']}",
        f"- **false OK (said fits, does not): {len(s['false_ok'])}**",
        f"- false fail (said does not fit, fits): {len(s['false_fail'])}",
    ]
    for label, key in (("false OK", "false_ok"), ("false fail", "false_fail"), ("uncertain", "uncertain_rows")):
        lines += [f"  - {label}: `{r['id']}` ({r['rule_id']})" for r in s[key]]
    return "\n".join(lines)


if __name__ == "__main__":
    print(markdown(score()))
    print(markdown(score(only_checked=True), "subset whose every part was confirmed on a maker page"))
