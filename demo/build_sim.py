"""An in-memory stand-in for the SpacetimeDB market, for `python3 demo/build.py --dry-run` and the build tests (#345).

It applies the rules the real market applies at the points a build touches: floors, Shield verdicts, advocate vetoes and cautions at the close,
rank 1 only for a mandate, the allowance rule on create_mandate, no payment without an approval, and (when asked) the sealed knockout stages
of docs/changes/1633-B-knockout-rounds.md (#363). It is NOT the market: nothing here ranks for the real run."""
from __future__ import annotations

import re

from demo import build

LADDER_TOP = (600, 1500)   # market/config.ts ALLOWANCE_LADDER's top step: per purchase, per period
# market/config.ts QUALITY (a test reads the file and pins these): the market ranks on the quality-adjusted score, not on landed price
QUALITY = {"condition_adj": {"new": 0.0, "open-box": 0.04, "refurbished": 0.08, "used": 0.15, "unknown": 0.0}, "no_returns_adj": 0.02,
           "min_returns_days": 30}


def adjusted_total(line: dict, perks: list, condition: str, quantity: float = 1.0) -> float:
    """market/rules/scoring.ts qualityAdjusted and rankBids' score for one picked line: price x quantity x (1 + the condition step + the
    no-returns step), in cents. The market passes no perksValue, so nothing else is taken off."""
    found = [int(m.group(1)) for p in perks for m in [re.search(r"(\d+)[- ]day returns?", str(p), re.I)] if m]
    returns = 0.0 if max([0, *found]) >= QUALITY["min_returns_days"] else QUALITY["no_returns_adj"]
    return round(line["unit_price"] * quantity * (1 + QUALITY["condition_adj"].get(condition, 0.0) + returns), 2)


class SimMarket:
    def __init__(self, spent=0.0, ladder_cap=True, scheduler_first=False, clock=None):
        # ladder_cap: set_allowance refuses above the ladder's top step ($600 a buy, $1,500 a period, market/config.ts)
        # scheduler_first (needs `clock`, a callable giving seconds): the market's deadline scheduler (closeRoundOnDeadline) closes a knockout
        # stage AT its deadline, before any later call is handled, as the real #363 module does. The referee's close_stage then finds the stage
        # closed: "round is still open until its deadline" (the next stage has opened) or "round already closed" (the last one).
        self.ladder_cap, self.scheduler_first, self.clock = ladder_cap, scheduler_first, clock
        self.ko = {}          # sealed knockout rounds (#363): round id -> {"stage", "max"}
        self.published = []   # publish_build_view calls: (goal_id, json text)
        self.log, self.bids, self.cards, self.verdicts, self.needs, self.rounds = [], {}, {}, {}, {}, {}
        self.rows, self.mandates, self.approvals, self.payments = [], {}, {}, {}
        self.fail, self.floors, self.floor_events, self.round_state = {}, {}, [], {}
        # the market's allowance row starts at $0 (a new buyer's first buy always calls); set_allowance changes it
        self.allow = {"per": 0.0, "period_limit": 0.0, "period": "week", "spent": spent}
        # switches for the checks that read the market back
        # the real referee cannot read private tables (HTTP 400); the buyer reads its own rows through the my_allowance and my_deals views
        self.allowance_readable, self.deals_readable, self.events_readable = True, True, True
        self.swallow_approval, self.never_close, self.knockout = False, False, set()
        self.goals = {}
        self.buyer_id = "vidyut"   # whose allowance the buyer client reads back (my_allowance)
        self.goal_reader = "vidyut"   # the buyer role the buyer client holds: my_goals returns this buyer's goals only
        self.goal_state = {}          # goal id -> state (default ACTIVE)
        self.codes = {}               # mandate hash -> the normalised approval code issued for it (#449 item 3)

    def post_goal(self, a):
        # market.ts GOAL_TYPES, which is also the enum of contracts/Goal.schema.json
        if a["type"] not in ("budget_cap", "part_by_date", "build_by_date"):
            raise RuntimeError("goal type must be one of budget_cap, part_by_date, build_by_date")
        if a["id"] in self.goals:
            raise RuntimeError(f"goal {a['id']} already exists")
        self.goals[a["id"]] = a

    def set_allowance(self, a):
        if a["per_purchase_limit"] > a["period_limit"]:
            raise RuntimeError("set_allowance refused: per_purchase_limit cannot be above period_limit")
        if self.ladder_cap and (a["per_purchase_limit"] > LADDER_TOP[0] or a["period_limit"] > LADDER_TOP[1]):
            raise RuntimeError(f"set_allowance refused: above the ladder's top step (${LADDER_TOP[0]} a buy, ${LADDER_TOP[1]} a period)")
        self.allow = {**self.allow, "per": a["per_purchase_limit"], "period_limit": a["period_limit"], "period": a["period"]}

    def client(self, name):
        return _Client(self, name)

    # reducers (only those with a rule worth faking)
    def set_floor(self, a):
        self.floors[(a["seller_id"], a["sku_spec"])] = a["floor"]

    def place_bid(self, a):
        need = self.needs[self.rounds[a["round_id"]]["need_id"]]
        item = need["items"][0]
        allowed = item.get("allowed_conditions") or [item["condition"]]
        # the market picks the cheapest line whose condition the goal allows; a bid with none is judged (and rejected) at the close
        fits = [l for l in a["lines"] if (l.get("offered_condition") or item["condition"]) in allowed] or a["lines"]
        line = min(fits, key=lambda l: l["unit_price"])
        below = line["unit_price"] < self.floors.get((a["seller_id"], line["sku_spec"]), 0)
        ko = self.ko.get(a["round_id"])
        stage = ko["stage"] if ko else 1
        if ko and stage > 1:   # docs/changes/1633-B: survivors only, one offer a stage, strictly lower than the seller's own last offer, at or above its floor
            mine = [b for b in self.bids.values() if b["round_id"] == a["round_id"] and b["seller_id"] == a["seller_id"]]
            if a["seller_id"] not in ko["alive"]:
                raise RuntimeError("place_bid refused: you are knocked out of this round")
            if any(b["stage"] == stage for b in mine):
                raise RuntimeError("place_bid refused: already offered this stage")
            if mine and line["unit_price"] >= min(b["landed"] for b in mine):
                raise RuntimeError("place_bid refused: the offer must be lower than your last stage's")
            # below its floor is not refused here: the offer stands and the stage's close knocks it out (docs/changes/1633-B)
        cond = line.get("offered_condition") or item["condition"]
        adjusted = adjusted_total(line, a.get("perks") or [], cond, float(item.get("quantity") or 1))
        self.bids[a["id"]] = {**a, "landed": line["unit_price"], "adjusted": adjusted, "below_floor": below, "stage": stage}

    def post_need(self, a):
        self.needs[a["id"]] = a

    def attach_advocate_card(self, a):
        self.cards[a["bid_id"]] = a

    def attach_verdict(self, a):
        self.verdicts[a["bid_id"]] = a["verdict"]

    def open_round(self, a):
        self.rounds[a["round_id"]] = a
        self.round_state[a["round_id"]] = "open"

    def open_knockout_round(self, a):
        """#363: stages of stage_window_s, up to max_stages; a seller that places no offer in a stage keeps its last one."""
        self.rounds[a["round_id"]] = a
        self.round_state[a["round_id"]] = "open"
        self.ko[a["round_id"]] = {"stage": 1, "max": a["max_stages"], "alive": None, "window": a["stage_window_s"],
                                  "deadline": self._now() + a["stage_window_s"]}

    def _now(self) -> float:
        return float(self.clock()) if self.clock is not None else 0.0

    def tick(self) -> None:
        """The deadline scheduler: close every open knockout stage whose deadline has passed, then the next stage's deadline is one window on."""
        if not self.scheduler_first:
            return
        for rid, ko in self.ko.items():
            while self.round_state.get(rid) == "open" and ko["deadline"] <= self._now():
                self._close_stage({"round_id": rid})
                ko["deadline"] += ko["window"]

    def close_stage(self, a):
        """The contract of docs/changes/1633-B: rule-breakers and the last-placed survivor go out; one survivor wins at once; at the last
        stage the best offer wins; zero survivors close the round with no deal."""
        if self.scheduler_first:
            self.tick()
            if self.round_state[a["round_id"]] == "closed":
                raise RuntimeError("round already closed")
            if self.ko[a["round_id"]]["deadline"] > self._now():
                raise RuntimeError("round is still open until its deadline")
        self._close_stage(a)

    def _close_stage(self, a):
        rid, ko = a["round_id"], self.ko[a["round_id"]]
        if self.never_close:
            return
        stage = ko["stage"]
        latest: dict[str, dict] = {}
        for b in sorted((b for b in self.bids.values() if b["round_id"] == rid), key=lambda b: b["stage"]):
            latest[b["seller_id"]] = b
        live = [b for s, b in latest.items() if ko["alive"] is None or s in ko["alive"]]
        # #363's closeStageInner ranks by price and never holds a caution back (heldBack stays empty), so neither does this stand-in
        ok, out = self._judge(rid, live, hold=False)
        out = list(out)
        champion = None
        if len(ok) > 1 and stage >= ko["max"]:
            champion = ok[0]
            out += [(b, ["did not advance: final stage"]) for b in ok[1:]]
            ok = ok[:1]
        elif len(ok) > 1:
            out.append((ok[-1], [f"did not advance: last place in stage {stage}"]))   # the single last-placed survivor goes out
            ok = ok[:-1]
        if len(ok) == 1 and champion is None:
            champion = ok[0]   # one survivor left: the round is won at once
        rows = []
        for i, b in enumerate(ok, 1):
            rows.append((b, i, [], "champion" if champion is b else "advancing"))
        rows += [(b, 0, why, "knocked_out") for b, why in out]
        for b, rank, why, status in rows:
            self.rows.append((len(self.rows) + 1, rid, b["id"], b["seller_id"], b["persona"], rank, b["landed"], why, b["lines"], b["origin"],
                              b["source"], b["adjusted"], "", stage, status))
        if champion is not None or not ok:
            self.round_state[rid] = "closed"
        else:
            ko["stage"] = stage + 1
            ko["alive"] = {b["seller_id"] for b in ok}

    def _held(self, b):
        card = self.cards.get(b["id"], {})
        return (f"held back: advocate caution ({card['rule_id']}: {card['text']})" if card.get("recommendation") == "caution" else "")

    def _judge(self, rid, mine, hold=True):
        """The checks the market runs on every live bid: floor, condition, Shield, advocate veto, the cap. -> (clean bids best first, [(bid,
        reasons)]). With `hold` (a plain round, close_round) a caution ranks after every clean bid, as the market holds it back."""
        need = self.needs[self.rounds[rid]["need_id"]]
        item = need["items"][0]
        allowed = item.get("allowed_conditions") or [item["condition"]]
        ok, out = [], []
        for b in mine:
            card, verdict = self.cards.get(b["id"]), self.verdicts.get(b["id"], "allow")
            cond = min(b["lines"], key=lambda l: l["unit_price"]).get("offered_condition") or item["condition"]
            fits = [l for l in b["lines"] if (l.get("offered_condition") or item["condition"]) in allowed]
            if not fits:   # scoring.ts checkLineSpec
                out.append((b, [f"condition: offered {cond}, goal asks for {' or '.join(allowed)}"]))
            elif b["below_floor"]:
                out.append((b, ["referee: below the seller's own floor"]))
            elif verdict != "allow":
                out.append((b, [f"shield {verdict}"]))
            elif card and card["recommendation"] == "veto":
                out.append((b, [f"advocate veto ({card['rule_id']}): {card['text']}"]))
            elif b["landed"] > need["spend_limit"]:
                out.append((b, ["over the cap"]))
            else:
                ok.append(b)
        # scoring.ts rankBids: a held-back caution last, then the adjusted score; a tie keeps the order the bids were sealed in
        ok.sort(key=lambda b: (hold and bool(self.cards.get(b["id"]) and self.cards[b["id"]]["recommendation"] == "caution"), b["adjusted"]))
        return ok, out

    def publish_build_view(self, a):
        self.published.append((a["goal_id"], a["json"]))

    def close_round(self, a):
        rid = a["round_id"]
        if self.never_close:
            return
        self.round_state[rid] = "closed"
        ok, out = self._judge(rid, [b for b in self.bids.values() if b["round_id"] == rid])
        for i, b in enumerate(ok, 1):
            held = self._held(b)
            self.rows.append((len(self.rows) + 1, rid, b["id"], b["seller_id"], b["persona"], i, b["landed"], [held] if held else [],
                              b["lines"], b["origin"], b["source"], b["adjusted"], "", 1, "advancing" if rid in self.knockout and i == 1 else ""))
        for b, why in out:
            self.rows.append((len(self.rows) + 1, rid, b["id"], b["seller_id"], b["persona"], 0, b["landed"], why, b["lines"], b["origin"], b["source"],
                              b["landed"], "", 1, ""))

    def create_mandate(self, a):
        bid_id = a["deal_id"][5:]
        won = next((r for r in self.rows if r[2] == bid_id and r[5] == 1), None)
        if won is None:
            raise RuntimeError("a mandate needs the rank 1 bid of a closed round")
        if a["payee"] != won[3] or abs(a["amount"] - won[6]) > 1e-9:
            raise RuntimeError("payee or amount differs from the winner")
        self.mandates[a["hash"]] = a
        al = self.allow   # market/rules/allowance.ts decide(): $0, over the per-buy limit or past the period limit all call
        if al["per"] > 0 and a["amount"] <= al["per"] and al["spent"] + a["amount"] <= al["period_limit"]:
            self.approvals[a["hash"]] = {"method": "allowance", "voice_approval_id": ""}
            self.allow = {**al, "spent": round(al["spent"] + a["amount"], 2)}
            self.floor_events.append(("approval_recorded", a["hash"], "Approved within the allowance"))

    def issue_approval_code(self, a):
        if a["mandate_hash"] not in self.mandates:
            raise RuntimeError("no mandate with that hash")
        self.codes[a["mandate_hash"]] = " ".join(a["code"].lower().split())

    def record_approval(self, a):
        if a["mandate_hash"] not in self.mandates:
            raise RuntimeError("no mandate with that hash")
        # #449 item 3 RT-11: a voice approval repeats the code issued for that mandate (the market compares it with its own row)
        if a["method"] == "voice_code" and " ".join(str(a.get("code", "")).lower().split()) != self.codes.get(a["mandate_hash"]):
            raise RuntimeError("the approval code does not match")
        if a["method"] == "allowance":
            raise RuntimeError("this deal is over the allowance; only the call approves it")
        if a["method"] == "voice_code" and not a["voice_approval_id"].strip():
            raise RuntimeError("a voice approval needs the VoiceApproval id from the call")
        if self.swallow_approval or a["mandate_hash"] in self.approvals:
            return   # the real market logs rejected() on a second approval and does not throw
        self.approvals[a["mandate_hash"]] = {"method": a["method"], "voice_approval_id": a["voice_approval_id"].strip()}
        self.floor_events.append(("approval_recorded", a["mandate_hash"], "Approved by voice code"))

    def record_payment(self, a):
        if a["mandate_hash"] not in self.approvals:
            raise RuntimeError("no approval row for this mandate hash; payment refused")
        self.payments[a["mandate_hash"]] = a


class _Client:
    def __init__(self, market, name):
        self.m, self.name = market, name

    def call(self, reducer, **args):
        self.m.log.append((self.name, reducer, args))
        self.m.tick()
        if self.m.fail.get(reducer):
            raise RuntimeError(self.m.fail[reducer])
        seen = {**args, "seller_id": self.name.split(":", 1)[1]} if reducer in ("place_bid", "set_floor") else args   # the market knows the caller
        getattr(self.m, reducer, lambda a: None)(seen)

    def sql(self, query):
        m = self.m
        m.tick()
        if query == "SELECT * FROM round_result":
            return list(m.rows)
        if query == "SELECT * FROM round":   # id, need_id, opened_at, deadline, extensions, state, sealed_count, closed_at, origin
            return [(rid, m.rounds[rid]["need_id"], "t", "t", 0, st, 0, None, "SIM") for rid, st in m.round_state.items()]
        if query in ("SELECT * FROM allowance", "SELECT * FROM approval", "SELECT * FROM mandate"):   # private: the referee cannot read them
            raise RuntimeError("sql failed (400): no such table")
        if query == build.GOALS_SQL:        # the my_goals view answers the caller's own buyer role only: the referee and sellers read none
            if self.name != "buyer":
                return []
            return [(g["id"], g["buyer_id"], g["type"], g["cap"], g["deadline"], m.goal_state.get(g["id"], "ACTIVE"), [1_000_000 * i])
                    for i, g in enumerate(m.goals.values(), 1) if g["buyer_id"] == m.goal_reader]
        if query == build.GOAL_ITEMS_SQL:   # my_goal_items: the same rule
            if self.name != "buyer":
                return []
            return [(g["id"], i["sku_spec"], i["condition"], i["variant"], i["quantity"], i["skipped_owned_part_id"])
                    for g in m.goals.values() if g["buyer_id"] == m.goal_reader for i in g["items"]]
        if query == "SELECT * FROM my_allowance":      # buyer only
            if self.name != "buyer" or not m.allowance_readable:
                raise RuntimeError("sql failed (400)")
            a = m.allow
            return [(m.buyer_id, "USD", a["per"], a["period_limit"], a["period"], a["spent"], 0, "t")]
        if query == "SELECT * FROM my_deals":          # buyer only: hash, id, deal, amount, payee, expiry, within, origin, method, voice id, ...
            if self.name != "buyer" or not m.deals_readable:
                raise RuntimeError("sql failed (400)")
            return [(h, mm["id"], mm["deal_id"], mm["amount"], mm["payee"], "t", False, mm["origin"], m.approvals.get(h, {}).get("method", ""),
                     m.approvals.get(h, {}).get("voice_approval_id", ""), None, "", "", None) for h, mm in m.mandates.items()]
        if query == "SELECT * FROM floor_event":   # id, kind, ref_table, ref_id, seller_id, label, origin, at
            if not m.events_readable:
                raise RuntimeError("sql failed (500)")
            return [(i, k, "approval", ref, "", label, "SIM", "t") for i, (k, ref, label) in enumerate(m.floor_events, 1)]
        raise AssertionError(query)


class Clients(dict):
    """Every seller id gets its own client, as the bridge makes one per seller identity."""
    def __init__(self, m):
        super().__init__({n: m.client(n) for n in ("buyer", "referee")})
        self.m = m

    def __missing__(self, key):
        self[key] = self.m.client(key)
        return self[key]

    def __contains__(self, key):
        return True


def make_clients(m):
    return Clients(m)


class FakeMarket(SimMarket):
    """The market the older build tests grew up with: no ladder cap on set_allowance (they use huge limits for an inside-the-allowance build)."""
    def __init__(self, spent=0.0, **kw):
        super().__init__(spent, **{"ladder_cap": False, **kw})

