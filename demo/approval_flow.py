"""Beat 4: the deal is above Vidyut's allowance, so the agent calls. All of this runs through the REAL pay/ code:
pay.mandate (hash, can_charge, mark_used), pay.callscript (script_for), pay.approval (word-pair code, three tries),
pay.tap (RFC 9421 signing, verify_request) and pay.replay (used nonces).

What is simulated: the call transport (the transcripts are typed by the runner, no Cartesia), the clock (it
advances 31 s per retry to clear the 30 s cooldown instead of sleeping) and the merchant (verify_request is what
Lane C's merchant simulator will call). Because the approval here is scripted (no call), the charge is ALWAYS the SIM stub.
A Stripe test-mode PaymentIntent runs only after a real call approves: demo/bridge.py --live-call --stripe (charge_or_stub).
Before the mandate exists, the winning price is re-checked live through Bright Data (demo/recheck.py) when
BRIGHT_DATA_API_KEY is set; out of stock or a price above the quote stops the call, anything unreadable keeps the MIRROR quote.
The approval code is never printed or stored. No key is ever printed.
"""
from __future__ import annotations

import copy
import json
import os
import secrets
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Optional

from demo import recheck as recheck_mod
from demo.common import LIVE, MIRROR, SIM, money, validate
from demo.goal import needs_call
from pay.approval import ApprovalService, script_for
from pay.mandate import can_charge, idempotency_key, mark_used, new_mandate
from pay.replay import NonceStore
from pay.tap import TapKeyError, attach_signature, generate_keypair, key_id, keyring, load_private_key, sign_request, verify_request
from pay.words import WORDS

MERCHANT_URL = "https://merchant-sim.example.test/v1/charge"
KEY_ENV = "VISA_TAP_PRIVATE_KEY_PATH"
STRIPE_ENV = "STRIPE_SECRET_KEY"
RETRY_GAP_S = 31          # clears the 30 s deny cooldown on the sim clock
ANSWER_DELAY_S = 4        # Vidyut answers 4 s after the agent stops speaking (listen window is 10 s)
STRIPE_URL = "https://api.stripe.com/v1/payment_intents"
SYSTEM_CA = "/etc/ssl/cert.pem"


def _wrong_pair(code: str) -> str:
    """Two valid code words that are not Vidyut's code, so the denial is for the wrong code and not for bad words."""
    taken = set(code.split())
    return " ".join([w for w in WORDS if w not in taken][3:5])


def _decision(d) -> dict:
    return {"approved": d.approved, "reason": d.reason, "state": d.state, "final": d.final}


def stripe_charge_sim(mandate: Mapping[str, Any]) -> dict:
    cents = int(round(float(mandate["amount"]) * 100))
    return {"mode": "SIM stub", "id": "ch_sim_" + mandate["hash"][:12], "object": "charge", "amount_cents": cents,
            "currency": "usd", "payment_method": "pm_card_visa (Stripe test card, not sent)", "status": "succeeded (SIM stub, no money moved)",
            "idempotency_key": idempotency_key(mandate)}


def _tls_context() -> ssl.SSLContext:
    """Normal certificate checking. A python.org build on macOS ships no CA file, so fall back to the system bundle
    (verification stays on; nothing is disabled)."""
    ctx = ssl.create_default_context()
    if not ssl.get_default_verify_paths().cafile and not ctx.cert_store_stats().get("x509_ca") and os.path.exists(SYSTEM_CA):
        ctx = ssl.create_default_context(cafile=SYSTEM_CA)
    return ctx


def stripe_charge_test(mandate: Mapping[str, Any], key: str, urlopen: Callable = urllib.request.urlopen) -> dict:
    """One Stripe TEST-mode PaymentIntent on the Visa test card, idempotent on the mandate hash. The key goes
    only in the Authorization header; errors name the exception type and never echo the request."""
    cents = int(round(float(mandate["amount"]) * 100))
    form = urllib.parse.urlencode({
        "amount": cents, "currency": "usd", "payment_method": "pm_card_visa", "confirm": "true",
        "automatic_payment_methods[enabled]": "true", "automatic_payment_methods[allow_redirects]": "never",
        "description": f"Fish Market demo, mandate {mandate['id']}", "metadata[mandate_hash]": mandate["hash"]}).encode()
    req = urllib.request.Request(STRIPE_URL, data=form, method="POST", headers={
        "Authorization": f"Bearer {key}", "Idempotency-Key": idempotency_key(mandate),
        "Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req, timeout=20, context=_tls_context()) as r:
        body = json.loads(r.read())
    return {"mode": "Stripe test mode", "id": body.get("id"), "object": body.get("object"), "amount_cents": body.get("amount"),
            "currency": body.get("currency"), "payment_method": "pm_card_visa (Stripe test card)", "status": body.get("status"),
            "idempotency_key": idempotency_key(mandate)}


def charge_uncertain(mandate: Mapping[str, Any]) -> dict:
    """#449 item 4 RT-10: a Stripe test call whose outcome is not known. It has no id (none is invented), so nothing can record
    it as a payment; the idempotency key is how the operator finds the original in the Stripe test dashboard."""
    return {"mode": "Stripe test mode (uncertain)", "id": None, "object": "payment_intent", "status": "uncertain",
            "idempotency_key": idempotency_key(mandate)}


def is_uncertain(charge: Mapping[str, Any]) -> bool:
    return isinstance(charge, Mapping) and charge.get("status") == "uncertain"


def charge_or_stub(mandate: Mapping[str, Any], env: Mapping[str, str], use_stripe: bool,
                   stripe_test: Optional[Callable] = None) -> tuple[dict, str]:
    """(charge, note). One Stripe TEST PaymentIntent when use_stripe and the key is sk_test_, else the SIM stub. #449 item 4 RT-10: with
    an sk_test_ key a refused or failed Stripe call is retried once with the same idempotency key (Stripe hands back the original),
    and if it still does not succeed the charge is "uncertain": never the SIM stub, which would look paid. The caller must have
    checked the approval and must not record or report an uncertain charge as paid."""
    key = env.get(STRIPE_ENV, "")
    live_ok = use_stripe and key.startswith("sk_test_")
    charge, note = None, ""
    if use_stripe and not live_ok:
        note = f"--stripe was passed but {STRIPE_ENV} is not an sk_test_ key, so the SIM stub runs"
    if live_ok:
        for _attempt in range(2):   # the second call carries the same Idempotency-Key, so it can never be a second charge
            charge, note = None, ""
            try:
                charge = (stripe_test or stripe_charge_test)(mandate, key)
            except urllib.error.HTTPError as e:   # Stripe's error type and code are safe to show; the key never is
                try:
                    err = json.loads(e.read()).get("error", {})
                except (ValueError, OSError):
                    err = {}
                note = f"Stripe test call refused (HTTP {e.code}, {err.get('type', 'unknown')}/{err.get('code', 'none')})"
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                note = f"Stripe test call failed ({type(e).__name__})"
            if charge is not None and charge.get("status") != "succeeded":   # #208: only a succeeded intent is a test charge
                note = f"Stripe test PaymentIntent {charge.get('id')} came back {charge.get('status') or 'with no status'}, not succeeded"
                charge = None
            if charge is not None:
                return charge, ""
        idem = idempotency_key(mandate)
        return charge_uncertain(mandate), (f"{note}, so the charge is uncertain: no SIM stub was recorded and nothing is reported paid. "
                                           f"Check the Stripe dashboard (test mode) for the PaymentIntent with idempotency key {idem}")
    return stripe_charge_sim(mandate), note


def _signing_key(env: Mapping[str, str], tmp: str):
    """(private_key, source label). The env key when usable, else a throwaway Ed25519 key in a temp dir."""
    if env.get(KEY_ENV):
        try:
            return load_private_key(env[KEY_ENV]), f"{KEY_ENV} (key file outside the repo)"
        except TapKeyError:
            note = f"{KEY_ENV} is set but unusable, so "
    else:
        note = ""
    path = os.path.join(tmp, "throwaway-ed25519.pem")
    generate_keypair(path)
    return load_private_key(path), note + "throwaway Ed25519 key in a temp dir (deleted after the run)"


def _live_recheck(b1: dict, b2: dict, bid: dict, win: dict, seller: dict, say, recheck_fn: Optional[Callable],
                  enabled: bool = True) -> tuple[dict, Optional[str]]:
    """Ask Bright Data what the winning listing costs now, print one honest line, return (result, stop reason or None).
    Not configured, slow or empty keep the quoted MIRROR price and say so; only an out of stock page or a rise above
    the quote stops the call (demo/recheck.py). enabled=False (the bridge, which does not handle a stopped beat 4 yet)
    makes no fetch and returns {state: skipped}."""
    line = bid["lines"][win["line"]]
    listing = {"url": line["listing_url"], "price": float(line["unit_price"]), "cap": float(b1["goal"]["cap"]),
               "snapshot_date": seller["lines"][win["line"]].get("snapshot_date", "")}
    if not enabled:
        say.line(MIRROR, f"Live re-check: off in this run, using the MIRROR price from {(listing['snapshot_date'] or '')[:10] or 'an earlier date'}")
        return recheck_mod.skipped(), None
    if recheck_fn is not None or recheck_mod.will_fetch():
        say.line(LIVE, "fetching live price through Bright Data (up to a minute)...")
    res = (recheck_fn or recheck_mod.recheck)(listing)
    dated = (listing["snapshot_date"] or "")[:10] or "an earlier date"
    state = res["state"]
    if state == "not_configured":
        say.line(MIRROR, f"Live re-check: Bright Data not configured, using the MIRROR price from {dated}")
    elif state in ("slow", "empty"):
        why = "no answer in time" if state == "slow" else f"nothing readable ({res.get('detail', 'empty')})"
        say.line(MIRROR, f"Live re-check: {why}, so the quoted MIRROR price from {dated} stands ({money(listing['price'])})")
    elif state == "stock_unknown":
        say.line(MIRROR, f"Live re-check: price {money(res['price'])} read through Bright Data at {recheck_mod.clock(res)}, but stock could not "
                         f"be read ({recheck_mod.raw_text(res)}), so stock stays unverified (MIRROR)")
    else:
        stock = "in stock" if state != "out_of_stock" else "OUT OF STOCK"
        say.line(LIVE, f"Live re-check through Bright Data: {money(res['price'])}, {stock}, {recheck_mod.clock(res)}")
    reason = recheck_mod.stop_reason(res, listing["price"], listing["cap"])
    if reason is None and state == "price_changed":
        say.line(LIVE, f"live price {money(res['price'])} is below the quote: the mandate stays at the quoted {money(listing['price'])}", 1)
    return res, reason


def run_beat4(b1: dict, b2: dict, now: datetime, say, env: Optional[Mapping[str, str]] = None,
              recheck_fn: Optional[Callable] = None, recheck_enabled: bool = True) -> dict:
    env = os.environ if env is None else env
    t0 = now.replace(microsecond=0)
    bid, win = b2["winner_bid"], b2["winner"]
    seller = next(s for s in b2["sellers"] if s["id"] == win["seller_id"])
    amount, payee = float(win["landed"]), seller["payee"]
    allowance, goal = b1["allowance"], copy.deepcopy(b1["goal"])
    call, why_call = needs_call(allowance, amount)
    say.header(4, "Two-way call approves a deal above the allowance",
               "REAL pay.mandate, pay.callscript, pay.approval, pay.tap, pay.replay; SIM call transport, clock and merchant; SIM Stripe stub")
    say.line(SIM, f"winning deal: {seller['name']} at {b2['winner_note']}; {why_call}: the agent must call")
    if bid["origin"] == MIRROR:
        say.line(SIM, f"the bid is MIRROR (a real, dated listing); the payee {payee} is a SIM test address, so no real merchant is contacted or paid")
    goal["state"], goal["reserved_amount"] = "HOLD_FOR_CALL", amount
    states = [{"state": "HUNTING", "at": b1["goal"]["created_at"]}, {"state": "HOLD_FOR_CALL", "reserved_amount": amount}]
    if not call:
        raise RuntimeError("the demo deal fits inside the allowance; nothing to approve on a call")
    live_check, stop = _live_recheck(b1, b2, bid, win, seller, say, recheck_fn, recheck_enabled)
    if stop:
        say.line(LIVE, f"call NOT placed: {stop}")
        return {"deal": {"deal_id": f"deal-{bid['id']}", "amount": amount, "payee": payee, "seller_id": seller["id"], "why_call": why_call},
                "recheck": live_check, "stopped": {"at": "recheck", "reason": stop}, "origin": SIM}

    mandate = new_mandate(deal_id=f"deal-{bid['id']}", buyer_id=goal["buyer_id"], amount=amount, payee=payee, goal_id=goal["id"],
                          within_allowance=False, origin=bid["origin"], now=t0)
    validate("Mandate", mandate)
    say.line(SIM, f"mandate {mandate['id']}: {money(mandate['amount'])} to {mandate['payee']}, expires {mandate['expires_at']} "
                  f"(10 minute quote TTL), hash {mandate['hash'][:16]}..., status {mandate['status']}")

    reason = b2["veto_reason"] or {"rule_id": "advocate.ok", "summary": "No problems found in the checks", "source_url": bid["lines"][0]["listing_url"]}
    script = script_for(mandate, reason)
    say.line(SIM, f"call script (amount and payee read from the mandate, why-answer from the closed-schema reason; stripped: {list(script.stripped) or 'nothing'}):")
    say.line(SIM, f"agent: \"{script.spoken()}\"", 1)
    say.line(SIM, 'Vidyut: "Why not the cheaper one?"', 1)
    say.line(SIM, f"agent: \"{script.why_answer}\"", 1)
    say.line(SIM, f"cited source on Vidyut's screen: {reason['source_url']}", 1)

    store = NonceStore()
    secret = env.get("APPROVAL_SECRET") or secrets.token_hex(16)
    svc = ApprovalService(secret=secret, store=store)
    session, code = svc.issue(mandate, now=t0)
    before = can_charge(mandate, t0, deal_id=mandate["deal_id"], amount=amount, payee=payee, store=store)
    say.line(SIM, f"two-word code issued and shown on Vidyut's authenticated screen (never printed here); can_charge before approval: "
                  f"{'PASS' if before else 'REFUSED'} ({before.reason})")
    session.start_call(t0)

    tries = [("wrong code", f"{_wrong_pair(code)} approve", f"{_wrong_pair(code)} approve"),
             ("code without approve", code, "[code]"),
             ("code plus approve", f"{code} approve", "[code] approve")]
    attempts, final = [], None
    t = t0
    for n, (label, said, shown) in enumerate(tries, 1):
        t = t0 + timedelta(seconds=ANSWER_DELAY_S + (n - 1) * RETRY_GAP_S)
        session.begin_listening(t - timedelta(seconds=ANSWER_DELAY_S))
        d = session.approve(said, t, confidence=0.93)
        attempts.append({"try": n, "label": label, "said": shown, "at": t.isoformat().replace("+00:00", "Z"), "decision": _decision(d)})
        verdict = "APPROVED" if d.approved else f"DENIED ({d.reason})"
        say.line(SIM, f"try {n} ({label}): Vidyut says \"{shown}\" -> {verdict}", 1)
        if d.record:
            final = d.record
        if d.approved:
            say.line(SIM, f"agent: \"{script.approved_line}\"", 2)
            break
        left = svc.max_attempts - svc.attempts_used(mandate["hash"])
        say.line(SIM, f"agent: \"{script.denied_line}\" (the call continues, {left} {'try' if left == 1 else 'tries'} left)", 2)
    if not session.state == "approved":
        raise RuntimeError("the demo call did not end approved")
    record = validate("VoiceApproval", final)
    at_approval = validate("Mandate", copy.deepcopy(mandate))
    t_charge = t + timedelta(seconds=2)
    after = can_charge(mandate, t_charge, deal_id=mandate["deal_id"], amount=amount, payee=payee, store=store)
    say.line(SIM, f"VoiceApproval {record['id']}: result {record['result']}, {record['attempts']} attempts, channel {record['channel']}, "
                  f"code stored only as a hash {record['code_hash'][:12]}...")
    say.line(SIM, f"can_charge after approval: {'PASS' if after else 'REFUSED'} ({after.reason}); mandate status {mandate['status']}")
    states.append({"state": "DONE", "reserved_amount": 0})

    # TAP-style signing and the merchant's check
    with tempfile.TemporaryDirectory() as tmp:
        priv, key_source = _signing_key(env, tmp)
    body = json.dumps({"mandate": mandate, "charge": {"amount": amount, "currency": "USD", "payee": payee}}, sort_keys=True,
                      separators=(",", ":")).encode()
    headers = sign_request(method="POST", url=MERCHANT_URL, body=body, mandate=mandate, private_key=priv, now=t_charge)
    attach_signature(mandate, headers)
    keys = keyring(priv.public_key())
    t_verify = t_charge + timedelta(seconds=1)
    first = verify_request(method="POST", url=MERCHANT_URL, headers=headers, body=body, keys=keys, store=store, now=t_verify,
                           expected_mandate_hash=mandate["hash"])
    say.line(SIM, f"request signed (RFC 9421 Ed25519, TAP-style; key: {key_source}); keyid {key_id(priv.public_key())[:12]}...")
    say.line(SIM, f"Mandate-Hash {headers['Mandate-Hash'][:16]}...  Content-Digest {headers['Content-Digest'][:24]}...")
    say.line(SIM, f"merchant simulator verify_request: {'VALID' if first else 'REJECTED'} ({first.reason})")
    if not first:
        raise RuntimeError(f"first request did not verify: {first.reason}")

    # the charge: guarded by can_charge, then the nonce is spent once
    guard = can_charge(mandate, t_verify, deal_id=mandate["deal_id"], amount=amount, payee=payee, store=store)
    if not guard:
        raise RuntimeError(f"can_charge refused at charge time: {guard.reason}")
    charge, stripe_note = charge_or_stub(mandate, env, use_stripe=False)   # a scripted approval never reaches Stripe (#193)
    mark_used(mandate, deal_id=mandate["deal_id"], amount=amount, payee=payee, store=store, now=t_verify)
    if stripe_note:
        say.line(SIM, stripe_note)
    live = charge["mode"] == "Stripe test mode"
    say.line(LIVE if live else SIM,
             f"charge ({charge['mode']}): {charge['id']} {money(charge['amount_cents'] / 100)}, status {charge['status']}, "
             f"idempotency key {charge['idempotency_key'][:20]}...")
    say.line(LIVE if live else SIM, ("a Stripe test-mode charge on a Visa test card" if live else
                                     "no Stripe call was made (the approval above is scripted; a Stripe test charge runs only after a real call: "
                                     "demo/bridge.py --live-call --stripe)")
             + ", under a TAP-style signed mandate; this is not Visa settlement")

    # a replay of the exact signed request, and an altered one
    replay = verify_request(method="POST", url=MERCHANT_URL, headers=headers, body=body, keys=keys, store=store,
                            now=t_verify + timedelta(seconds=1), expected_mandate_hash=mandate["hash"])
    tampered = body.replace(f"{amount}".encode(), b"7.22", 1)
    altered = verify_request(method="POST", url=MERCHANT_URL, headers=headers, body=tampered, keys=keys, store=store,
                             now=t_verify + timedelta(seconds=1), expected_mandate_hash=mandate["hash"])
    say.line(SIM, f"replay of the same signed request: {'ACCEPTED' if replay else 'FAILS'} ({replay.reason})")
    say.line(SIM, f"same request with the amount edited: {'ACCEPTED' if altered else 'FAILS'} ({altered.reason})")
    validate("Mandate", mandate)
    goal["state"], goal["reserved_amount"] = "DONE", 0
    return {
        "deal": {"deal_id": mandate["deal_id"], "amount": amount, "payee": payee, "seller_id": seller["id"], "why_call": why_call},
        "mandate_at_approval": at_approval, "mandate": mandate, "advocate_reason": reason,
        "call_script": {"opening": script.opening, "deal_line": script.deal_line, "ask_line": script.ask_line,
                        "why_answer": script.why_answer, "approved_line": script.approved_line, "denied_line": script.denied_line,
                        "stripped": list(script.stripped)},
        "can_charge_before": {"ok": bool(before), "reason": before.reason}, "can_charge_after": {"ok": bool(after), "reason": after.reason},
        "attempts": attempts, "approval_record": record,
        "signature": {"method": "POST", "url": MERCHANT_URL, "headers": dict(headers), "keyid": key_id(priv.public_key()),
                      "key_source": key_source, "body_sha256_in_digest": headers["Content-Digest"]},
        "verify": {"first": {"ok": bool(first), "reason": first.reason}, "replay": {"ok": bool(replay), "reason": replay.reason},
                   "altered": {"ok": bool(altered), "reason": altered.reason}},
        "recheck": live_check, "charge": charge, "goal_state_log": states, "goal_final": goal, "code_redacted": True, "origin": SIM,
    }
