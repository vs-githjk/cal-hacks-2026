"""Post a goal from Python, as Lane A's buyer agent would. Usage: python3 market/scripts/post_goal.py [goal_id]"""
import sys
import time

from stdb import Market

goal_id = sys.argv[1] if len(sys.argv) > 1 else f"goal-py-{int(time.time())}"
Market().call(
    "post_goal",
    id=goal_id,
    buyer_id="joe",
    type="part_by_date",
    text="a GPU for 1440p that fits my case and PSU, under $800, by Friday",
    cap=800,
    deadline_minutes=60 * 24 * 3,
    po_number="",
    origin="SIM",
    items=[{"category": "gpu", "description": "GPU for 1440p", "sku_spec": "", "model_number": ""}],
)
print("posted", goal_id)
