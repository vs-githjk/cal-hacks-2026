"""Post a goal from Python, as Lane A's buyer agent would (Lane A's Goal contract).
Needs setup_roles.py first. Usage: python3 market/scripts/post_goal.py [goal_id] [token_dir]
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from stdb import Market

goal_id = sys.argv[1] if len(sys.argv) > 1 else f"goal-py-{int(time.time())}"
tokens = sys.argv[2] if len(sys.argv) > 2 else ".tokens"
deadline = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT23:59:00Z")
Market(token_file=os.path.join(tokens, "buyer-joe.json")).call(
    "post_goal",
    id=goal_id,
    buyer_id="joe",
    type="part_by_date",
    cap=800,
    deadline=deadline,
    po_number="",
    origin="SIM",
    items=[{"sku_spec": "gpu-rtx5070ti-retail", "condition": "new", "variant": "retail", "quantity": 1, "skipped_owned_part_id": ""}],
)
print("posted", goal_id)
