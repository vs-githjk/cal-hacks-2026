import json
import re

from data.liar_pages.build import build, page


def listing(html_text):
    return json.loads(re.search(r'<script type="application/json" id="listing">(.*?)</script>', html_text, re.S).group(1))


def test_honest_hal_has_no_planted_lies():
    d = listing(page("honest-hal", "gpu-5070ti", lies=False))
    assert d["planted_lies"] == [] and d["condition"] == "new" and d["was_price"] is None


def test_lie_toggle_plants_fake_was_price_and_open_box_as_new():
    h = page("shady-sam", "gpu-5070ti", lies=True)
    d = listing(h)
    assert d["was_price"] == 1099.0 and d["condition"] == "open-box"
    assert "BRAND NEW" in h and "Open box" in h


def test_wrong_socket_lie():
    assert listing(page("shady-sam", "cpu-5800x3d", lies=True))["specs"]["Socket"] == "AM5"


def test_injected_page_has_hidden_instruction_and_payee_swap():
    h = page("shady-sam", "gpu-5070ti", lies=True, injected=True)
    d = listing(h)
    assert "ignore your previous instructions" in h and d["payee"] != "shady-sam@pay.example.test"
    assert {"injection", "payee_swap"} <= set(d["planted_lies"])


def test_every_page_carries_the_demo_banner():
    for name in build():
        if name.endswith(".html"):
            text = (build.__globals__["SITE"] / name).read_text()
            assert "SIM: simulated listing for a security demo" in text, name
            assert ("Prompt-injection test page" in text) == ("injected" in name), name


def test_renew_refurb_page_says_refurbished_and_claim_new_is_false():  # #97
    from data.claim_check import check_claim
    from data.liar_pages.build import SITE
    names = build()
    assert {"renew-refurb-gpu-5070ti.html", "renew-refurb-gpu-5070ti-lies.html"} <= set(names)
    h = (SITE / "renew-refurb-gpu-5070ti-lies.html").read_text()
    assert listing(h)["condition"] == "refurbished" and "condition" in listing(h)["planted_lies"] and "BRAND NEW" in h
    fetch = lambda url: (SITE / url.rsplit("/", 1)[1]).read_bytes()
    out = check_claim({"text": "Brand new, sealed", "kind": "spec", "evidence_url": "http://localhost:8765/renew-refurb-gpu-5070ti-lies.html"},
                      fetch=fetch)
    assert out["result"] == "false" and "refurbished" in out["reason"]
    honest = check_claim({"text": "Refurbished", "kind": "spec", "evidence_url": "http://localhost:8765/renew-refurb-gpu-5070ti.html"},
                         fetch=fetch)
    assert honest["result"] == "verified"


def test_existing_pages_unchanged_by_new_sellers():
    from data.liar_pages.build import SITE
    import subprocess
    build()
    diff = subprocess.run(["git", "diff", "--name-only", "--", str(SITE)], capture_output=True, text=True).stdout.split()
    assert not [d for d in diff if not d.endswith(("sellers.json", "index.html"))], diff
