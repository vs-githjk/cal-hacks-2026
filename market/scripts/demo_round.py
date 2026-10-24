"""One SIM round end to end over the Python bridge, standing in for Lanes A, C and D until they land.
Needs setup_roles.py first. Usage: python3 market/scripts/demo_round.py [token_dir] [window_s]
"""
import os
import sys
import time

from stdb import Market

TOKENS = sys.argv[1] if len(sys.argv) > 1 else ".tokens"
WINDOW = int(sys.argv[2]) if len(sys.argv) > 2 else 12
agent = {n: Market(token_file=os.path.join(TOKENS, f"{n}.json")) for n in ["referee", "buyer-joe", "seller-a", "seller-b", "seller-c"]}
ref, joe = agent["referee"], agent["buyer-joe"]
GPU = "gpu-rtx5070ti-retail"
run = str(int(time.time()))
need, rnd = f"need-{run}", f"round-{run}"


def line(price, condition=""):
    return [{"sku_spec": GPU, "offered_spec": "", "offered_condition": condition, "unit_price": price, "quantity": 1}]


def refused(who, reducer, **args):
    try:
        agent[who].call(reducer, **args)
        return "ALLOWED (bad)"
    except RuntimeError as e:
        return "refused: " + str(e).split("): ", 1)[-1][:90]


joe.call("post_need", id=need, buyer_id="joe", goal_id="goal-joe-gpu", delivery_window="by Friday", spend_limit=800,
         consent=True, auction_window_s=WINDOW, origin="SIM",
         items=[{"sku_spec": GPU, "condition": "new", "variant": "retail", "quantity": 1, "unit": "each"}])
ref.call("open_round", round_id=rnd, need_id=need, window_s=WINDOW)
for s, floor in [("seller-a", 700), ("seller-b", 650), ("seller-c", 690)]:
    agent[s].call("set_floor", sku_spec=GPU, floor=floor)
bids = {"seller-a": (780, ""), "seller-b": (699, "open-box"), "seller-c": (745, "")}
for s, (price, cond) in bids.items():
    agent[s].call("place_bid", id=f"{rnd}-{s}", round_id=rnd, persona={"seller-a": "Seller A", "seller-b": "Seller B", "seller-c": "Seller C"}[s],
                  lines=line(price, cond), stated_total=price, perks=[], claims=[], origin="SIM", source="sim:demo_round")
print("seller-a sees:", [r[0] for r in agent["seller-a"].sql("SELECT * FROM my_bids")])
print("seller-a open_round:", refused("seller-a", "open_round", round_id="x", need_id=need, window_s=5))
print("seller-a attach_verdict on seller-c:", refused("seller-a", "attach_verdict", bid_id=f"{rnd}-seller-c", verdict="block", rule_ids=["x"], origin="SIM"))
print("seller-b bad quantity:", refused("seller-b", "place_bid", id="q", round_id=rnd, persona="x",
      lines=[{"sku_spec": GPU, "offered_spec": "", "offered_condition": "", "unit_price": 700, "quantity": 0}],
      stated_total=0, perks=[], claims=[], origin="SIM", source="x"))
ref.call("attach_claim_check", bid_id=f"{rnd}-seller-c", claim="in stock", check="verified", evidence_url="https://example.com/sim", origin="SIM")
print(f"waiting {WINDOW + 2}s for the scheduler to close the round...")
time.sleep(WINDOW + 2)
print("round:", ref.sql(f"SELECT state FROM round WHERE id = '{rnd}'"))
for r in ref.sql(f"SELECT seller_id, rank, landed, reasons FROM round_result WHERE round_id = '{rnd}'"):
    print("  result:", r)
mh = f"mh-{run}"
ref.call("create_mandate", hash=mh, id=f"mdt-{run}", deal_id=f"{rnd}-seller-c", buyer_id="joe", amount=745, payee="seller-c",
         expiry_minutes=10, nonce=run, origin="SIM")
print("pay before approval:", refused("referee", "record_payment", mandate_hash=mh, payment_ref="pi_sim", amount=745))
print("seller-c approves own deal:", refused("seller-c", "record_approval", mandate_hash=mh, method="typed_code", approved_by="joe"))
joe.call("record_approval", mandate_hash=mh, method="typed_code", approved_by="joe")
ref.call("record_payment", mandate_hash=mh, payment_ref="pi_sim_" + run, amount=745)
ref.call("record_approval", mandate_hash=mh, method="typed_code", approved_by="joe")
print("refused attempts shown:", ref.sql("SELECT kind, reason FROM rejected_attempt"))
