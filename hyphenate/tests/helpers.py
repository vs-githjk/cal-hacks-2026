from hyphenate.engine import seed_company

T = lambda d, h=9: f"2026-{d}T{h:02d}:00:00Z"  # T("10-05") -> 2026-10-05T09:00:00Z


def gpu(qty=2, price=1249.99, **kw):
    return {"sku": "RTX-5070-TI", "desc": "RTX 5070 Ti 16GB", "qty": qty, "price": price, "condition": "new", "allowed": ["new"], **kw}


def serials(n, tag="A"):
    return [f"SN{tag}{i:03d}" for i in range(n)]


def approved_po(eng=None, vendor="bestbuy", lines=None, at="10-05"):
    eng = eng or seed_company(mirror={})
    out = eng.request(requester="vidyut", vendor_id=vendor, lines=lines or [gpu()], at=T(at, 9), justification="render farm")
    pid = out.data["po"]["id"]
    r = eng.approve(pid, by="rhodey", at=T(at, 10))
    assert r.ok, r.to_dict()
    return eng, pid


def received(eng, pid, qty=2, at="10-08", tag="A", **kw):
    r = eng.receive(pid, by="happy", at=T(at), lines=[{"sku": "RTX-5070-TI", "qty": qty, "condition": "new", "serials": serials(qty, tag), **kw}])
    assert r.ok, r.to_dict()
    return r


def codes(out):
    return {c for d in out.decisions for c in d.codes}
