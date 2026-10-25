"""All the catalog sellers in one process. Run from agents/: python sellers/run_all.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from uagents import Bureau

import common
from seller_agent import build


def build_all(names=None) -> list:
    """Build each seller. In mailbox mode a seller that still has the public dev seed is skipped with a message, so the
    sellers that are ready (the ones on Agentverse) keep running; single-agent runs keep the hard exit."""
    agents = []
    for name in common.MIRROR_SELLERS:
        if not names and name not in common.SELLERS:
            print(f"{name} off: set {name.upper()}_AGENT_SEED in agents/.env (private, {common.MIN_PRIVATE_SEED}+ "
                  "characters) to run it; it has no default seed")
    if not names:
        for name, why in common.RETIRED_SELLERS.items():
            print(f"{name} {why}")
    for name in names or [n for n in common.SELLERS if n not in common.RETIRED_SELLERS]:
        if not common.mailbox_ready(name):
            print(f"{name} skipped: set {name.upper()}_AGENT_SEED")
            continue
        a = build(name)
        print(f"{name} address:", a.address)
        agents.append(a)
    return agents


if __name__ == "__main__":
    common.require_peer_seeds("seller_1")   # #449 RT-27: every seller trusts the buyer; production mode needs its private seed
    bureau = Bureau(port=8010, endpoint=["http://localhost:8010/submit"])
    for a in build_all():
        bureau.add(a)
    bureau.run()
