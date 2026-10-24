"""Accounts-payable seat: invoice intake and three-way match, credit memos, payment under the mandate guard, bank
reconciliation, vendor bank changes and period close."""
from __future__ import annotations

import datetime
import re
from typing import Optional

from hyphenate.company import Outcome
from hyphenate.ledger import LedgerError, Line
from hyphenate.matching import Finding, match_lines
from hyphenate.money import cents, usd
from hyphenate.trust import resolve
from hyphenate.vendors import assess
from pay.mandate import can_charge, mandate_hash, mark_used, new_mandate, parse_ts

HOLD_RULE = {"possible_duplicate": "match.duplicate", "remit_to_mismatch": "match.remit_to", "arithmetic": "match.arithmetic", "claim_false": "match.claim"}


def _norm(number: str) -> str:
    """Invoice numbers compare without case, punctuation or leading zeros: 'INV-0042', 'inv 42' and 'Inv42' are one number."""
    s = re.sub(r"[^a-z0-9]", "", str(number).lower())
    return re.sub(r"(?<=[a-z])0+(?=\d)|^0+(?=\d)", "", s)


class PayablesMixin:
    # ----- credit memo requests -----
    def _memo(self, po: dict, inv: Optional[dict], items: list, at: str, parent: str) -> list:
        amount = sum(i["credit"] for i in items)
        if amount <= 0:
            return []
        v = self.vendors[po["vendor_id"]]
        mid = self._next("cm", "CM")
        ref = f"invoice {inv['number']} on {po['id']}" if inv else f"prepaid {po['id']}"
        text = (f"Credit memo request {mid} to {v.name}: {ref}. " + "; ".join(f"{i['code']}: {i['detail']}" for i in items) +
                f". We ask for a credit of {usd(amount)} or a corrected invoice.")
        memo = {"id": mid, "vendor_id": v.id, "po_id": po["id"], "invoice_id": inv["id"] if inv else None, "amount": amount,
                "reasons": [i["code"] for i in items], "status": "requested", "requested_at": at, "text": text}
        self.memos[mid] = memo
        d = self._d(at, "credit_memo_request", f"memo:{mid}", "requested", f"asked {v.name} for a credit of {usd(amount)}: " + "; ".join(i["code"] for i in items),
                    rule="match.three_way", codes=tuple(i["code"] for i in items), parents=[parent],
                    evidence=[{"type": "invoice" if inv else "po", "id": inv["id"] if inv else po["id"], "detail": text}])
        return [d]

    def credit_memo_issued(self, memo_id: str, *, at: str, by: str = "ap-agent") -> Outcome:
        at = self._now(at)
        m = self.memos[memo_id]
        m["status"] = "credited"
        d = self._d(at, "credit_memo", f"memo:{memo_id}", "credited", f"{self.vendors[m['vendor_id']].name} issued the credit memo for {usd(m['amount'])}; the held bill is closed out by their corrected invoice",
                    rule="match.three_way", actor={"kind": "data", "id": f"vendor-memo:{memo_id}"}, evidence=[{"type": "memo", "id": memo_id, "detail": m["text"]}])
        return Outcome(True, "credited", [d], {"memo": m})

    # ----- invoice intake and match -----
    def invoice(self, *, po_id: str, number: str, date: str, lines: list, at: str, id: Optional[str] = None, remit_to: Optional[str] = None,
                total: Optional[float] = None, claim: Optional[dict] = None, supersedes: Optional[str] = None, vendor_id: Optional[str] = None) -> Outcome:
        po = self.pos[po_id]
        v = self.vendors[po["vendor_id"]]
        # validate every input before any state changes: a bad invoice must not burn a number or half-book
        try:
            datetime.date.fromisoformat(date)
        except (TypeError, ValueError):
            raise ValueError(f"invoice date must be YYYY-MM-DD, got {date!r}")
        if not isinstance(number, str) or not number.strip():
            raise ValueError("invoice number is required")
        at = self._now(at)
        iid = id or self._next("inv", "INV")
        subj = f"invoice:{iid}"
        inv_lines = [{"sku": l["sku"], "qty": int(l["qty"]), "unit": cents(l["price"]), "condition": l.get("condition", "new")} for l in lines]
        if not inv_lines or any(l["qty"] <= 0 or l["unit"] <= 0 for l in inv_lines):
            raise ValueError("invoice needs lines with positive quantities and prices")
        computed = sum(l["qty"] * l["unit"] for l in inv_lines)
        stated = cents(total) if total is not None else computed
        inv = {"id": iid, "po_id": po_id, "vendor_id": v.id, "number": number, "date": date, "lines": inv_lines, "total": stated, "computed": computed,
               "remit_to": remit_to, "claim": claim, "status": "received", "received_at": at, "findings": [], "payable": 0, "supersedes": supersedes}
        self.invoices[iid] = inv
        try:
            return self._intake(po, v, inv, iid, subj, inv_lines, stated, computed, number, date, at, remit_to, claim, supersedes, vendor_id)
        except Exception:
            self.invoices.pop(iid, None)  # nothing half-booked stays behind; the decision log keeps the attempt
            raise

    def _intake(self, po, v, inv, iid, subj, inv_lines, stated, computed, number, date, at, remit_to, claim, supersedes, vendor_id) -> Outcome:
        po_id = po["id"]
        d_in = self._d(at, "invoice_received", subj, "received", f"invoice {number} from {v.name} for {usd(stated)} against {po_id}", rule="match.three_way",
                       actor={"kind": "data", "id": f"invoice:{iid}"}, evidence=[{"type": "invoice", "id": iid, "detail": f"{len(inv_lines)} line(s), dated {date}"}])
        findings: list[Finding] = []
        trust: list = []
        # duplicates: same number, or same vendor + PO + lines + total inside the window
        key = _norm(number)
        dup = next((o for o in self.invoices.values() if o["id"] != iid and o["vendor_id"] == v.id and _norm(o["number"]) == key), None)
        if dup:
            inv["status"] = "rejected_duplicate"
            d = self._d(at, "invoice_match", subj, "denied", f"invoice number {number} from {v.name} was already received as {dup['id']} ({dup['status']}); not booked twice",
                        rule="match.duplicate", codes=("duplicate_invoice",), parents=[d_in.id], evidence=[{"type": "invoice", "id": dup["id"], "detail": f"same vendor, same number {dup['number']}"}])
            return Outcome(False, "rejected_duplicate", [d_in, d], {"invoice": inv, "code": "duplicate_invoice"})
        sig = sorted((l["sku"], l["qty"], l["unit"]) for l in inv_lines)
        for o in self.invoices.values():
            if o["id"] == iid or o["vendor_id"] != v.id or o["po_id"] != po_id or o["status"] in ("superseded", "rejected_duplicate") or o["id"] == supersedes:
                continue
            same = sorted((l["sku"], l["qty"], l["unit"]) for l in o["lines"]) == sig and o["total"] == stated
            days = abs((parse_ts(at) - parse_ts(o["received_at"])).days)
            if same and days <= self.policy.duplicate_window_days:
                findings.append(Finding("possible_duplicate", "", f"same vendor, PO, lines and total as {o['id']} ({o['number']}) received {days} day(s) earlier"))
                break
        if supersedes and supersedes in self.invoices and self.invoices[supersedes]["status"] == "held":
            self.invoices[supersedes]["status"] = "superseded"
        if po["status"] not in self.APPROVED_STATES:
            findings.append(Finding("po_not_approved", "", f"{po_id} is {po['status']}; nothing can be billed against it"))
        if vendor_id and vendor_id != v.id:
            findings.append(Finding("vendor_mismatch", "", f"invoice came from {vendor_id} but the PO is with {v.id}"))
        if remit_to and remit_to != v.bank_account:
            trust.append(resolve("remit_account", [{"source": "vendor_master", "value": v.bank_account, "ref": f"vendor:{v.id}"}, {"source": "seller_claim", "value": remit_to, "ref": f"invoice:{iid}"}]))
            findings.append(Finding("remit_to_mismatch", "", "invoice asks to pay a different bank account than the verified vendor master"))
        if stated != computed:
            findings.append(Finding("arithmetic", "", f"total {usd(stated)} but the lines add to {usd(computed)}", stated - computed if stated > computed else 0))
        risk = assess(v, at)
        mf = match_lines(po["lines"], inv_lines, self.policy, strict=risk.price_tolerance_zero) if po["status"] in self.APPROVED_STATES else []
        findings += mf
        for l in po["lines"]:
            if any(f.code == "qty_short" and f.sku == l["sku"] for f in mf) and l["rejected"]:
                findings.append(Finding("rejected_goods_billed", l["sku"], f"{l['rejected']} unit(s) were rejected at receiving ({', '.join(sorted(set(l['reject_reasons'])))}) and are still billed"))
        for f in mf:
            pl = next((l for l in po["lines"] if l["sku"] == f.sku), None)
            il = next((l for l in inv_lines if l["sku"] == f.sku), None)
            if not pl or not il:
                continue
            if f.code == "condition_mismatch":
                got = next((c for c in pl["accepted_conditions"] if c != il["condition"]), pl["condition"])
                trust.append(resolve("goods_condition", [{"source": "seller_claim", "value": il["condition"], "ref": f"invoice:{iid}"}, {"source": "receiving", "value": got, "ref": "receiving"}]))
            if f.code in ("price_variance", "price_variance_immaterial"):
                trust.append(resolve("agreed_price", [{"source": "seller_claim", "value": il["unit"], "ref": f"invoice:{iid}"}, {"source": "contract", "value": pl["unit"], "ref": f"po:{po_id}"}]))
            if f.code in ("qty_short", "billed_before_receipt"):
                trust.append(resolve("goods_quantity", [{"source": "seller_claim", "value": pl["billed"] + il["qty"], "ref": f"invoice:{iid}"}, {"source": "receiving", "value": pl["accepted"], "ref": "receiving"}]))
        if claim and claim.get("result") == "false":
            findings.append(Finding("claim_false", "", f"independent page check says the claim does not hold: {claim.get('reason', 'see evidence')}"))
        inv["findings"] = [f.to_dict() for f in findings]
        tds = []
        for r in trust:
            if r["trusted"] and not r["agreed"]:
                tds.append(self._d(at, "source_trust", subj, "resolved", r["reason"], rule="match.three_way", codes=(f"trust_{r['field']}",),
                                   parents=[d_in.id], evidence=[{"type": o["source"], "id": str(o.get("ref", "")), "detail": str(o["value"])} for o in [r["trusted"], *r["disagreeing"]]]))
        holds = [f for f in findings if f.hold]
        decs = [d_in, *tds]
        if holds:
            inv["status"] = "held"
            codes = sorted({f.code for f in holds})
            rule = next((HOLD_RULE[c] for c in codes if c in HOLD_RULE), "match.three_way")
            ev = [{"type": "po", "id": po_id, "detail": usd(po["total"])}, {"type": "invoice", "id": iid, "detail": usd(stated)}]
            ev += [{"type": "receiving", "id": r, "detail": ""} for r in po["receipts"]]
            if risk.level != "normal":
                ev.append({"type": "vendor", "id": v.id, "detail": f"level {risk.level}: {risk.reasons[0] if risk.reasons else ''}"})
            d = self._d(at, "invoice_match", subj, "hold", "held: " + "; ".join(f"{f.code} ({f.detail})" for f in holds), rule=rule, codes=tuple(codes),
                        parents=[d_in.id, *[t.id for t in tds]], evidence=ev)
            decs.append(d)
            inv["match_decision"] = d.id
            decs += self._memo(po, inv, [f.to_dict() for f in holds], at, d.id)
            return Outcome(False, "held", decs, {"invoice": inv, "codes": codes})
        return self._book_bill(po, inv, v, findings, decs, d_in, at)

    def _book_bill(self, po, inv, v, findings, decs, d_in, at) -> Outcome:
        """Post first, mutate after: if the ledger refuses, nothing about the PO or invoice has changed."""
        subj = f"invoice:{inv['id']}"
        unit_of = {p["sku"]: p["unit"] for p in po["lines"]}
        accrual = sum(l["qty"] * unit_of[l["sku"]] for l in inv["lines"])
        variance = inv["total"] - accrual
        notes = [f.detail for f in findings if not f.hold]
        refs = [f"po:{po['id']}", f"invoice:{inv['id']}"]

        def commit(status: str, payable: int) -> None:
            for l in inv["lines"]:
                next(p for p in po["lines"] if p["sku"] == l["sku"])["billed"] += l["qty"]
            inv["payable"], inv["status"] = payable, status
            po["invoices"].append(inv["id"])

        if v.terms == "prepay":
            lines = []
            if variance > 0:
                lines = [Line("5900", debit=variance), Line("2000", credit=variance, party=v.id)]
            elif variance < 0:
                lines = [Line("1300", debit=-variance, party=v.id), Line("5900", credit=-variance)]
            if lines:
                e, jd, moved = self._post(at=at, date=inv["date"], lines=lines, reason=f"prepaid invoice {inv['number']} price variance", refs=refs, subject=subj, kind="bill_posting",
                                          rule="post.bill", parents=[d_in.id], codes=("prepaid_variance",))
                decs += [x for x in (moved, jd) if x]
                inv["match_decision"] = jd.id
            else:
                d = self._d(at, "invoice_match", subj, "matched", "matched against PO and receiving; already paid by deposit, nothing to book", rule="match.three_way", codes=("matched",), parents=[d_in.id])
                decs.append(d)
                inv["match_decision"] = d.id
            commit("matched" if variance > 0 else "matched_prepaid", variance if variance > 0 else 0)
            return Outcome(True, inv["status"], decs, {"invoice": inv})
        lines = [Line("2100", debit=accrual, party=v.id)]
        if variance > 0:
            lines.append(Line("5900", debit=variance))
        lines.append(Line("2000", credit=inv["total"], party=v.id))
        if variance < 0:
            lines.append(Line("5900", credit=-variance))
        e, jd, moved = self._post(at=at, date=inv["date"], lines=lines,
                                  reason=f"bill {inv['number']}: reverse accrual {usd(accrual)}, book payable {usd(inv['total'])}" + (f", variance {usd(variance)} to price variance" if variance else ""),
                                  refs=refs, subject=subj, kind="bill_posting", rule="post.bill", parents=[d_in.id],
                                  evidence=[{"type": "po", "id": po["id"], "detail": usd(po["total"])}, *[{"type": "receiving", "id": r, "detail": ""} for r in po["receipts"]]],
                                  codes=("matched", *(("price_variance_immaterial",) if variance else ())))
        decs += [x for x in (moved, jd) if x]
        inv["match_decision"] = jd.id
        inv["entry"] = e.id
        commit("matched", inv["total"])
        return Outcome(True, "matched", decs, {"invoice": inv, "entry": e.to_dict(), "notes": notes})

    # ----- payment -----
    def build_mandate(self, po_id: str, amount_cents: int, at: str) -> dict:
        po = self.pos[po_id]
        m = new_mandate(deal_id=po_id, buyer_id=self.id, amount=amount_cents / 100, payee=po["bound"]["payee"], now=parse_ts(at), origin="SIM")
        m["status"], m["approval_id"] = "approved", po["approval_decisions"][-1]
        return m

    def _pay_gate(self, po, v, at, by, subj, kind, amount) -> Optional[Outcome]:
        denied = self._need(by, "release_payment", at, kind, subj)
        if denied:
            return denied
        me = self.people[by]
        if me.role != "ap_agent" and (by == po["requester"] or by in {a["by"] for a in po["approvals"]}):
            return self._deny(at, kind, subj, by, "payer_not_independent", f"{me.name} requested or approved this PO and cannot release its payment", "sod.payer_independent")
        if po["status"] not in self.APPROVED_STATES or not po["bound"]:
            return self._deny(at, kind, subj, by, "po_not_approved", f"{po['id']} has no complete approval", "pay.gate")
        if not v.bank_verified:
            ch = next((e for e in reversed(v.events) if e.kind == "bank_change"), None)
            return self._deny(at, kind, subj, by, "bank_unverified",
                              f"{v.name}'s bank details changed on {ch.at[:10] if ch else '?'} by {ch.by if ch else '?'} and no second person has verified them; payment held",
                              "pay.gate", evidence=[{"type": "vendor", "id": v.id, "detail": "bank_change unverified"}])
        if po["paid"] + po["prepaid"] + amount > po["bound"]["ceiling"]:
            return self._deny(at, kind, subj, by, "over_ceiling", f"paying {usd(amount)} would take the PO to {usd(po['paid'] + po['prepaid'] + amount)}, above the approved ceiling {usd(po['bound']['ceiling'])}", "approval.bind")
        return None

    def _charge(self, po, v, at, by, subj, kind, amount, mandate, parents) -> tuple:
        m = mandate or self.build_mandate(po["id"], amount, at)
        verdict = can_charge(m, parse_ts(at), deal_id=po["id"], amount=amount / 100, payee=po["bound"]["payee"], store=self.store, buyer_id=self.id)
        if not verdict:
            d = self._d(at, kind, subj, "blocked", f"charge refused by the mandate guard: {verdict.reason} ({verdict.detail}); the mandate does not match the approved PO {po['id']}",
                        rule="pay.mandate", codes=(f"mandate_{verdict.reason}",), parents=parents,
                        evidence=[{"type": "mandate", "id": str(m.get("id", "?")), "detail": f"amount {m.get('amount')} payee {m.get('payee')}"}])
            return None, Outcome(False, "blocked", [d], {"code": f"mandate_{verdict.reason}"})
        mark_used(m, deal_id=po["id"], amount=amount / 100, payee=po["bound"]["payee"], store=self.store, now=parse_ts(at), buyer_id=self.id)
        return m, None

    def pay(self, invoice_id: str, *, at: str, by: str = "ap-agent", mandate: Optional[dict] = None) -> Outcome:
        at = self._now(at)
        inv = self.invoices[invoice_id]
        po = self.pos[inv["po_id"]]
        v = self.vendors[po["vendor_id"]]
        subj = f"invoice:{invoice_id}"
        if inv["status"] != "matched":
            return self._deny(at, "payment_release", subj, by, "already_paid" if inv["status"] == "paid" else "invoice_not_matched",
                              f"invoice {inv['number']} is {inv['status']}; only a matched bill is paid", "pay.gate", parents=[inv["match_decision"]] if inv.get("match_decision") else ())
        amount = inv["payable"]
        blocked = self._pay_gate(po, v, at, by, subj, "payment_release", amount)
        if blocked:
            return blocked
        parents = [inv["match_decision"], *po["approval_decisions"]]
        m, fail = self._charge(po, v, at, by, subj, "payment_release", amount, mandate, parents)
        if fail:
            return fail
        pid = self._next("pay", "PAY")
        mh = mandate_hash(m)
        e, d, moved = self._post(at=at, date=at[:10], lines=[Line("2000", debit=amount, party=v.id), Line("1000", credit=amount)], reason=f"pay invoice {inv['number']} to {v.name} under mandate {mh[:12]}",
                                 refs=[f"po:{po['id']}", f"invoice:{invoice_id}", f"payment:{pid}"], subject=subj, kind="payment_release", rule="pay.gate", parents=parents,
                                 evidence=[{"type": "mandate", "id": mh[:16], "detail": f"deal {po['id']} payee {m['payee']} amount {usd(amount)}"}, {"type": "binding", "id": po["bound"]["hash"][:16], "detail": "approval binding"}],
                                 outcome="released", codes=("released",))
        self.payments[pid] = {"id": pid, "kind": "payment", "invoice_id": invoice_id, "po_id": po["id"], "vendor_id": v.id, "amount": amount, "payee": m["payee"], "mandate_hash": mh,
                              "ref": f"pi_sim_{mh[:10]}", "at": at, "source": "SIM", "reconciled": False, "decision": d.id}
        po["paid"] += amount
        inv["status"] = "paid"
        self._maybe_close(po, at)
        return Outcome(True, "paid", [x for x in (moved, d) if x], {"payment": self.payments[pid], "entry": e.to_dict()})

    def prepay(self, po_id: str, *, at: str, by: str = "ap-agent", mandate: Optional[dict] = None) -> Outcome:
        at = self._now(at)
        po = self.pos[po_id]
        v = self.vendors[po["vendor_id"]]
        subj = f"po:{po_id}"
        if v.terms != "prepay":
            return self._deny(at, "prepayment", subj, by, "not_prepay_vendor", f"{v.name} is on {v.terms} terms; it is paid against a matched bill", "pay.gate")
        amount = po["total"]
        blocked = self._pay_gate(po, v, at, by, subj, "prepayment", amount)
        if blocked:
            return blocked
        m, fail = self._charge(po, v, at, by, subj, "prepayment", amount, mandate, list(po["approval_decisions"]))
        if fail:
            return fail
        pid = self._next("pay", "PAY")
        mh = mandate_hash(m)
        e, d, moved = self._post(at=at, date=at[:10], lines=[Line("1200", debit=amount, party=v.id), Line("1000", credit=amount)], reason=f"prepay {po_id} to {v.name} under mandate {mh[:12]}",
                                 refs=[f"po:{po_id}", f"payment:{pid}"], subject=subj, kind="prepayment", rule="pay.gate", parents=list(po["approval_decisions"]),
                                 evidence=[{"type": "mandate", "id": mh[:16], "detail": f"deal {po_id} payee {m['payee']}"}], outcome="released", codes=("released", "prepaid"))
        self.payments[pid] = {"id": pid, "kind": "prepayment", "invoice_id": None, "po_id": po_id, "vendor_id": v.id, "amount": amount, "payee": m["payee"], "mandate_hash": mh,
                              "ref": f"pi_sim_{mh[:10]}", "at": at, "source": "SIM", "reconciled": False, "decision": d.id}
        po["prepaid"] += amount
        return Outcome(True, "prepaid", [x for x in (moved, d) if x], {"payment": self.payments[pid], "entry": e.to_dict()})

    def _maybe_close(self, po, at) -> None:
        if po["status"] in ("received", "partially_received", "approved") and all(l["billed"] >= l["qty"] for l in po["lines"]) \
                and all(self.invoices[i]["status"] in ("paid", "matched_prepaid", "superseded") for i in po["invoices"]):
            po["status"] = "closed"
            po["committed"] = po["paid"]
            self.vendors[po["vendor_id"]].add("completed_order", at, "ap-agent", po["id"])

    def close_po(self, po_id: str, *, at: str, by: str = "ap-agent") -> Outcome:
        """Close an order early (a short delivery that will not be completed). Prepaid money that bought nothing becomes a vendor credit."""
        at = self._now(at)
        po = self.pos[po_id]
        v = self.vendors[po["vendor_id"]]
        subj = f"po:{po_id}"
        denied = self._need(by, "post_bill", at, "po_close", subj)
        if denied:
            return denied
        decs = []
        if v.terms == "prepay" and po["prepaid"]:
            received = sum(l["accepted"] * l["unit"] for l in po["lines"])
            rejected_reclass = sum(l["rejected"] * l["unit"] for l in po["lines"])
            outstanding = po["prepaid"] - received - rejected_reclass
            if outstanding > 0:
                e, d, moved = self._post(at=at, date=at[:10], lines=[Line("1300", debit=outstanding, party=v.id), Line("1200", credit=outstanding, party=v.id)],
                                         reason=f"close {po_id}: prepaid goods never delivered become a vendor credit", refs=[f"po:{po_id}"], subject=subj, kind="vendor_credit",
                                         rule="receive.accrue", codes=("refund_due",), parents=list(po["approval_decisions"]))
                decs += [x for x in (moved, d) if x]
                decs += self._memo(po, None, [{"code": "short_delivery", "detail": f"{usd(outstanding)} prepaid for units never delivered", "credit": outstanding}], at, d.id)
        po["status"] = "closed"
        po["committed"] = sum(l["accepted"] * l["unit"] for l in po["lines"])
        short = any(l["accepted"] < l["qty"] for l in po["lines"])
        decs.append(self._d(at, "po_close", subj, "closed", f"closed with {sum(l['accepted'] for l in po['lines'])} of {sum(l['qty'] for l in po['lines'])} units delivered; budget commitment released down to what was received",
                            rule="post.bill", codes=("closed_short",) if short else ("closed",), parents=[x.id for x in decs] or list(po["approval_decisions"])))
        return Outcome(True, "closed", decs, {"po": self.po_view(po_id)})

    # ----- bank -----
    def bank_record(self, rec: dict, *, at: str) -> Outcome:
        """rec: {id, kind: charge|refund|fee, amount (dollars), payee, ref, source}. The bank is an outside party and wins on cash."""
        at = self._now(at)
        bid, kind, amt = rec["id"], rec.get("kind", "charge"), cents(rec["amount"])
        subj = f"bank:{bid}"
        self.bank[bid] = {**rec, "amount_cents": amt, "at": at}
        bev = {"type": "bank_record", "id": bid, "detail": f"{kind} {usd(amt)} {rec.get('source', 'sim')}"}
        if kind == "fee":
            e, d, moved = self._post(at=at, date=at[:10], lines=[Line("6100", debit=amt), Line("1000", credit=amt)], reason=f"bank fee {bid}", refs=[f"bank:{bid}"], subject=subj,
                                     kind="bank_reconcile", rule="recon.trust", evidence=[bev], outcome="booked", codes=("bank_fee",))
            return Outcome(True, "booked", [x for x in (moved, d) if x], {})
        pay = next((p for p in self.payments.values() if p["ref"] == rec.get("ref")), None)
        if kind == "refund":
            v = next((x for x in self.vendors.values() if x.payee_id == rec.get("payee")), None)
            if v is None or self.ledger.balance("1300", party=v.id) < amt:
                d = self._d(at, "bank_reconcile", subj, "exception", "a refund arrived that does not match any vendor credit receivable; left for the controller", rule="recon.trust", codes=("unmatched_refund",), evidence=[bev])
                return Outcome(False, "exception", [d], {"code": "unmatched_refund"})
            e, d, moved = self._post(at=at, date=at[:10], lines=[Line("1000", debit=amt), Line("1300", credit=amt, party=v.id)], reason=f"refund {bid} clears vendor credit", refs=[f"bank:{bid}"],
                                     subject=subj, kind="bank_reconcile", rule="recon.trust", evidence=[bev], outcome="reconciled", codes=("refund_matched",))
            return Outcome(True, "reconciled", [x for x in (moved, d) if x], {})
        if pay is None:
            d = self._d(at, "bank_reconcile", subj, "exception", f"{usd(amt)} left the bank to {rec.get('payee')} with no payment in the ledger; held for the controller", rule="recon.trust", codes=("unrecorded_disbursement",), evidence=[bev])
            return Outcome(False, "exception", [d], {"code": "unrecorded_disbursement"})
        evid = [bev, {"type": "payment", "id": pay["id"], "detail": f"ledger {usd(pay['amount'])} payee {pay['payee']}"}]
        if rec.get("payee") != pay["payee"]:
            v = self.vendors[pay["vendor_id"]]
            v.bank_verified = False
            v.add("fraud_hold", at, "hyphenate", f"bank sent {pay['id']} to {rec.get('payee')}, mandate payee was {pay['payee']}")
            d = self._d(at, "bank_reconcile", subj, "exception", f"the bank shows {pay['id']} went to {rec.get('payee')}, but the approved payee is {pay['payee']}; vendor frozen until the controller reviews",
                        rule="recon.trust", codes=("bank_payee_mismatch",), evidence=evid, parents=[pay["decision"]])
            return Outcome(False, "exception", [d], {"code": "bank_payee_mismatch"})
        res = resolve("cash_amount", [{"source": "bank", "value": amt, "ref": bid}, {"source": "ledger", "value": pay["amount"], "ref": pay["id"]}])
        pay["reconciled"] = True
        if res["agreed"]:
            d = self._d(at, "bank_reconcile", subj, "reconciled", f"bank and ledger agree on {usd(amt)} for {pay['id']}", rule="recon.trust", codes=("reconciled",), evidence=evid, parents=[pay["decision"]])
            return Outcome(True, "reconciled", [d], {})
        diff = amt - pay["amount"]
        if diff > 0:
            lines = [Line("1300", debit=diff, party=pay["vendor_id"]), Line("1000", credit=diff)]
            why = f"bank took {usd(diff)} more than we paid; recoverable from {self.vendors[pay['vendor_id']].name}"
        else:
            lines = [Line("1000", debit=-diff), Line("2000", credit=-diff, party=pay["vendor_id"])]
            why = f"bank moved {usd(-diff)} less than we paid; we still owe it"
        pay["bank_corrected"] = True
        e, d, moved = self._post(at=at, date=at[:10], lines=lines, reason=f"{res['reason']} Correcting entry: {why}", refs=[f"bank:{bid}", f"payment:{pay['id']}"], subject=subj, kind="bank_reconcile",
                                 rule="recon.trust", evidence=evid, parents=[pay["decision"]], outcome="corrected", codes=("bank_amount_differs", "trust_cash_amount"))
        return Outcome(True, "corrected", [x for x in (moved, d) if x], {"entry": e.to_dict()})

    # ----- vendor bank details -----
    def change_vendor_bank(self, vendor_id: str, *, new_account: str, by: str, at: str, via: str = "email") -> Outcome:
        at = self._now(at)
        v = self.vendors[vendor_id]
        subj = f"vendor:{vendor_id}"
        denied = self._need(by, "change_vendor_bank", at, "vendor_bank_change", subj)
        if denied:
            return denied
        old = v.bank_account
        v.bank_account, v.bank_verified = new_account, False
        v.add("bank_change", at, by, f"{old} -> {new_account} via {via}")
        d = self._d(at, "vendor_bank_change", subj, "pending_verification",
                    f"{self.people[by].name} changed {v.name}'s bank account ({via}); no payment goes out until a different person verifies it by call-back",
                    rule="sod.bank_change_verified_by_other", actor={"kind": "person", "id": by}, codes=("bank_change",), evidence=[{"type": "vendor", "id": vendor_id, "detail": f"{old} -> {new_account}"}])
        return Outcome(True, "pending_verification", [d], {"vendor": v.to_dict()})

    def verify_vendor_bank(self, vendor_id: str, *, by: str, at: str, method: str = "call-back to the number on file") -> Outcome:
        at = self._now(at)
        v = self.vendors[vendor_id]
        subj = f"vendor:{vendor_id}"
        ch = next((e for e in reversed(v.events) if e.kind == "bank_change"), None)
        if ch is not None and ch.by == by:
            return self._deny(at, "vendor_bank_verify", subj, by, "same_person_verified", "the person who changed the bank account cannot verify it", "sod.bank_change_verified_by_other")
        denied = self._need(by, "verify_bank_change", at, "vendor_bank_verify", subj)
        if denied:
            return denied
        v.bank_verified = True
        v.add("bank_verified", at, by, method)
        d = self._d(at, "vendor_bank_verify", subj, "verified", f"{self.people[by].name} verified {v.name}'s bank account by {method}", rule="sod.bank_change_verified_by_other",
                    actor={"kind": "person", "id": by}, codes=("bank_verified",),
                    evidence=[{"type": "vendor", "id": vendor_id, "detail": f"change by {ch.by if ch else 'n/a'} on {ch.at[:10] if ch else 'n/a'}"}])
        return Outcome(True, "verified", [d], {"vendor": v.to_dict()})

    # ----- manual journal (a person, with a reason; the ledger still refuses anything unbalanced or locked) -----
    def manual_journal(self, *, by: str, at: str, date: str, lines: list, reason: str, refs: list) -> Outcome:
        at = self._now(at)
        subj = f"journal:{by}:{at}"
        denied = self._need(by, "manual_journal", at, "manual_journal", subj)
        if denied:
            return denied
        try:
            did = f"dec_{len(self.audit.decisions) + 1:04d}"
            e = self.ledger.post(date=date, lines=lines, reason=reason, refs=[*refs, f"decision:{did}"], by=by, at=at)
        except LedgerError as ex:
            d = self._d(at, "manual_journal", subj, "denied", f"the ledger refused {self.people[by].name}'s entry: {ex.message}", rule="close.period", codes=(ex.code,),
                        evidence=[{"type": "person", "id": by, "detail": "attempted by"}])
            return Outcome(False, "denied", [d], {"code": ex.code})
        d = self._d(at, "manual_journal", subj, "posted", f"{self.people[by].name} posted {e.id}: {reason}", rule="close.period", actor={"kind": "person", "id": by},
                    evidence=[{"type": "journal_entry", "id": e.id, "detail": e.period}], codes=("manual",))
        return Outcome(True, "posted", [d], {"entry": e.to_dict()})

    # ----- period close -----
    def close_period(self, period: str, *, by: str, at: str) -> Outcome:
        at = self._now(at)
        subj = f"period:{period}"
        denied = self._need(by, "close_period", at, "period_close", subj)
        if denied:
            return denied
        loose = [p["id"] for p in self.payments.values() if p["at"][:7] == period and not p["reconciled"]]
        if loose:
            d = self._d(at, "period_close", subj, "blocked", f"{period} cannot close: {len(loose)} payment(s) have no bank record ({', '.join(loose)})", rule="close.period", codes=("unreconciled_cash",),
                        evidence=[{"type": "payment", "id": i, "detail": "no bank record"} for i in loose])
            return Outcome(False, "blocked", [d], {"code": "unreconciled_cash"})
        try:
            res = self.ledger.close_period(period, by=by, at=at)
        except LedgerError as e:
            d = self._d(at, "period_close", subj, "blocked", f"{period} cannot close: {e.message}", rule="close.period", codes=(e.code,), evidence=[{"type": "period", "id": period, "detail": e.message}])
            return Outcome(False, "blocked", [d], {"code": e.code})
        held = [i["id"] for i in self.invoices.values() if i["status"] == "held" and i["date"][:7] <= period]
        accr = self.ledger.balance("2100", through=period)
        d = self._d(at, "period_close", subj, "closed",
                    f"{self.people[by].name} closed {period}. Trial balance {usd(res['trial_balance']['debit'])} each side; accrued received-not-billed {usd(accr)}; {len(held)} held invoice(s) will post in the next open period when released",
                    rule="close.period", actor={"kind": "person", "id": by}, codes=("closed",),
                    evidence=[{"type": "trial_balance", "id": period, "detail": f"debit {res['trial_balance']['debit']} credit {res['trial_balance']['credit']}"}])
        return Outcome(True, "closed", [d], {"close": res, "held_invoices": held, "accrued": accr})
