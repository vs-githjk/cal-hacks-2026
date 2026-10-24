"""DEV scenarios: used while building and tuned against. SIM company (Pixel Forge Games), planted errors with an answer key.
Dates are 2026 (MM-DD or MM-DD HH). `{po1}` style placeholders in facts are replaced by the real ids."""


def SSD(q, p=100.0, **kw):
    return {"sku": "SSD-2TB", "qty": q, "price": p, **kw}


def GPU(q, p=1249.99, **kw):
    return {"sku": "RTX-5070-TI", "qty": q, "price": p, **kw}


def ready(po, lines, vendor="bestbuy", day="10-05", by="rhodey", dept=None):
    s = {"do": "request", "as": po, "requester": "vidyut", "vendor": vendor, "lines": lines, "at": day, "why": "team gear"}
    if dept:
        s["dept"] = dept
    return [s, {"do": "approve", "po": po, "by": by, "at": f"{day} 10"}]


def rcv(po, lines, at="10-08", by="happy"):
    return {"do": "receive", "po": po, "by": by, "at": at, "lines": lines}


def inv(po, number, lines, date="10-09", as_="i1", at=None, **kw):
    return {"do": "invoice", "po": po, "number": number, "date": date, "at": at or date, "lines": lines, "as": as_, **kw}


def L(sku, qty, price, **kw):
    return {"sku": sku, "qty": qty, "price": price, **kw}


def planted(id, title, fault, steps, expect=(), expect_facts=(), forbid=(), setup=None):
    return {"id": id, "title": title, "fault": fault, "planted": True, "setup": setup or {}, "steps": steps,
            "key": {"expect": [dict(zip(("kind", "outcome", "code"), e)) for e in expect], "expect_facts": list(expect_facts), "forbid_facts": list(forbid)}}


def clean(id, title, steps, expect_facts=(), setup=None):
    return {"id": id, "title": title, "fault": "clean_control", "planted": False, "setup": setup or {}, "steps": steps,
            "key": {"expect": [], "expect_facts": list(expect_facts), "forbid_facts": []}}


SSD10 = [SSD(10)]
SSD2 = [SSD(2)]
CASES = [
    planted("D01", "Vendor bills 10 SSDs, 8 arrive", "short_shipment",
            [*ready("po1", SSD10), rcv("po1", [{"sku": "SSD-2TB", "qty": 8}]), inv("po1", "SS-1", [L("SSD-2TB", 10, 100.0)])],
            [("invoice_match", "hold", "qty_short"), ("credit_memo_request", "requested", "qty_short")],
            ["invoice_status:{i1}:held", "memo_requested:{i1}"], ["paid:{i1}", "invoice_status:{i1}:matched"]),
    planted("D02", "Open-box units arrive, invoice says new (PO allowed open-box)", "wrong_condition",
            [*ready("po1", [SSD(2, allowed=["new", "open-box"])]), rcv("po1", [{"sku": "SSD-2TB", "qty": 2, "condition": "open-box"}]), inv("po1", "WC-1", [L("SSD-2TB", 2, 100.0)])],
            [("invoice_match", "hold", "condition_mismatch"), ("source_trust", "resolved", "trust_goods_condition")],
            ["invoice_status:{i1}:held", "memo_requested:{i1}"], ["paid:{i1}"]),
    planted("D03", "Open-box units arrive, PO allows new only", "wrong_condition_rejected",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2, "condition": "open-box"}]), inv("po1", "WR-1", [L("SSD-2TB", 2, 100.0)])],
            [("receiving", "failed", "condition_not_allowed"), ("vendor_history", "noted", "failed_receiving"), ("invoice_match", "hold", "rejected_goods_billed")],
            ["invoice_status:{i1}:held"], ["paid:{i1}", "invoice_status:{i1}:matched"]),
    planted("D04", "Invoice price 8 percent above the PO", "price_drift",
            [*ready("po1", SSD10), rcv("po1", [{"sku": "SSD-2TB", "qty": 10}]), inv("po1", "PD-1", [L("SSD-2TB", 10, 108.0)])],
            [("invoice_match", "hold", "price_variance"), ("source_trust", "resolved", "trust_agreed_price")],
            ["invoice_status:{i1}:held"], ["paid:{i1}", "invoice_status:{i1}:matched"]),
    planted("D05", "Same invoice sent twice with different punctuation", "duplicate_invoice",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "INV-42", [L("SSD-2TB", 2, 100.0)]),
             inv("po1", "INV 0042", [L("SSD-2TB", 2, 100.0)], date="10-12", as_="i2")],
            [("invoice_match", "denied", "duplicate_invoice")], ["invoice_status:{i1}:matched", "invoice_status:{i2}:rejected_duplicate"], ["paid:{i2}"]),
    planted("D06", "Vendor bank details changed the day before payment", "changed_bank_details",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "BC-1", [L("SSD-2TB", 2, 100.0)]),
             {"do": "vendor_bank_change", "vendor": "bestbuy", "by": "maria", "at": "10-09 15"}, {"do": "pay", "invoice": "i1", "at": "10-10"}],
            [("payment_release", "denied", "bank_unverified")], ["vendor_bank_verified:bestbuy:false"], ["paid:{i1}"]),
    planted("D07", "Invoice remit-to account differs from the vendor master", "remit_to_changed",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "RT-1", [L("SSD-2TB", 2, 100.0)], remit_to="acct_attacker_999")],
            [("invoice_match", "hold", "remit_to_mismatch"), ("source_trust", "resolved", "trust_remit_account")], ["invoice_status:{i1}:held"], ["paid:{i1}"]),
    planted("D08", "Requester tries to approve their own PO", "requester_self_approval",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "bestbuy", "lines": SSD2, "at": "10-05"}, {"do": "approve", "po": "po1", "by": "vidyut", "at": "10-05 10"}],
            [("po_approval", "denied", "self_approval")], ["po_status:{po1}:pending_approval"], ["po_approved_by:{po1}:vidyut", "po_status:{po1}:approved"]),
    planted("D09", "Requester's delegate approves on their behalf", "delegate_approval",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "bestbuy", "lines": SSD2, "at": "10-05"}, {"do": "approve", "po": "po1", "by": "vidyut-assistant", "at": "10-05 10"}],
            [("po_approval", "denied", "delegate_of_requester")], ["po_status:{po1}:pending_approval"], ["po_status:{po1}:approved"]),
    planted("D10", "Department head approves over the department budget", "over_budget",
            [{"do": "request", "as": "po1", "requester": "jess", "dept": "art", "vendor": "bestbuy", "lines": [SSD(1, 1500.0)], "at": "10-05"}, {"do": "approve", "po": "po1", "by": "kara", "at": "10-05 10"}],
            [("po_approval", "denied", "over_budget")], ["po_status:{po1}:pending_approval"], ["po_status:{po1}:approved"], setup={"budgets": {"art": 100000}}),
    planted("D11", "Department head approves above the $2,500 limit", "above_authority",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "bestbuy", "lines": [GPU(3)], "at": "10-05"}, {"do": "approve", "po": "po1", "by": "rhodey", "at": "10-05 10"}],
            [("po_approval", "denied", "above_authority")], ["po_status:{po1}:pending_approval"], ["po_status:{po1}:approved"]),
    planted("D12", "Controller says no; a cheaper allowed line exists", "controller_no_replan",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "bestbuy", "lines": [SSD(2, 1000.0, allowed=["new", "open-box"], alt=[{"condition": "open-box", "price": 800.0}])], "at": "10-05"},
             {"do": "reject", "po": "po1", "by": "pepper", "at": "10-05 10", "reason": "over this quarter's plan", "max": 1700}],
            [("po_reject", "rejected", "controller_no"), ("replan", "replanned", None)], ["po_status:{po1}:replanned"], ["po_status:{po1}:approved"]),
    planted("D13", "Controller says no; nothing cheaper is allowed", "controller_no_drop",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "bestbuy", "lines": [SSD(2, 1000.0)], "at": "10-05"},
             {"do": "reject", "po": "po1", "by": "pepper", "at": "10-05 10", "reason": "not this quarter"}],
            [("po_reject", "rejected", "controller_no"), ("replan", "dropped", "dropped")], ["po_status:{po1}:dropped"], ["po_status:{po1}:approved"]),
    planted("D14", "Invoice arrives before anything was received", "billed_before_receipt",
            [*ready("po1", SSD2), inv("po1", "BR-1", [L("SSD-2TB", 2, 100.0)])],
            [("invoice_match", "hold", "billed_before_receipt")], ["invoice_status:{i1}:held"], ["paid:{i1}", "invoice_status:{i1}:matched"]),
    planted("D15", "Wrong SKU arrives (4 TB for the 2 TB ordered)", "wrong_sku_received",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-4TB", "qty": 2}]), inv("po1", "WS-1", [L("SSD-2TB", 2, 100.0)])],
            [("receiving", "failed", "unexpected_sku"), ("invoice_match", "hold", "billed_before_receipt")], ["invoice_status:{i1}:held"], ["paid:{i1}"]),
    planted("D16", "Same serial numbers arrive on a second receipt", "duplicate_serial",
            [*ready("po1", [SSD(4)]), rcv("po1", [{"sku": "SSD-2TB", "qty": 2, "tag": "T1"}]), rcv("po1", [{"sku": "SSD-2TB", "qty": 2, "tag": "T1"}], at="10-09")],
            [("receiving", "failed", "duplicate_serial")], ["po_status:{po1}:partially_received"]),
    planted("D17", "Serialized units arrive without serial numbers", "serial_missing",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2, "serials": ["only-one"]}])],
            [("receiving", "failed", "serial_missing")], ["po_status:{po1}:approved"]),
    planted("D18", "Invoice total does not equal its lines", "arithmetic",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "AR-1", [L("SSD-2TB", 2, 100.0)], total=250.0)],
            [("invoice_match", "hold", "arithmetic")], ["invoice_status:{i1}:held"], ["paid:{i1}", "invoice_status:{i1}:matched"]),
    planted("D19", "Vendor failed a check a month ago: a 40 cent variance is no longer waved through", "vendor_history_strict",
            [ready("po1", SSD10)[0], {"do": "approve", "po": "po1", "by": "rhodey", "at": "10-05 10"}, {"do": "approve", "po": "po1", "by": "pepper", "at": "10-05 11"},
             rcv("po1", [{"sku": "SSD-2TB", "qty": 10}]), inv("po1", "SV-1", [L("SSD-2TB", 10, 100.4)])],
            [("approval_route", "routed", "strict_vendor"), ("invoice_match", "hold", "price_variance")], ["po_status:{po1}:received", "invoice_status:{i1}:held"], ["paid:{i1}", "invoice_status:{i1}:matched"],
            setup={"vendors": {"bestbuy": {"events": [{"kind": "failed_receiving", "at": "2026-09-20T00:00:00Z", "by": "happy", "detail": "open-box sent as new"}]}}}),
    planted("D20", "First order with an unproven vendor above $1,000", "new_vendor_large_po",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "newco", "lines": [SSD(1, 1500.0)], "at": "10-05"}, {"do": "approve", "po": "po1", "by": "rhodey", "at": "10-05 10"}],
            [("approval_route", "routed", "new_vendor"), ("po_approval", "denied", "controller_required")], ["po_status:{po1}:pending_approval"], ["po_status:{po1}:approved"],
            setup={"vendors": {"newco": {}}}),
    planted("D21", "Charge attempted with an edited mandate amount", "mandate_amount_tamper",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "MT-1", [L("SSD-2TB", 2, 100.0)]),
             {"do": "pay", "invoice": "i1", "at": "10-10", "tamper": {"set": {"amount": 2999.0}}}],
            [("payment_release", "blocked", "mandate_hash_mismatch")], ["invoice_status:{i1}:matched"], ["paid:{i1}"]),
    planted("D22", "Charge attempted to a different payee with a re-signed mandate", "mandate_payee_swap",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "MP-1", [L("SSD-2TB", 2, 100.0)]),
             {"do": "pay", "invoice": "i1", "at": "10-10", "tamper": {"set": {"payee": "evil@pay.example.test"}, "rehash": True}}],
            [("payment_release", "blocked", "mandate_payee_mismatch")], ["invoice_status:{i1}:matched"], ["paid:{i1}"]),
    planted("D23", "Bank record shows $50 more than the ledger", "bank_ledger_disagree",
            [*ready("po1", [GPU(2)]), rcv("po1", [{"sku": "RTX-5070-TI", "qty": 2}]), inv("po1", "BL-1", [L("RTX-5070-TI", 2, 1249.99)]),
             {"do": "pay", "invoice": "i1", "at": "10-10", "as": "p1"}, {"do": "bank", "id": "ba1", "at": "10-11", "pay": "p1", "vendor": "bestbuy", "amount": 2549.98, "source": "stripe_test"}],
            [("bank_reconcile", "corrected", "trust_cash_amount")], ["paid:{i1}", "payment_corrected:{p1}", "vendor_credit:bestbuy:5000"]),
    planted("D24", "Invoice against a PO nobody approved", "unapproved_po",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "bestbuy", "lines": SSD2, "at": "10-05"}, inv("po1", "UP-1", [L("SSD-2TB", 2, 100.0)], date="10-09"),
             {"do": "pay", "invoice": "i1", "at": "10-10"}],
            [("invoice_match", "hold", "po_not_approved"), ("payment_release", "denied", "invoice_not_matched")], ["invoice_status:{i1}:held"], ["paid:{i1}"]),
    planted("D25", "Bill dated into a month that is already closed", "period_locked_posting",
            [*ready("po1", SSD2, day="03-25"), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}], at="03-31"), {"do": "close_period", "period": "2026-03", "by": "pepper", "at": "04-01"},
             inv("po1", "PL-1", [L("SSD-2TB", 2, 100.0)], date="03-30", at="04-03")],
            [("posting_period", "rerouted", "period_locked")], ["period_closed:2026-03", "invoice_status:{i1}:matched"]),
    planted("D26", "Second invoice bills past the PO quantity", "over_billing",
            [*ready("po1", SSD10), rcv("po1", [{"sku": "SSD-2TB", "qty": 10}]), inv("po1", "OB-1", [L("SSD-2TB", 8, 100.0)]), inv("po1", "OB-2", [L("SSD-2TB", 4, 100.0)], date="10-10", as_="i2")],
            [("invoice_match", "hold", "qty_over_po")], ["invoice_status:{i1}:matched", "invoice_status:{i2}:held"], ["paid:{i2}", "invoice_status:{i2}:matched"]),
    planted("D27", "PO price 36 percent above a fresh MIRROR market price", "price_above_market",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "gadget-grove", "lines": [GPU(1, 1700.0)], "at": "10-24"}, {"do": "approve", "po": "po1", "by": "rhodey", "at": "10-24 10"}],
            [("approval_route", "routed", "above_market"), ("po_approval", "denied", "controller_required")], ["po_status:{po1}:pending_approval"], ["po_status:{po1}:approved"],
            setup={"mirror": {"RTX-5070-TI": {"price": 124999, "as_of": "2026-10-20T00:00:00Z", "source": "https://example.test/bb", "origin": "MIRROR"}}}),
    planted("D28", "A manual journal that does not balance", "unbalanced_entry",
            [{"do": "journal", "by": "pepper", "at": "10-05", "date": "10-05", "lines": [{"account": "1500", "debit": 10000}, {"account": "1000", "credit": 9000}]}],
            [("manual_journal", "denied", "unbalanced")]),
    planted("D29", "The AP agent tries to post a manual journal", "agent_overreach",
            [{"do": "journal", "by": "ap-agent", "at": "10-05", "date": "10-05", "lines": [{"account": "1500", "debit": 10000}, {"account": "1000", "credit": 10000}]}],
            [("manual_journal", "denied", "no_permission")]),
    planted("D30", "The person who changed the vendor bank account verifies it themselves", "same_person_verifies",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "SP-1", [L("SSD-2TB", 2, 100.0)]),
             {"do": "vendor_bank_change", "vendor": "bestbuy", "by": "maria", "at": "10-09 15"}, {"do": "vendor_bank_verify", "vendor": "bestbuy", "by": "maria", "at": "10-10 9"},
             {"do": "pay", "invoice": "i1", "at": "10-10 10"}],
            [("vendor_bank_verify", "denied", "same_person_verified"), ("payment_release", "denied", "bank_unverified")], ["vendor_bank_verified:bestbuy:false"], ["paid:{i1}"]),
    planted("D31", "The controller who approved the PO tries to release its payment", "payer_not_independent",
            [*ready("po1", [GPU(3)], by="pepper"), rcv("po1", [{"sku": "RTX-5070-TI", "qty": 3}]), inv("po1", "PI-1", [L("RTX-5070-TI", 3, 1249.99)]), {"do": "pay", "invoice": "i1", "at": "10-10", "by": "pepper"}],
            [("payment_release", "denied", "payer_not_independent")], ["invoice_status:{i1}:matched"], ["paid:{i1}"]),
    planted("D32", "Close the month with a payment that has no bank record", "unreconciled_close",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "UC-1", [L("SSD-2TB", 2, 100.0)]), {"do": "pay", "invoice": "i1", "at": "10-10"},
             {"do": "close_period", "period": "2026-10", "by": "pepper", "at": "10-31"}],
            [("period_close", "blocked", "unreconciled_cash")], ["paid:{i1}"], ["period_closed:2026-10"]),
    planted("D33", "Seller claims new; an independent page check says it is not", "claim_false",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "CF-1", [L("SSD-2TB", 2, 100.0)], claim={"result": "false", "reason": "listing page shows open-box"})],
            [("invoice_match", "hold", "claim_false")], ["invoice_status:{i1}:held"], ["paid:{i1}"]),
    planted("D34", "The bank sent the money to someone other than the approved payee", "bank_wrong_payee",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "BP-1", [L("SSD-2TB", 2, 100.0)]), {"do": "pay", "invoice": "i1", "at": "10-10", "as": "p1"},
             {"do": "bank", "id": "ba2", "at": "10-11", "pay": "p1", "payee": "other@x.test", "amount": 200.0}],
            [("bank_reconcile", "exception", "bank_payee_mismatch")], ["vendor_bank_verified:bestbuy:false"]),
    planted("D35", "Prepaid order: 3 of 4 units arrive and the vendor will not ship the last", "prepaid_short_delivery",
            [*ready("po1", [SSD(4)], vendor="bargain-bin"), {"do": "prepay", "po": "po1", "at": "10-06"}, rcv("po1", [{"sku": "SSD-2TB", "qty": 3}]), {"do": "close_po", "po": "po1", "at": "10-20"}],
            [("vendor_credit", "posted", "refund_due"), ("po_close", "closed", "closed_short")], ["vendor_credit:bargain-bin:10000", "memo_requested:{po1}"]),
    planted("D36", "The approver of a PO also receives the goods", "receiver_not_independent",
            [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}], by="rhodey")],
            [("receiving", "denied", "receiver_not_independent")], ["po_status:{po1}:approved"]),
    # found by the PR #40 review after the first freeze; added to dev with the fix
    planted("D37", "Invoice splits one SKU over two qty-1 lines to slip past a 1-unit receipt", "split_invoice_lines",
            [*ready("po1", [GPU(2)]), rcv("po1", [{"sku": "RTX-5070-TI", "qty": 1}]), inv("po1", "SL-1", [L("RTX-5070-TI", 1, 1249.99), L("RTX-5070-TI", 1, 1249.99)])],
            [("invoice_match", "hold", "qty_short")], ["invoice_status:{i1}:held"], ["paid:{i1}", "invoice_status:{i1}:matched"]),
    planted("D38", "Requester charges another department's budget to get its approver", "cross_department_charge",
            [{"do": "request", "as": "po1", "requester": "vidyut", "dept": "art", "vendor": "bestbuy", "lines": [SSD(1, 500.0)], "at": "10-05"}],
            [("po_request", "denied", "wrong_department")]),
    planted("D39", "Strict vendor and the requester is a department head: still two signatures", "strict_vendor_peer_signature",
            [{"do": "request", "as": "po1", "requester": "rhodey", "vendor": "bestbuy", "lines": SSD10, "at": "10-05"}, {"do": "approve", "po": "po1", "by": "pepper", "at": "10-05 10"}],
            [("approval_route", "routed", "strict_vendor"), ("po_approval", "partially_approved", "strict_vendor")], ["po_status:{po1}:pending_approval"], ["po_status:{po1}:approved"],
            setup={"vendors": {"bestbuy": {"events": [{"kind": "failed_receiving", "at": "2026-09-20T00:00:00Z", "by": "happy", "detail": "late"}]}}}),
    # found by the blind run (Lane C, #45); added to dev with the fixes, so those blind cases are no longer blind
    planted("D40", "Look-alike invoice under a new number with the goods already covering it and no new receipt", "duplicate_invoice_lookalike",
            [*ready("po1", [SSD(4)]), rcv("po1", [{"sku": "SSD-2TB", "qty": 4}]), inv("po1", "LK-1", [L("SSD-2TB", 2, 100.0)]), inv("po1", "LK-2", [L("SSD-2TB", 2, 100.0)], date="10-10", as_="i2")],
            [("invoice_match", "hold", "possible_duplicate")], ["invoice_status:{i1}:matched", "invoice_status:{i2}:held"], ["paid:{i2}"]),
    planted("D41", "PO priced 23 percent above the MIRROR median, SKU typed in lower case with spaces", "price_above_market_sku_spelling",
            [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "gadget-grove", "lines": [{"sku": "rtx 5070 ti", "qty": 1, "price": 1600.0}], "at": "10-24"}, {"do": "approve", "po": "po1", "by": "rhodey", "at": "10-24 10"}],
            [("approval_route", "routed", "above_market"), ("po_approval", "denied", "controller_required")], ["po_status:{po1}:pending_approval"], ["po_status:{po1}:approved"],
            setup={"mirror": {"RTX-5070-TI": {"price": 129999, "as_of": "2026-10-20T00:00:00Z", "source": "median of 14 retail listings", "origin": "MIRROR"}}}),
    # clean controls: the system must stay out of the way
    clean("C01", "Clean order from request to closed month",
          [*ready("po1", [GPU(2)]), rcv("po1", [{"sku": "RTX-5070-TI", "qty": 2}]), inv("po1", "CL-1", [L("RTX-5070-TI", 2, 1249.99)]), {"do": "pay", "invoice": "i1", "at": "10-10", "as": "p1"},
           {"do": "bank", "id": "ba1", "at": "10-11", "pay": "p1", "vendor": "bestbuy", "amount": 2499.98}, {"do": "close_period", "period": "2026-10", "by": "pepper", "at": "10-31"}],
          ["paid:{i1}", "period_closed:2026-10", "po_status:{po1}:closed"]),
    clean("C02", "Honest partial delivery, billed as it arrives",
          [*ready("po1", SSD10), rcv("po1", [{"sku": "SSD-2TB", "qty": 6}]), inv("po1", "PA-1", [L("SSD-2TB", 6, 100.0)]), rcv("po1", [{"sku": "SSD-2TB", "qty": 4}], at="10-10"),
           inv("po1", "PA-2", [L("SSD-2TB", 4, 100.0)], date="10-11", as_="i2"), {"do": "pay", "invoice": "i1", "at": "10-12"}, {"do": "pay", "invoice": "i2", "at": "10-12 11"}],
          ["paid:{i1}", "paid:{i2}", "po_status:{po1}:closed"]),
    clean("C03", "Immaterial price variance (40 cents on $1,000) is booked to variance and paid",
          [*ready("po1", SSD10), rcv("po1", [{"sku": "SSD-2TB", "qty": 10}]), inv("po1", "IV-1", [L("SSD-2TB", 10, 100.04)]), {"do": "pay", "invoice": "i1", "at": "10-10"}], ["paid:{i1}"]),
    clean("C04", "Vendor bank change verified by a second person before payment",
          [*ready("po1", SSD2), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}]), inv("po1", "BV-1", [L("SSD-2TB", 2, 100.0)]),
           {"do": "vendor_bank_change", "vendor": "bestbuy", "by": "maria", "at": "10-09 15"}, {"do": "vendor_bank_verify", "vendor": "bestbuy", "by": "pepper", "at": "10-10 9"},
           {"do": "pay", "invoice": "i1", "at": "10-10 10"}], ["paid:{i1}", "vendor_bank_verified:bestbuy:true"]),
    clean("C05", "Month-end accrual reverses when the bill lands in the next month",
          [*ready("po1", SSD2, day="09-25"), rcv("po1", [{"sku": "SSD-2TB", "qty": 2}], at="09-29"), {"do": "close_period", "period": "2026-09", "by": "pepper", "at": "09-30"},
           inv("po1", "AC-1", [L("SSD-2TB", 2, 100.0)], date="10-02"), {"do": "pay", "invoice": "i1", "at": "10-03"}], ["paid:{i1}", "period_closed:2026-09"]),
    clean("C06", "Prepaid vendor delivers in full",
          [*ready("po1", [SSD(4)], vendor="bargain-bin"), {"do": "prepay", "po": "po1", "at": "10-06"}, rcv("po1", [{"sku": "SSD-2TB", "qty": 4}]), inv("po1", "PP-1", [L("SSD-2TB", 4, 100.0)])],
          ["invoice_status:{i1}:matched_prepaid", "prepaid:{po1}"]),
    clean("C07", "Strict vendor, exact price, two signatures",
          [{"do": "request", "as": "po1", "requester": "vidyut", "vendor": "bestbuy", "lines": SSD10, "at": "10-05"}, {"do": "approve", "po": "po1", "by": "rhodey", "at": "10-05 10"},
           {"do": "approve", "po": "po1", "by": "pepper", "at": "10-05 11"}, rcv("po1", [{"sku": "SSD-2TB", "qty": 10}]), inv("po1", "SE-1", [L("SSD-2TB", 10, 100.0)]), {"do": "pay", "invoice": "i1", "at": "10-10"}],
          ["paid:{i1}"], setup={"vendors": {"bestbuy": {"events": [{"kind": "failed_receiving", "at": "2026-09-20T00:00:00Z", "by": "happy", "detail": "late"}]}}}),
    clean("C09", "Two partial deliveries, each billed after its receipt, both bills identical",
          [*ready("po1", [GPU(2)]), rcv("po1", [{"sku": "RTX-5070-TI", "qty": 1}]), inv("po1", "TP-1", [L("RTX-5070-TI", 1, 1249.99)]), rcv("po1", [{"sku": "RTX-5070-TI", "qty": 1}], at="10-10"),
           inv("po1", "TP-2", [L("RTX-5070-TI", 1, 1249.99)], date="10-11", as_="i2"), {"do": "pay", "invoice": "i1", "at": "10-12"}, {"do": "pay", "invoice": "i2", "at": "10-12 11"}],
          ["paid:{i1}", "paid:{i2}", "po_status:{po1}:closed"]),
    clean("C08", "New vendor, small first order",
          [*ready("po1", [SSD(1, 800.0)], vendor="newco"), rcv("po1", [{"sku": "SSD-2TB", "qty": 1}]), inv("po1", "NV-1", [L("SSD-2TB", 1, 800.0)]), {"do": "pay", "invoice": "i1", "at": "10-10"}],
          ["paid:{i1}"], setup={"vendors": {"newco": {}}}),
]
