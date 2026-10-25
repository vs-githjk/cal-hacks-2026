"""Tests for the end-to-end demo runner. Run from the repo root: python3 -m pytest demo/tests

The runner must complete offline, block the injected listing in beat 3, approve only on the third try in beat 4,
and emit JSON that validates against the contracts on main (contracts/). One REAL mirror seller wins round 1.
"""
import io
import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from demo import adapters, run_demo
from demo.approval_flow import STRIPE_ENV, stripe_charge_test
from demo.common import Narrator, schema_errors
from pay.callscript import clean_advocate_reason

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 24, 5, 40, 0, tzinfo=timezone.utc)


def full_run(**kw):
    buf = io.StringIO()
    run = run_demo.run_all(now=NOW, say=Narrator(True, buf), **kw)
    return run, buf.getvalue()


@pytest.fixture(scope="module")
def result():
    run, text = full_run()
    return run, text


@pytest.fixture(scope="module")
def run(result):
    return result[0]


def b(run, n):
    return run["beats"][str(n)]


# ---------- the whole run ----------

def test_full_run_completes_and_every_check_passes(run):
    assert run["beats_run"] == [1, 2, 3, 4, 5]
    assert run["checks"] and all(run["checks"].values()), run["checks"]


def test_full_run_works_with_no_network(monkeypatch):
    def no_net(*a, **k):
        raise AssertionError("the offline demo tried to open a socket")
    monkeypatch.setattr(socket.socket, "connect", no_net)
    run, _ = full_run()
    assert all(run["checks"].values())


def test_json_round_trips(run):
    assert json.loads(json.dumps(run, default=str))["schema"] == run_demo.SCHEMA


# ---------- beat 1 ----------

def test_beat1_skips_the_owned_psu_and_cites_the_entry(run):
    goal = b(run, 1)["goal"]
    psu = next(i for i in goal["items"] if i["part"] == "psu")
    assert psu["skipped_owned_part_id"] == "owned-psu"
    assert any("owned-psu" in s and "750 W PSU" in s for s in b(run, 1)["skip_lines"])
    assert [i["sku_spec"] for i in b(run, 1)["need"]["items"]] == ["rtx 5070 ti"]
    assert goal["cap"] == 1300.0 and goal["items"][0]["allowed_conditions"] == ["new", "open-box"]


def test_sellers_never_see_the_cap(run):
    for bid in b(run, 2)["bids"]:
        assert "spend_limit" not in json.dumps(bid)
        assert "floor" not in bid and all("floor" not in l for l in bid["lines"])


# ---------- beat 2 ----------

def test_beat2_every_bid_is_labelled_and_mirror_bids_carry_listing_urls(run):
    bids = b(run, 2)["bids"]
    assert {x["origin"] for x in bids} == {"MIRROR", "SIM"}
    for x in bids:
        assert x["source"] == {"MIRROR": "mirror", "SIM": "simulated"}[x["origin"]]
        for line in x["lines"]:
            assert line["origin"] in ("MIRROR", "SIM") and line["listing_url"].startswith("http")
            if line["origin"] == "MIRROR":
                assert "derived" not in line["basis"]   # a real seller never gets an invented line
    assert len({x["seller_id"] for x in bids}) == len(bids)  # one agent per seller of record
    several = [x for x in bids if len(x["lines"]) > 1]
    assert several and all(len({l["offered_condition"] for l in x["lines"]}) == len(x["lines"]) for x in several)


def test_beat2_cheapest_eligible_bid_is_vetoed_with_a_cited_source(run):
    b2 = b(run, 2)
    ranked, cards = b2["ranking"]["ranked"], b2["cards"]
    assert ranked[0]["seller_id"] == "shady-sam" and cards[0]["recommendation"] == "veto"
    assert cards[0]["call_reason"]["rule_id"] == "advocate.condition"   # Lane A's real call_reason and closed summary
    assert cards[0]["call_reason"]["source_url"].endswith("shady-sam-gpu-5070ti-lies.html")
    rules = {w["rule_id"] for w in cards[0]["warnings"]}
    assert rules == {"advocate.condition", "advocate.price"}  # the page shows open-box; the false "was" price
    assert all(w["source_url"].startswith("http") for c in cards for w in c["warnings"])
    assert any("highest recorded $829.00" in w["text"] for w in cards[0]["warnings"])
    assert b2["winner"]["seller_id"] == "best-buy" and b2["winner_seller_id"] == "best-buy"


def test_beat2_a_real_mirror_seller_wins_on_a_real_line(run):
    b2 = b(run, 2)
    win = next(x for x in b2["bids"] if x["id"] == b2["winner"]["bid_id"])
    assert win["origin"] == "MIRROR" and win["lines"][b2["winner"]["line"]]["origin"] == "MIRROR"
    assert win["lines"][b2["winner"]["line"]]["unit_price"] == 1299.99 and 1299.99 <= b(run, 1)["goal"]["cap"]
    assert win["mirror_snapshot_id"].startswith("bestbuy-")
    card = next(c for c in b2["cards"] if c["bid_id"] == win["id"])
    assert card["recommendation"] == "buy" and card["fit"]["verdict"] == "pass"   # ASUS Prime, maker-spec 304 mm in a 305 mm case (test_demo_winner.py)
    assert all(s["origin"] == "SIM" for s in b2["sellers"] if s["id"] in {"shady-sam", "bargain-bin", "lowball", "fair-price-pc", "gadget-grove"})


def test_seller_model_one_seller_two_condition_lines_cheapest_allowed_line_is_picked(run):
    b2 = b(run, 2)
    grove = next(x for x in b2["bids"] if x["seller_id"] == "gadget-grove")
    assert [l["offered_condition"] for l in grove["lines"]] == ["new", "open-box"]
    entry = next(r for r in b2["ranking"]["ranked"] if r["seller_id"] == "gadget-grove")
    assert entry["condition"] == "open-box" and entry["landed"] == min(l["unit_price"] for l in grove["lines"])
    assert [a["condition"] for a in entry["alternatives"]] == ["new", "open-box"]   # lines are alternatives, never summed
    assert entry["landed"] < grove["lines"][0]["unit_price"]
    card = next(c for c in b2["cards"] if c["bid_id"] == grove["id"])
    assert card["line"] == entry["line"] == 1 and card["judged_condition"] == "open-box"
    assert not any(w["rule_id"] == "advocate.spec" for w in card["warnings"])   # allowed open-box is not "you asked for new"


def test_advice_compares_on_quality_adjusted_price_not_raw_price(run):
    ranked = b(run, 2)["ranking"]["ranked"]
    by = {r["seller_id"]: r for r in ranked}
    assert by["gadget-grove"]["landed"] < by["best-buy"]["landed"]
    assert "fair-price-pc" not in by and any(d["seller_id"] == "fair-price-pc" for d in b(run, 2)["ranking"]["disqualified"])   # $1,329 is over the cap
    assert by["best-buy"]["adjusted"] < by["gadget-grove"]["adjusted"]    # open-box and unknown returns cost points
    assert [r["adjusted"] for r in ranked] == sorted(r["adjusted"] for r in ranked)


def test_beat2_incompatible_part_is_vetoed_by_the_fit_checker(run):
    card = next(c for c in b(run, 2)["cards"] if c["bid_id"].endswith("bargain-bin"))
    assert card["recommendation"] == "veto" and card["call_reason"]["rule_id"] == "fit.gpu_length"
    assert card["warnings"][0]["text"] == "Does not fit: The card is longer than your case allows."


def test_beat2_referee_rejects_a_bid_under_its_floor_before_ranking(run):
    b2 = b(run, 2)
    low = next(r for r in b2["referee"] if r["seller_id"] == "lowball")
    assert low["passed"] is False and "floor" in low["reasons"][0]
    assert all(r["seller_id"] != "lowball" for r in b2["ranking"]["ranked"])
    assert next(x for x in b2["bids"] if x["seller_id"] == "lowball")["floor_check_passed"] is False


def test_beat2_sealing_and_anti_snipe(run):
    b2 = b(run, 2)
    vis = b2["visibility"]
    assert vis["before_close"] == {"public": 0, "buyer": 0} and vis["after_close"] == vis["bids_sealed"]
    assert set(vis["each_seller_sees"].values()) == {1}
    assert b2["clock"]["extensions"] == 1 and b2["clock"]["closed_ms"] == 17000


def test_beat2_only_the_learners_last_second_bid_extends_the_deadline(run):
    arrivals = b(run, 2)["arrivals"]
    assert len(arrivals) >= 12   # the cadence must hold with the full seller list, not just the first five
    extended = [a["seller_id"] for a in arrivals if a["extended"]]
    assert extended == [arrivals[-1]["seller_id"]]
    window_open = 12000 - 3000
    assert all(a["at_ms"] < window_open for a in arrivals[:-1])


def test_beat2_mirror_bids_over_the_cap_are_out_and_unknown_condition_is_not_guessed(run):
    out = {d["seller_id"]: d for d in b(run, 2)["ranking"]["disqualified"]}
    assert "over the goal cap" in " ".join(out["ebay-263900"]["reasons"]) and "ebay-442526" in out
    assert any("will not guess" in r for r in out["micro-center"]["reasons"])


def test_beat2_every_advocate_reason_is_speakable(run):
    for c in b(run, 2)["cards"]:
        kept, dropped = clean_advocate_reason(c["call_reason"])
        assert not dropped and set(kept) == {"rule_id", "summary", "host"}, (c["call_reason"], dropped)


def test_real_fit_checker_advocate_claim_check_and_shield_are_actually_called():
    from data.fit_checker import check_fit
    from shield.core import screen
    mod, how = adapters.advocate_checks()
    assert how.startswith("REAL agents/advocate/checks.py") and Path(mod.__file__).as_posix().endswith("agents/advocate/checks.py")
    with mock.patch.object(mod, "check_fit", wraps=check_fit) as fit, mock.patch.object(mod, "advise", wraps=mod.advise) as adv, \
            mock.patch.object(mod, "call_reason", wraps=mod.call_reason) as cr, \
            mock.patch("demo.round.screen", wraps=screen) as sh, mock.patch("demo.beats.screen", wraps=screen) as sh3:
        full_run()
    assert fit.call_count >= 8 and adv.call_count >= 8 and cr.call_count >= 8 and sh.call_count >= 10 and sh3.call_count == 2


# ---------- beat 3 ----------

def test_beat3_injected_listing_is_blocked_with_rules_and_evidence(run):
    inj = b(run, 3)["injected"]
    assert inj["verdict"] == "block" and b(run, 3)["blocked"]
    assert {"shield.payee.swap", "shield.hidden.instruction", "shield.override.instruction"} <= set(inj["rule_ids"])
    assert inj["evidence_spans"] and all(s["text"] and s["rule_id"] in inj["rule_ids"] for s in inj["evidence_spans"])
    assert b(run, 3)["control"]["verdict"] == "allow"


def test_beat3_text_screening_is_the_real_screen_on_the_real_page():
    from shield.core import screen
    html = (ROOT / "data/liar_pages/site/shady-sam-gpu-5070ti-injected.html").read_text(encoding="utf-8")
    assert screen(html, {"payee_of_record": "shady-sam@pay.example.test"})["verdict"] == "block"


# ---------- beat 4 ----------

def test_beat4_approves_only_on_the_third_try(run):
    tries = b(run, 4)["attempts"]
    assert [t["decision"]["approved"] for t in tries] == [False, False, True]
    assert [t["decision"]["reason"] for t in tries[:2]] == ["wrong_code", "no_code"]
    assert [t["label"] for t in tries] == ["wrong code", "code without approve", "code plus approve"]
    assert b(run, 4)["approval_record"]["result"] == "approved" and b(run, 4)["approval_record"]["attempts"] == 3
    assert b(run, 4)["code_redacted"] is True and tries[1]["said"] == "[code]" and tries[2]["said"] == "[code] approve"


def test_beat4_can_charge_passes_only_after_approval(run):
    b4 = b(run, 4)
    assert b4["can_charge_before"] == {"ok": False, "reason": "not_approved"}
    assert b4["can_charge_after"] == {"ok": True, "reason": "ok"}
    assert b4["mandate_at_approval"]["status"] == "approved" and b4["mandate"]["status"] == "used"


def test_beat4_mandate_is_above_the_allowance_and_binds_the_winner(run):
    b4, b1 = b(run, 4), b(run, 1)
    m = b4["mandate"]
    assert m["amount"] == b(run, 2)["winner"]["landed"] > b1["allowance"]["per_purchase_limit"]
    assert m["within_allowance"] is False and m["payee"] == "best-buy@pay.example.test"
    assert m["tap_signature"] == b4["signature"]["headers"]["Signature"]
    assert b4["call_script"]["stripped"] == [] and "one thousand two hundred ninety nine dollars and ninety nine cents" in b4["call_script"]["deal_line"]
    assert b4["advocate_reason"]["rule_id"] == "advocate.condition"


def test_beat4_signature_verifies_and_replay_or_edit_fails(run):
    v = b(run, 4)["verify"]
    assert v["first"] == {"ok": True, "reason": "ok"}
    assert v["replay"] == {"ok": False, "reason": "replayed_mandate"}
    assert v["altered"] == {"ok": False, "reason": "digest_mismatch"}
    assert set(b(run, 4)["signature"]["headers"]) == {"Content-Digest", "Mandate-Hash", "Signature-Agent", "Signature-Input", "Signature"}


def _mandate():
    from pay.mandate import new_mandate
    return new_mandate(deal_id="deal-t", buyer_id="vidyut", amount=773.22, payee="honest-hal@pay.example.test")


def test_beat4_scripted_approval_never_calls_stripe_even_with_a_test_key(run):
    """#193: the runner's approval is typed, not a call, so beat 4 always pays with the SIM stub."""
    assert b(run, 4)["charge"]["mode"] == "SIM stub" and "no money moved" in b(run, 4)["charge"]["status"]
    key = "sk_test_FAKEKEY1234567890"
    from demo import approval_flow
    with mock.patch.object(approval_flow, "stripe_charge_test", lambda *a, **k: pytest.fail("Stripe called after a scripted approval")):
        scripted, text = full_run(env={STRIPE_ENV: key})
    assert scripted["beats"]["4"]["charge"]["mode"] == "SIM stub" and "after a real call" in text
    assert key not in text and key not in json.dumps(scripted, default=str)


def test_run_demo_refuses_stripe():
    with pytest.raises(SystemExit):
        run_demo.main(["--stripe", "--no-write"])


def test_charge_or_stub_is_a_sim_stub_without_the_flag_or_a_test_key():
    from demo.approval_flow import charge_or_stub
    never = lambda *a: pytest.fail("no Stripe call")
    ch, note = charge_or_stub(_mandate(), {STRIPE_ENV: "sk_live_notatestkey"}, use_stripe=True, stripe_test=never)
    assert ch["mode"] == "SIM stub" and "is not an sk_test_ key" in note
    assert "sk_live_notatestkey" not in note and "sk_live_notatestkey" not in json.dumps(ch)
    ch, note = charge_or_stub(_mandate(), {STRIPE_ENV: "sk_test_FAKEKEY1234567890"}, use_stripe=False, stripe_test=never)
    assert ch["mode"] == "SIM stub" and note == ""


def test_charge_or_stub_uses_stripe_test_mode_only_with_flag_and_test_key_and_never_returns_the_key():
    from demo.approval_flow import charge_or_stub
    key = "sk_test_FAKEKEY1234567890"
    calls = []

    def fake(mandate, k):
        calls.append(k)
        return {"mode": "Stripe test mode", "id": "pi_test_1", "object": "payment_intent", "amount_cents": 77322, "currency": "usd",
                "payment_method": "pm_card_visa (Stripe test card)", "status": "succeeded", "idempotency_key": "mandate:" + mandate["hash"]}
    ch, note = charge_or_stub(_mandate(), {STRIPE_ENV: key}, use_stripe=True, stripe_test=fake)
    assert ch["mode"] == "Stripe test mode" and calls == [key] and note == ""
    assert key not in json.dumps(ch)


def test_stripe_charge_test_sends_the_key_only_in_the_header_and_returns_no_key():
    key = "sk_test_FAKEKEY1234567890"
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None, context=None):
        seen["ctx"] = context
        seen["auth"], seen["idem"], seen["body"], seen["url"] = req.get_header("Authorization"), req.get_header("Idempotency-key"), req.data.decode(), req.full_url
        return Resp(json.dumps({"id": "pi_1", "object": "payment_intent", "amount": 77322, "currency": "usd", "status": "succeeded"}).encode())
    from pay.mandate import idempotency_key, new_mandate
    m = new_mandate(deal_id="deal-t", buyer_id="vidyut", amount=773.22, payee="honest-hal@pay.example.test")
    out = stripe_charge_test(m, key, urlopen=fake_urlopen)
    assert seen["auth"] == f"Bearer {key}" and key not in seen["body"] and key not in json.dumps(out)
    assert seen["idem"] == idempotency_key(m) == out["idempotency_key"] and "pm_card_visa" in seen["body"] and "amount=77322" in seen["body"]
    assert seen["url"].startswith("https://api.stripe.com/")
    import ssl
    assert seen["ctx"].verify_mode == ssl.CERT_REQUIRED and seen["ctx"].check_hostname   # verification stays on


def test_beat4_uses_the_env_signing_key_when_it_is_usable(tmp_path):
    from pay.tap import generate_keypair
    path = tmp_path / "k.pem"
    generate_keypair(str(path))
    run, text = full_run(env={"VISA_TAP_PRIVATE_KEY_PATH": str(path)})
    assert "VISA_TAP_PRIVATE_KEY_PATH" in run["beats"]["4"]["signature"]["key_source"]
    assert str(path) not in text and str(path) not in json.dumps(run, default=str)
    bad, _ = full_run(env={"VISA_TAP_PRIVATE_KEY_PATH": str(tmp_path / "missing.pem")})
    assert "unusable" in bad["beats"]["4"]["signature"]["key_source"] and all(bad["checks"].values())


# ---------- beat 5 ----------

def test_beat5_loss_reports_have_bands_reasons_and_sources_only(run):
    reports = b(run, 5)["round1_loss_reports"]
    by = {r["seller_id"]: r for r in reports}
    assert by["shady-sam"]["reason"] == "advocate_veto" and by["bargain-bin"]["reason"] == "fit"
    assert by["gadget-grove"]["reason"] == "price" and by["gadget-grove"]["gap_band"] == "within5"
    assert by["ebay-263900"]["gap_band"] == "within20" and "lowball" not in by and "best-buy" not in by  # the winner gets no loss report
    for r in reports:
        assert set(r) == {"id", "round_id", "seller_id", "won", "gap_band", "reason", "source_url", "created_at"}
        assert r["won"] is False and r["source_url"].startswith("http")


def test_beat5_learner_closes_the_gap_inside_its_floor_against_a_static_control(run):
    b5 = b(run, 5)
    assert b5["learner"]["round2_price"] < b5["learner"]["round1_price"] and b5["learner"]["above_floor"]
    assert b5["learner"]["round2_price"] >= b5["learner"]["floor"]
    assert b5["control"] == {"round1_price": 1329.0, "round2_price": 1329.0, "unchanged": True}
    assert b5["learning_seller"] == "gadget-grove" and b5["control_seller"] == "fair-price-pc"
    assert b5["round2"]["winner"]["seller_id"] == "gadget-grove" and b5["gap_closed"] is True
    assert b5["strategy"]["diff"] == {"price_step": {"from": 0.0, "to": 0.03}}
    assert next(r for r in b5["round2"]["loss_reports"] if r["seller_id"] == "fair-price-pc")["gap_band"] == "within5"
    assert "SIM template" in b5["what_to_change_origin"]


# ---------- contracts ----------

def test_every_artifact_validates_against_its_contract(run):
    a = run["artifacts"]
    pairs = [("Goal", a["goal"]), ("Need", a["need"]), ("Allowance", a["allowance"]), ("Mandate", a["mandate"]),
             ("Mandate", a["mandate_at_approval"]), ("VoiceApproval", a["approval_record"])]
    pairs += [("OwnedPart", o) for o in a["owned_parts"]] + [("Bid", x) for x in a["bids"]] + [("Claim", c) for c in a["claims"]]
    pairs += [("LossReport", r) for r in a["loss_reports"]]
    pairs += [("AdvocateCard", {k: c[k] for k in ("need_id", "bid_id", "warnings", "recommendation", "wait_until")}) for c in a["verdicts"]["advocate_cards"]]
    shield = a["verdicts"]["shield"] + [a["verdicts"]["injected_listing"], a["verdicts"]["control_listing"]]
    pairs += [("ShieldVerdict", {k: s[k] for k in ("message_id", "sender_agent", "verdict", "reasons", "attack_type", "latency_ms")}) for s in shield]
    assert len(pairs) > 40
    bad = [(n, schema_errors(n, o)) for n, o in pairs if schema_errors(n, o)]
    assert not bad, bad[:3]


def test_json_validates_after_a_file_round_trip(tmp_path):
    path = run_demo.write_run(full_run()[0], tmp_path)
    assert re.fullmatch(r"run-\d{8}T\d{6}Z\.json", path.name)
    a = json.loads(path.read_text(encoding="utf-8"))["artifacts"]
    assert schema_errors("Goal", a["goal"]) == [] and schema_errors("Mandate", a["mandate"]) == []
    assert all(schema_errors("LossReport", r) == [] for r in a["loss_reports"])


def test_contract_validation_catches_a_broken_artifact(run):
    broken = dict(run["artifacts"]["mandate"])
    del broken["hash"]
    assert schema_errors("Mandate", broken)
    assert schema_errors("LossReport", {"id": "x"})


# ---------- adapters ----------

def test_claim_check_adapter_returns_the_real_lane_c_check_and_it_reads_hosted_pages_offline():
    from data import claim_check
    from demo.pages import fixture_fetch
    fn, label, real = adapters.claim_checker()
    assert real is True and fn is claim_check.check_claim and label.startswith("REAL data.claim_check")
    base = "http://127.0.0.1:8765/"
    r = fn({"evidence_url": base + "shady-sam-gpu-5070ti-lies.html", "field": "was_price", "value": 1099.0}, fetch=fixture_fetch)
    assert r["result"] == "false" and "did not match the price history" in r["reason"] and r["evidence_hash"]
    r = fn({"evidence_url": base + "honest-hal-gpu-5070ti.html", "field": "condition", "value": "new"}, fetch=fixture_fetch)
    assert r["result"] == "verified"
    r = fn({"evidence_url": "https://www.bestbuy.com/x", "field": "condition", "value": "new"}, fetch=fixture_fetch)
    assert r["result"] == "unverified"  # a page we cannot read is never "false"


def test_advocate_adapter_loads_lane_a_checks_without_the_uagents_runtime():
    mod, how = adapters.advocate_checks()
    assert callable(mod.advise) and mod.CALL_SUMMARIES["fit.gpu_length"] and how.startswith("REAL agents/advocate/checks.py")
    for rule, text in mod.CALL_SUMMARIES.items():   # every closed summary is speakable on the call
        kept, dropped = clean_advocate_reason({"rule_id": rule, "summary": text, "source_url": "https://example.com/x"})
        assert not dropped, (rule, dropped)


def test_no_pending_contract_copies_remain():
    assert not (ROOT / "demo" / "contracts_pending").exists()
    assert not (ROOT / "demo" / "standins" / "advocate.py").exists() and not (ROOT / "demo" / "standins" / "claim_check.py").exists()
    for name in ("Goal", "OwnedPart", "LossReport"):
        assert (ROOT / "contracts" / f"{name}.schema.json").exists()


def test_stripe_env_reads_only_the_key_from_env_or_file_and_never_returns_other_values(tmp_path):
    f = tmp_path / ".env"
    f.write_text("OTHER=secret-other\nSTRIPE_SECRET_KEY='sk_test_FILEKEY'\n", encoding="utf-8")
    assert run_demo.stripe_env(f, {}) == {"STRIPE_SECRET_KEY": "sk_test_FILEKEY"}
    assert run_demo.stripe_env(f, {"STRIPE_SECRET_KEY": "sk_test_ENVKEY"}) == {"STRIPE_SECRET_KEY": "sk_test_ENVKEY"}
    assert run_demo.stripe_env(tmp_path / "missing", {}) == {}


def test_stripe_http_error_shows_stripe_error_type_never_the_key():
    import urllib.error
    from demo import approval_flow
    key = "sk_test_FAKEKEY1234567890"

    def boom(mandate, k):
        raise urllib.error.HTTPError("https://api.stripe.com/v1/payment_intents", 401, "Unauthorized", {},
                                     io.BytesIO(json.dumps({"error": {"type": "invalid_request_error", "code": "api_key_invalid"}}).encode()))
    with mock.patch.object(approval_flow, "stripe_charge_test", boom):
        ch, note = approval_flow.charge_or_stub(_mandate(), {STRIPE_ENV: key}, use_stripe=True)
    assert ch["mode"] == "SIM stub" and "HTTP 401, invalid_request_error/api_key_invalid" in note
    assert key not in note and key not in json.dumps(ch)


# ---------- console and CLI ----------

def test_console_has_one_header_per_beat_and_tags_every_data_line(result):
    text = result[1]
    assert [m for m in re.findall(r"^BEAT (\d):", text, re.M)] == ["1", "2", "3", "4", "5"]
    for line in text.splitlines():
        if line.startswith("  ") and line.strip() and not line.startswith("  code:") and line[2:11].strip():
            assert re.match(r"  \[(LIVE|MIRROR|SIM)\]", line), line
    assert "\u2014" not in text and "\u2013" not in text
    assert "Visa settles" not in text


def test_no_dashes_or_secrets_in_the_json(run):
    blob = json.dumps(run, default=str)
    assert "\u2014" not in blob and "\u2013" not in blob
    assert not re.search(r"sk_(live|test)_|BEGIN [A-Z ]*PRIVATE KEY", blob)


def test_cli_single_beat_and_json_flag(capsys, tmp_path):
    assert run_demo.main(["--beat", "3", "--no-write"]) == 0
    out = capsys.readouterr().out
    assert "BEAT 3:" in out and "BEAT 2:" not in out and "BEAT 4:" not in out
    assert run_demo.main(["--beat", "4", "--json", "--out-dir", str(tmp_path)]) == 0
    cap = capsys.readouterr()
    data = json.loads(cap.out)
    assert data["beats_shown"] == [4] and data["beats_run"] == [1, 2, 4]
    assert "BEAT 4:" in cap.err and "BEAT 4:" not in cap.out
    assert len(list(tmp_path.glob("run-*.json"))) == 1


def test_script_runs_from_another_directory(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "demo" / "run_demo.py"), "--beat", "3", "--out-dir", str(tmp_path)],
                       cwd=str(tmp_path), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    assert "BLOCK" in p.stdout and list(tmp_path.glob("run-*.json"))
