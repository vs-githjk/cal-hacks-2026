"""Purchasing seat: requisition, approval chain, controller NO and re-plan, receiving."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Optional

from hyphenate.company import Outcome
from hyphenate.ledger import Line
from hyphenate.money import cents, usd
from hyphenate.trust import resolve
from hyphenate.vendors import assess


def _clean_lines(lines: list) -> list:
    out = []
    if not lines:
        raise ValueError("a requisition needs at least one line")
    for l in lines:
        qty = l.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError("qty must be a positive whole number")
        unit = cents(l["price"] if "price" in l else l["unit"] / 100)
        if unit <= 0:
            raise ValueError("price must be positive")
        cond = l.get("condition", "new")
        out.append({"sku": l["sku"], "desc": l.get("desc", l["sku"]), "qty": qty, "unit": unit, "condition": cond,
                    "allowed": list(l.get("allowed") or [cond]), "serialized": bool(l.get("serialized", True)),
                    "accepted": 0, "rejected": 0, "billed": 0, "accepted_conditions": [], "reject_reasons": [],
                    "min_qty": int(l.get("min_qty", qty)),
                    "alternatives": [{"condition": a["condition"], "unit": cents(a["price"]), "note": a.get("note", "")}
                                     for a in l.get("alternatives", [])]})
    return out


def _total(lines: list) -> int:
    return sum(l["qty"] * l["unit"] for l in lines)


class ProcurementMixin:
    # ----- route: who must approve, and why -----
    def _route(self, po: dict, at: str) -> dict:
        v = self.vendors[po["vendor_id"]]
        risk = assess(v, at)
        total = po["total"]
        flags, notes, refs = [], [], []
        if total > self.policy.dept_head_limit:
            flags.append("over_limit")
            notes.append(f"{usd(total)} is above the {usd(self.policy.dept_head_limit)} department limit")
        if risk.new_vendor and total > self.policy.new_vendor_controller_over:
            flags.append("new_vendor")
            notes.append(f"{v.name} has no completed order and the PO is above {usd(self.policy.new_vendor_controller_over)}")
        if risk.level == "strict":
            flags.append("strict_vendor")
            notes.append(f"{v.name} is strict: {risk.reasons[0]}")
        limit = self.budgets.get(po["dept"], 0)
        used = self.budget_used(po["dept"], exclude=po["id"])
        if used + total > limit:
            flags.append("over_budget")
            notes.append(f"{po['dept']} budget {usd(limit)}, committed {usd(used)}, this PO {usd(total)}")
        for l in po["lines"]:
            ref = self.mirror.get(l["sku"])
            r = resolve("market_price", [{"source": "mirror", "value": ref["price"], "as_of": ref["as_of"], "ref": ref.get("source", "")}] if ref else [], now=at)
            t = r["trusted"]
            if t:
                refs.append({"type": "mirror", "id": l["sku"], "detail": f"{usd(t['value'])} as of {t['as_of'][:10]} {ref.get('origin', 'MIRROR')}"})
                if l["unit"] > t["value"] * (1 + self.policy.mirror_above_pct):
                    flags.append("above_market")
                    notes.append(f"{l['sku']} at {usd(l['unit'])} is more than {int(self.policy.mirror_above_pct * 100)}% above the {usd(t['value'])} reference")
                elif l["unit"] < t["value"] * (1 - self.policy.mirror_below_pct):
                    flags.append("suspiciously_low")
                    notes.append(f"{l['sku']} at {usd(l['unit'])} is more than {int(self.policy.mirror_below_pct * 100)}% below the {usd(t['value'])} reference")
            elif ref:
                notes.append(f"{l['sku']}: market reference is stale, ignored")
        flags = list(dict.fromkeys(flags))
        two = "strict_vendor" in flags
        esc = [f for f in flags if f != "strict_vendor"]
        if two:
            needs = ["dept_head", "controller"]
        elif esc:
            needs = ["controller"]
        else:
            needs = ["dept_head"]
        req = self.people[po["requester"]]
        if req.role == "dept_head" and "dept_head" in needs:
            needs = [n if n != "dept_head" else "controller" for n in needs]
            needs = list(dict.fromkeys(needs))
            two = False
        return {"needs": needs, "two_person": two, "flags": flags, "notes": notes, "evidence": refs, "vendor_level": risk.level}

    # ----- request -----
    def request(self, *, requester: str, vendor_id: str, lines: list, at: str, justification: str = "",
                dept: Optional[str] = None, parent: Optional[str] = None, replans: int = 0) -> Outcome:
        at = self._now(at)
        denied = self._need(requester, "request", at, "po_request", f"requester:{requester}")
        if denied:
            return denied
        if vendor_id not in self.vendors:
            raise ValueError(f"unknown vendor {vendor_id}")
        req = self.people[requester]
        pid = self._next("po", "PO")
        lines = _clean_lines(lines)
        po = {"id": pid, "requester": requester, "dept": dept or req.dept, "vendor_id": vendor_id, "lines": lines,
              "total": _total(lines), "justification": justification, "status": "pending_approval", "created_at": at,
              "approvals": [], "committed": 0, "parent": parent, "replans": replans, "bound": None, "route": None,
              "invoices": [], "receipts": [], "paid": 0, "prepaid": 0, "approval_decisions": []}
        self.pos[pid] = po
        route = self._route(po, at)
        po["route"] = route
        d0 = self._d(at, "po_draft", f"po:{pid}", "drafted",
                     f"{req.name} asked for {', '.join(str(l['qty']) + 'x ' + l['sku'] for l in lines)} from {self.vendors[vendor_id].name} for {usd(po['total'])}",
                     rule="approval.route", actor={"kind": "person", "id": requester},
                     evidence=[{"type": "requisition", "id": pid, "detail": justification or "no justification given"}])
        d1 = self._d(at, "approval_route", f"po:{pid}", "routed",
                     "needs " + " and ".join(route["needs"]) + (" (two people)" if route["two_person"] else "")
                     + ("; " + "; ".join(route["notes"]) if route["notes"] else "; inside every limit"),
                     rule="approval.route", codes=tuple(route["flags"]) or ("standard",), parents=[d0.id],
                     evidence=[{"type": "vendor", "id": vendor_id, "detail": f"level {route['vendor_level']}"}, *route["evidence"]])
        po["route_decision"] = d1.id
        return Outcome(True, "pending_approval", [d0, d1], {"po": self.po_view(pid)})

    # ----- approve -----
    def approve(self, po_id: str, *, by: str, at: str, override_budget: bool = False, note: str = "") -> Outcome:
        at = self._now(at)
        po = self.pos[po_id]
        subj = f"po:{po_id}"
        req = self.people[po["requester"]]
        ev = [{"type": "po", "id": po_id, "detail": f"requester {req.id}"}]
        me = self.people.get(by)
        if me is not None and by == po["requester"]:  # separation of duties is checked before role, so the reason is the real one
            return self._deny(at, "po_approval", subj, by, "self_approval", f"{me.name} requested this PO and cannot approve it",
                              "sod.requester_cannot_approve", evidence=ev)
        if me is not None and (po["requester"] in me.acts_for or by in req.acts_for):
            return self._deny(at, "po_approval", subj, by, "delegate_of_requester", f"{me.name} acts for the requester {req.name}; a delegate cannot approve what the person delegating asked for",
                              "sod.requester_cannot_approve", evidence=ev)
        denied = self._need(by, "approve", at, "po_approval", subj)
        if denied:
            return denied
        if po["status"] != "pending_approval":
            return self._deny(at, "po_approval", subj, by, "not_pending", f"{po_id} is {po['status']}, not waiting for approval", "approval.route")
        if any(a["by"] == by for a in po["approvals"]):
            return self._deny(at, "po_approval", subj, by, "duplicate_approver", f"{me.name} already approved this PO; one person fills one signature",
                              "approval.authority", evidence=ev)
        route = self._route(po, at)  # fresh: vendor history and budget may have changed since the request
        po["route"] = route
        needs = route["needs"]
        role = me.role
        if role == "dept_head":
            if me.dept != po["dept"]:
                return self._deny(at, "po_approval", subj, by, "wrong_department", f"{me.name} heads {me.dept}, this PO is {po['dept']}", "approval.authority", evidence=ev)
            if po["total"] > self.policy.dept_head_limit:
                return self._deny(at, "po_approval", subj, by, "above_authority",
                                  f"{usd(po['total'])} is above the {usd(self.policy.dept_head_limit)} a department head can approve; the controller must", "approval.authority", evidence=ev)
        filled = [a["fills"] for a in po["approvals"]]
        fill = None
        if role == "controller":
            if "controller" in needs and "controller" not in filled:
                fill = "controller"
            elif "dept_head" in needs and not route["two_person"] and "dept_head" not in filled:
                fill = "dept_head"
        elif role == "dept_head" and "dept_head" in needs and "dept_head" not in filled:
            fill = "dept_head"
        if fill is None:
            codes = [f for f in route["flags"] if f != "strict_vendor"] + ["controller_required"]
            why = "; ".join(route["notes"]) or "this PO needs the controller"
            primary = "over_budget" if "over_budget" in route["flags"] else "controller_required"
            d = self._d(at, "po_approval", subj, "denied", f"{me.name} ({role}) cannot approve this: {why}. {'Needs ' + ' and '.join(needs)}.",
                        rule="approval.budget" if primary == "over_budget" else "approval.authority", codes=codes,
                        evidence=[{"type": "person", "id": by, "detail": "attempted by"}, *ev], parents=[po["route_decision"]])
            return Outcome(False, "denied", [d], {"code": primary})
        if "over_budget" in route["flags"] and not override_budget:
            return self._deny(at, "po_approval", subj, by, "budget_override_required",
                              "the PO is over its department budget; the controller must approve with an explicit budget override",
                              "approval.budget", evidence=ev, parents=[po["route_decision"]])
        a = {"by": by, "role": role, "fills": fill, "at": at, "note": note, "override_budget": bool(override_budget and "over_budget" in route["flags"])}
        po["approvals"].append(a)
        filled = {x["fills"] for x in po["approvals"]}
        done = all(n in filled for n in needs)
        d = self._d(at, "po_approval", subj, "approved" if done else "partially_approved",
                    f"{me.name} approved as {fill}" + (" with a budget override" if a["override_budget"] else "") + (". All required signatures are in." if done else f". Still needs {', '.join(n for n in needs if n not in filled)}."),
                    rule="approval.route", actor={"kind": "person", "id": by}, codes=tuple(route["flags"]) or ("standard",),
                    evidence=ev, parents=[po["route_decision"]])
        po["approval_decisions"].append(d.id)
        decs = [d]
        if done:
            decs.append(self._bind(po, at, d.id))
        return Outcome(True, po["status"], decs, {"po": self.po_view(po_id)})

    def _bind(self, po: dict, at: str, parent: str):
        v = self.vendors[po["vendor_id"]]
        from hyphenate.matching import line_tolerance
        ceiling = sum(l["qty"] * l["unit"] + line_tolerance(l["qty"] * l["unit"], self.policy, False) for l in po["lines"])
        bound = {"deal_id": po["id"], "payee": v.payee_id, "currency": "USD", "ceiling": ceiling, "approval_ids": list(po["approval_decisions"])}
        bound["hash"] = hashlib.sha256(json.dumps({k: bound[k] for k in ("deal_id", "payee", "currency", "ceiling")}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        po["bound"] = bound
        po["status"] = "approved"
        po["committed"] = po["total"]
        return self._d(at, "approval_bind", f"po:{po['id']}", "bound",
                       f"approval binds deal {po['id']}, payee {v.payee_id}, ceiling {usd(ceiling)} (PO {usd(po['total'])} plus immaterial tolerance); a charge can only match these terms",
                       rule="approval.bind", parents=[parent], evidence=[{"type": "binding_hash", "id": bound["hash"][:16], "detail": "sha256 over deal, payee, currency, ceiling"}])

    # ----- reject, re-plan, drop -----
    def reject(self, po_id: str, *, by: str, at: str, reason: str, max_amount: Optional[float] = None) -> Outcome:
        at = self._now(at)
        po = self.pos[po_id]
        subj = f"po:{po_id}"
        denied = self._need(by, "reject", at, "po_reject", subj)
        if denied:
            return denied
        if po["status"] != "pending_approval":
            return self._deny(at, "po_reject", subj, by, "not_pending", f"{po_id} is {po['status']}", "approval.route")
        if by == po["requester"]:
            return self._deny(at, "po_reject", subj, by, "self_approval", "the requester withdraws a PO, they do not reject it", "sod.requester_cannot_approve")
        cap = cents(max_amount) if max_amount is not None else None
        d = self._d(at, "po_reject", subj, "rejected", f"{self.people[by].name} said no: {reason}" + (f" (will consider up to {usd(cap)})" if cap is not None else ""),
                    rule="replan.after_no", actor={"kind": "person", "id": by}, codes=("controller_no" if self.people[by].role == "controller" else "approver_no",),
                    parents=[po["route_decision"]], evidence=[{"type": "person", "id": by, "detail": reason}])
        po["status"] = "rejected"
        po["committed"] = 0
        out = self._replan(po, at, cap, d)
        return Outcome(True, po["status"], [d, *out.decisions], {"po": self.po_view(po_id), "replan": out.data})

    def _replan(self, po: dict, at: str, cap: Optional[int], rejection) -> Outcome:
        if po["replans"] >= self.policy.max_replans:
            return self._drop(po, at, rejection, f"already re-planned {po['replans']} times")
        lines = copy.deepcopy(po["lines"])
        changed = []
        for l in lines:
            alts = [a for a in l["alternatives"] if a["condition"] in l["allowed"] and a["unit"] < l["unit"]]
            if alts:
                best = min(alts, key=lambda a: a["unit"])
                changed.append(f"{l['sku']} {l['condition']} {usd(l['unit'])} -> {best['condition']} {usd(best['unit'])}")
                l["unit"], l["condition"] = best["unit"], best["condition"]
            l["alternatives"] = []
        total = _total(lines)
        if cap is not None:
            while total > cap:
                cand = [l for l in lines if l["qty"] > l["min_qty"]]
                if not cand:
                    break
                big = max(cand, key=lambda l: l["qty"] * l["unit"])
                big["qty"] -= 1
                changed.append(f"{big['sku']} quantity -> {big['qty']}")
                total = _total(lines)
        if not changed or total >= po["total"] or (cap is not None and total > cap):
            return self._drop(po, at, rejection, "no allowed alternative fits" + (f" under {usd(cap)}" if cap is not None else " (nothing cheaper in an allowed condition)"))
        for l in lines:
            l["accepted_conditions"], l["accepted"], l["rejected"], l["billed"] = [], 0, 0, 0
        child = self.request(requester=po["requester"], vendor_id=po["vendor_id"], at=at, justification=f"re-plan of {po['id']} after a no: " + "; ".join(changed),
                             lines=[{"sku": l["sku"], "desc": l["desc"], "qty": l["qty"], "unit": l["unit"], "condition": l["condition"], "allowed": l["allowed"],
                                     "serialized": l["serialized"], "min_qty": l["min_qty"]} for l in lines], dept=po["dept"], parent=po["id"], replans=po["replans"] + 1)
        cpo = self.pos[child.data["po"]["id"]]
        d = self._d(at, "replan", f"po:{po['id']}", "replanned",
                    f"re-planned as {cpo['id']} at {usd(cpo['total'])} (was {usd(po['total'])}): {'; '.join(changed)}. It needs approval again.",
                    rule="replan.after_no", actor={"kind": "rule", "id": "replan.after_no"}, parents=[rejection.id],
                    evidence=[{"type": "po", "id": cpo["id"], "detail": "new PO"}])
        po["status"] = "replanned"
        po["replanned_to"] = cpo["id"]
        return Outcome(True, "replanned", [d, *child.decisions], {"child": cpo["id"]})

    def _drop(self, po: dict, at: str, rejection, why: str) -> Outcome:
        po["status"] = "dropped"
        po["committed"] = 0
        d = self._d(at, "replan", f"po:{po['id']}", "dropped", f"dropped: {why}. The department budget is released and {self.people[po['requester']].name} is told.",
                    rule="replan.after_no", parents=[rejection.id], codes=("dropped",))
        return Outcome(True, "dropped", [d], {"dropped": po["id"]})

    # ----- receiving -----
    def receive(self, po_id: str, *, by: str, at: str, lines: list) -> Outcome:
        at = self._now(at)
        po = self.pos[po_id]
        subj = f"po:{po_id}"
        approvers = {a["by"] for a in po["approvals"]}
        if by == po["requester"] or by in approvers:
            return self._deny(at, "receiving", subj, by, "receiver_not_independent", f"{self.people[by].name} requested or approved this PO and cannot also receive it", "sod.receiver_independent")
        denied = self._need(by, "receive", at, "receiving", subj)
        if denied:
            return denied
        if po["status"] not in ("approved", "partially_received"):
            return self._deny(at, "receiving", subj, by, "po_not_open", f"{po_id} is {po['status']}; goods are received against an approved PO", "receive.check")
        v = self.vendors[po["vendor_id"]]
        rid = self._next("rcv", "RCV")
        acc_value, rej_value, results, seen = 0, 0, [], set()
        for rl in lines:
            qty = rl["qty"]
            pl = next((l for l in po["lines"] if l["sku"] == rl["sku"]), None)
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                raise ValueError("received qty must be a positive whole number")
            res = {"sku": rl["sku"], "qty": qty, "condition": rl.get("condition", "new"), "serials": list(rl.get("serials", [])), "accepted": 0, "rejected": 0, "reasons": []}
            if pl is None:
                res["rejected"], res["reasons"] = qty, ["unexpected_sku"]
            elif not rl.get("ok", True):
                res["rejected"], res["reasons"] = qty, list(rl.get("reasons") or ["failed_check"])
            else:
                reasons = []
                sers = res["serials"]
                if pl["serialized"] and len(sers) != qty:
                    reasons.append("serial_missing")
                dup = [s for s in sers if s in self.serials or s in seen]
                if dup:
                    reasons.append("duplicate_serial")
                if res["condition"] not in pl["allowed"]:
                    reasons.append("condition_not_allowed")
                if reasons:
                    res["rejected"], res["reasons"] = qty, reasons
                else:
                    room = pl["qty"] - pl["accepted"]
                    take = min(qty, room)
                    res["accepted"], res["rejected"] = take, qty - take
                    if qty > take:
                        res["reasons"].append("over_delivery")
                    seen.update(sers[:take])
            if pl is not None:
                pl["accepted"] += res["accepted"]
                pl["rejected"] += res["rejected"]
                pl["accepted_conditions"] += [res["condition"]] * res["accepted"]
                pl["reject_reasons"] += res["reasons"] if res["rejected"] else []
            acc_value += res["accepted"] * (pl["unit"] if pl else 0)
            rej_value += res["rejected"] * (pl["unit"] if pl else 0)
            results.append(res)
        for res in results:
            if res["accepted"]:
                for s in res["serials"][:res["accepted"]]:
                    self.serials[s] = rid
        rec = {"id": rid, "po_id": po_id, "by": by, "at": at, "lines": results, "accepted_value": acc_value, "rejected_value": rej_value}
        self.receipts[rid] = rec
        po["receipts"].append(rid)
        n_acc, n_rej = sum(r["accepted"] for r in results), sum(r["rejected"] for r in results)
        failed = n_rej > 0
        codes = sorted({c for r in results for c in r["reasons"]})
        d = self._d(at, "receiving", subj, "failed" if failed else "accepted",
                    f"{self.people[by].name} received {n_acc} unit(s) accepted and {n_rej} rejected" + (f" ({', '.join(codes)})" if codes else ""),
                    rule="receive.check", actor={"kind": "person", "id": by}, codes=tuple(codes) or ("clean",),
                    evidence=[{"type": "receiving", "id": rid, "detail": "; ".join(f"{r['sku']} accepted {r['accepted']} rejected {r['rejected']} {r['condition']}" for r in results)}])
        decs = [d]
        if failed:
            v.add("failed_receiving", at, by, ", ".join(codes) or "failed check")
            decs.append(self._d(at, "vendor_history", f"vendor:{v.id}", "noted", f"{v.name}: failed receiving check recorded; strict matching and a second signature apply for {120} days",
                                rule="vendor.history", codes=("failed_receiving",), parents=[d.id]))
        if acc_value:
            if v.terms == "prepay":
                lines_ = [Line("1500", debit=acc_value), Line("1200", credit=acc_value, party=v.id)]
                why = f"goods accepted on prepaid PO {po_id}: draw down the deposit"
            else:
                lines_ = [Line("1500", debit=acc_value), Line("2100", credit=acc_value, party=v.id)]
                why = f"accrue goods received and not yet billed on {po_id}"
            e, jd, moved = self._post(at=at, date=at[:10], lines=lines_, reason=why, refs=[f"po:{po_id}", f"receiving:{rid}"], subject=subj, kind="accrual",
                                      rule="receive.accrue", parents=[d.id], codes=("accrued",))
            decs += [x for x in (moved, jd) if x]
        if rej_value and v.terms == "prepay":
            e, jd, moved = self._post(at=at, date=at[:10], lines=[Line("1300", debit=rej_value, party=v.id), Line("1200", credit=rej_value, party=v.id)],
                                      reason=f"refund due: prepaid goods rejected on {po_id}", refs=[f"po:{po_id}", f"receiving:{rid}"], subject=subj, kind="vendor_credit",
                                      rule="receive.accrue", parents=[d.id], codes=("refund_due",))
            decs += [x for x in (moved, jd) if x]
            decs += self._memo(po, None, [{"code": "goods_rejected", "detail": ", ".join(codes), "credit": rej_value}], at, d.id)
        done = all(l["accepted"] >= l["qty"] for l in po["lines"])
        po["status"] = "received" if done else ("partially_received" if any(l["accepted"] for l in po["lines"]) else po["status"])
        return Outcome(True, po["status"], decs, {"receipt": rec, "po": self.po_view(po_id)})

    # ----- views -----
    def po_view(self, po_id: str) -> dict:
        p = self.pos[po_id]
        return {k: p[k] for k in ("id", "requester", "dept", "vendor_id", "status", "total", "justification", "created_at", "committed", "parent",
                                  "replans", "bound", "route", "invoices", "receipts", "paid", "prepaid")} | {
            "approvals": list(p["approvals"]), "lines": [{k: v for k, v in l.items() if k != "alternatives"} | {"alternatives": l["alternatives"]} for l in p["lines"]],
            "replanned_to": p.get("replanned_to")}
