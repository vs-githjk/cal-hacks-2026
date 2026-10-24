"""FastAPI app for Hyphenate (Lane D). Run: python3 -m uvicorn hyphenate.api:app --port 8788

All routes live under /v1/hyphenate. State is one in-memory simulated company (Pixel Forge Games, SIM) so Lane B can render
pages: POST /v1/hyphenate/demo/reset loads the seeded story, ?story=empty gives a blank studio. Every write returns
{ok, status, decision_ids, decisions, ...}; a refused action is HTTP 200 with ok=false and a decision that says why (the refusal is
a result, not an error). 404 unknown id, 409 time went backwards, 422 bad input. JSON shapes: hyphenate/README.md.
"""
from __future__ import annotations

import datetime
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from hyphenate import VERSION
from hyphenate.audit import AuditError
from hyphenate.company import Outcome
from hyphenate.demo import run_story
from hyphenate.draft import draft_explanation
from hyphenate.engine import Engine, seed_company
from hyphenate.ledger import CHART, Line
from hyphenate.trust import resolve
from hyphenate.vendors import assess
from shield.api import BodyLimit


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(engine: Optional[Engine] = None) -> FastAPI:
    app = FastAPI(title="Hyphenate: purchasing and AP seats (SIM)", version=VERSION)
    app.add_middleware(BodyLimit)
    app.state.eng = engine or seed_company()
    P = "/v1/hyphenate"

    def eng() -> Engine:
        return app.state.eng

    def at_of(payload: dict) -> str:
        at = payload.get("at") or max(_now(), eng().clock)
        return at

    @app.exception_handler(KeyError)
    async def _nf(_: Request, e: KeyError):
        return JSONResponse({"detail": f"not found: {e.args[0]}"}, status_code=404)

    @app.exception_handler(ValueError)
    async def _bad(_: Request, e: ValueError):
        code = 409 if "time cannot go backwards" in str(e) else 422
        return JSONResponse({"detail": str(e)}, status_code=code)

    @app.exception_handler(AuditError)
    async def _audit(_: Request, e: AuditError):
        return JSONResponse({"detail": str(e)}, status_code=404)

    def out(o: Outcome) -> dict:
        return o.to_dict()

    # ---------- meta ----------
    @app.get(f"{P}/health")
    def health():
        return {"status": "ok", "version": VERSION, "company": eng().name, "origin": "SIM", "clock": eng().clock}

    @app.post(f"{P}/demo/reset")
    def reset(story: str = "moment"):
        if story == "moment":
            app.state.eng = run_story()["engine"]
        elif story == "empty":
            app.state.eng = seed_company()
        else:
            raise ValueError("story must be 'moment' or 'empty'")
        return {"ok": True, "story": story, "decisions": len(eng().audit.decisions), "clock": eng().clock}

    @app.get(f"{P}/company")
    def company():
        c = eng()
        return {"name": c.name, "origin": "SIM", "people": [p.to_dict() for p in c.people.values()], "budgets": c.budgets,
                "budget_used": {d: c.budget_used(d) for d in c.budgets}, "policy": c.policy.__dict__, "clock": c.clock,
                "sod": "requesters never approve; receivers never requested or approved; payers never requested or approved; bank changes are verified by someone else"}

    @app.get(f"{P}/vendors")
    def vendors():
        c = eng()
        return {"vendors": [{**v.to_dict(), "risk": assess(v, max(c.clock, "2026-01-01T00:00:00Z")).__dict__ | {"reasons": list(assess(v, max(c.clock, "2026-01-01T00:00:00Z")).reasons)}} for v in c.vendors.values()]}

    # ---------- purchase orders ----------
    @app.get(f"{P}/pos")
    def pos(status: Optional[str] = None):
        c = eng()
        return {"pos": [c.po_view(i) for i, p in c.pos.items() if status is None or p["status"] == status]}

    @app.get(f"{P}/pos/{{po_id}}")
    def po(po_id: str):
        c = eng()
        v = c.po_view(po_id)
        subj = f"po:{po_id}"
        return {**v, "decisions": [d.to_dict() for d in c.audit.for_subject(subj)], "memos": [m for m in c.memos.values() if m["po_id"] == po_id],
                "invoices_detail": [c.invoices[i] for i in c.pos[po_id]["invoices"]]}

    @app.post(f"{P}/requisitions")
    def requisition(payload: dict[str, Any] = Body(...)):
        return out(eng().request(requester=payload["requester"], vendor_id=payload["vendor_id"], lines=payload["lines"], at=at_of(payload),
                                 justification=payload.get("justification", ""), dept=payload.get("dept")))

    @app.post(f"{P}/pos/{{po_id}}/approve")
    def approve(po_id: str, payload: dict[str, Any] = Body(...)):
        return out(eng().approve(po_id, by=payload["by"], at=at_of(payload), override_budget=bool(payload.get("override_budget", False)), note=payload.get("note", "")))

    @app.post(f"{P}/pos/{{po_id}}/reject")
    def reject(po_id: str, payload: dict[str, Any] = Body(...)):
        return out(eng().reject(po_id, by=payload["by"], at=at_of(payload), reason=payload.get("reason", ""), max_amount=payload.get("max_amount")))

    @app.post(f"{P}/pos/{{po_id}}/receive")
    def receive(po_id: str, payload: dict[str, Any] = Body(...)):
        return out(eng().receive(po_id, by=payload["by"], at=at_of(payload), lines=payload["lines"]))

    @app.post(f"{P}/pos/{{po_id}}/prepay")
    def prepay(po_id: str, payload: dict[str, Any] = Body(default={})):
        return out(eng().prepay(po_id, at=at_of(payload)))

    @app.post(f"{P}/pos/{{po_id}}/close")
    def close_po(po_id: str, payload: dict[str, Any] = Body(default={})):
        return out(eng().close_po(po_id, at=at_of(payload)))

    # ---------- invoices, memos, payments ----------
    @app.get(f"{P}/invoices")
    def invoices(status: Optional[str] = None):
        return {"invoices": [i for i in eng().invoices.values() if status is None or i["status"] == status]}

    @app.get(f"{P}/invoices/{{invoice_id}}")
    def invoice_get(invoice_id: str):
        c = eng()
        i = c.invoices[invoice_id]
        return {**i, "decisions": [d.to_dict() for d in c.audit.for_subject(f"invoice:{invoice_id}")], "memos": [m for m in c.memos.values() if m["invoice_id"] == invoice_id]}

    @app.post(f"{P}/invoices")
    def invoice_post(payload: dict[str, Any] = Body(...)):
        return out(eng().invoice(po_id=payload["po_id"], number=payload["number"], date=payload["date"], lines=payload["lines"], at=at_of(payload), remit_to=payload.get("remit_to"),
                                 total=payload.get("total"), claim=payload.get("claim"), supersedes=payload.get("supersedes"), vendor_id=payload.get("vendor_id")))

    @app.post(f"{P}/invoices/{{invoice_id}}/pay")
    def pay(invoice_id: str, payload: dict[str, Any] = Body(default={})):
        return out(eng().pay(invoice_id, at=at_of(payload), by=payload.get("by", "ap-agent")))

    @app.get(f"{P}/memos")
    def memos():
        return {"memos": list(eng().memos.values())}

    @app.post(f"{P}/memos/{{memo_id}}/issued")
    def memo_issued(memo_id: str, payload: dict[str, Any] = Body(default={})):
        return out(eng().credit_memo_issued(memo_id, at=at_of(payload)))

    @app.post(f"{P}/bank-records")
    def bank(payload: dict[str, Any] = Body(...)):
        return out(eng().bank_record({k: payload.get(k) for k in ("id", "kind", "amount", "payee", "ref", "source") if k in payload}, at=at_of(payload)))

    @app.post(f"{P}/vendors/{{vendor_id}}/bank-change")
    def bank_change(vendor_id: str, payload: dict[str, Any] = Body(...)):
        return out(eng().change_vendor_bank(vendor_id, new_account=payload["new_account"], by=payload["by"], at=at_of(payload), via=payload.get("via", "email")))

    @app.post(f"{P}/vendors/{{vendor_id}}/bank-verify")
    def bank_verify(vendor_id: str, payload: dict[str, Any] = Body(...)):
        return out(eng().verify_vendor_bank(vendor_id, by=payload["by"], at=at_of(payload), method=payload.get("method", "call-back to the number on file")))

    # ---------- ledger ----------
    @app.get(f"{P}/ledger/accounts")
    def accounts():
        return {"accounts": [{"id": k, "name": v[0], "type": v[1], "balance": eng().ledger.balance(k)} for k, v in sorted(CHART.items())]}

    @app.get(f"{P}/ledger/journal")
    def journal(ref: Optional[str] = None, period: Optional[str] = None):
        led = eng().ledger
        es = led.entries_for_ref(ref) if ref else led.entries
        return {"entries": [e.to_dict() for e in es if period is None or e.period == period], "closed_periods": led.locked}

    @app.get(f"{P}/ledger/trial-balance")
    def trial(through: Optional[str] = None):
        led = eng().ledger
        return {**led.trial_balance(through), "subledger_problems": led.subledger_ties(), "ap_by_vendor": led.party_balances("2000"), "accrued_by_vendor": led.party_balances("2100")}

    @app.post(f"{P}/journal")
    def manual(payload: dict[str, Any] = Body(...)):
        lines = [Line(l["account"], int(l.get("debit", 0)), int(l.get("credit", 0)), l.get("party")) for l in payload["lines"]]
        return out(eng().manual_journal(by=payload["by"], at=at_of(payload), date=payload["date"], lines=lines, reason=payload.get("reason", ""), refs=payload.get("refs", [])))

    @app.post(f"{P}/periods/{{period}}/close")
    def close(period: str, payload: dict[str, Any] = Body(...)):
        return out(eng().close_period(period, by=payload["by"], at=at_of(payload)))

    # ---------- audit ----------
    @app.get(f"{P}/audit")
    def audit(subject: Optional[str] = None, kind: Optional[str] = None, outcome: Optional[str] = None, limit: int = 200):
        ds = [d for d in eng().audit.decisions if (subject is None or d.subject == subject) and (kind is None or d.kind == kind) and (outcome is None or d.outcome == outcome)]
        return {"decisions": [d.to_dict() for d in ds[-max(1, min(limit, 1000)):]], "total": len(ds)}

    @app.get(f"{P}/audit/verify")
    def audit_verify():
        return {"broken": eng().audit.verify_chain(), "invariants": eng().invariants(), "decisions": len(eng().audit.decisions)}

    @app.get(f"{P}/audit/{{decision_id}}")
    def audit_get(decision_id: str):
        d = eng().audit.get(decision_id)
        if d is None:
            raise KeyError(decision_id)
        return d.to_dict()

    @app.get(f"{P}/audit/{{decision_id}}/explain")
    def explain(decision_id: str, draft: bool = False):
        x = eng().explain(decision_id)
        if draft:
            x["draft"] = draft_explanation(x)
        return x

    # ---------- reconciliation and proof ----------
    @app.get(f"{P}/reconciliation")
    def reconciliation():
        """Per payment: what each source says and which one the trust ranking believes, with the reason."""
        c, rows = eng(), []
        for p in c.payments.values():
            bank = next((b for b in c.bank.values() if b.get("ref") == p["ref"]), None)
            obs = [{"source": "ledger", "value": p["amount"], "ref": p["id"]}]
            if bank:
                obs.append({"source": "bank", "value": bank["amount_cents"], "ref": bank["id"]})
            inv = c.invoices.get(p["invoice_id"]) if p["invoice_id"] else None
            if inv:
                obs.append({"source": "seller_claim", "value": inv["total"], "ref": inv["id"]})
            res = resolve("cash_amount", obs)
            po = c.pos[p["po_id"]]
            refs = [{"sku": l["sku"], "po_unit": l["unit"], "mirror": (c.mirror.get(l["sku"]) or {}).get("price"), "mirror_as_of": (c.mirror.get(l["sku"]) or {}).get("as_of")} for l in po["lines"]]
            rows.append({"payment": p["id"], "invoice": p["invoice_id"], "po": p["po_id"], "ledger": p["amount"], "bank": bank["amount_cents"] if bank else None, "seller_claim": inv["total"] if inv else None,
                         "mirror": refs, "agreed": res["agreed"], "believed": res["trusted"]["source"] if res["trusted"] else None, "reason": res["reason"], "origin": "SIM"})
        return {"rows": rows}

    @app.get(f"{P}/results")
    def results(heldout: bool = True):
        from hyphenate.scenarios.runner import run_set, summarize
        dev = run_set("dev_cases", "dev")
        body: dict = {"label": "SIM", "dev": summarize(dev), "cases": [{k: r.get(k) for k in ("id", "title", "fault", "planted", "split", "verdict", "missing", "forbidden")} for r in dev]}
        if heldout:
            ho = run_set("heldout_cases", "held_out")
            body["held_out"] = summarize(ho)
            body["cases"] += [{k: r.get(k) for k in ("id", "title", "fault", "planted", "split", "verdict", "missing", "forbidden")} for r in ho]
        return body

    return app


app = create_app()
