"""All three sellers in one process. Run from agents/: python sellers/run_all.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from uagents import Bureau

import common
from seller_agent import build

if __name__ == "__main__":
    bureau = Bureau(port=8010, endpoint=["http://localhost:8010/submit"])
    for name in common.SELLERS:
        a = build(name)
        print(f"{name} address:", a.address)
        bureau.add(a)
    bureau.run()
