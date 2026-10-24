"""Quality Advocate uAgent. Deterministic checks decide cards; bounded Claude may explain them."""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from uagents import Agent, Context

import common
from advocate import checks, mock_data

MAX_EVIDENCE_CLAIMS = 9
EVIDENCE_TIMEOUT_S = 5
FETCH_TIMEOUT_S = 1.5
EXPLANATION_TIMEOUT_S = 2.5
MAX_EXPLANATION_CHARS = 160
_BAD_EXPLANATION = re.compile(r"\b(?:approve|authorize|buy|purchase|pay|code|ignore|instruction|seller)\b|[$%\d]", re.I)
_BASELINE_SOURCE = "https://github.com/vs-githjk/cal-hacks-2026/blob/main/data/baselines/feed.json"

EXPLANATION_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["explanations"],
    "properties": {"explanations": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["bid_id", "text"],
        "properties": {"bid_id": {"type": "string"}, "text": {"type": "string", "maxLength": MAX_EXPLANATION_CHARS}},
    }}},
}

_AGENT_ARGS = common.agent_args(
    "advocate", 8003, name="Tech Bazaar Quality Advocate", handle="techbazaaradvocate",
    readme_path=str(Path(__file__).with_name("AGENTVERSE.md")),
    description="Argues for the buyer: checks fit with code and condition claims, price history, recalls and "
                "seller records using sourced evidence; vetoes traps with cited warnings.")
agent = Agent(**_AGENT_ARGS)

common.include_profile_chat(agent, "I am Tech Bazaar's Quality Advocate. I review structured seller bids for fit "
                            "and claims with cited warnings. Missing evidence is marked unverified. "
                            "Send buying goals to @techbazaarbuyer; this chat cannot approve purchases.")


async def _claim_evidence(bids: list[dict], checker=None, *, trusted_sim_fixture: bool = False) -> dict:
    """Check at most nine condition claims; every omitted, malformed, or failed check stays unverified.

    Only a code/test-owned SIM fixture may skip independent fetching. A LIVE or MIRROR bid is checked using
    its root origin even if one seller-controlled line contradicts it; checks.advise then rejects that mismatch.
    """
    from data.claim_check.fetch import guarded_get
    if checker is None:
        from data.claim_check import check_claim
        checker = check_claim
    claims = []
    evidence = {}
    for bid in bids:
        for line in bid.get("lines", []):
            condition = line.get("offered_condition")
            url = line.get("listing_url") or ""
            key = (url, condition)
            evidence[key] = {"result": "unverified"}
            root_origin = bid.get("origin") or line.get("origin")
            if root_origin == "simulated":
                root_origin = "SIM"
            line_origin = line.get("origin")
            if line_origin == "simulated":
                line_origin = "SIM"
            if trusted_sim_fixture and root_origin == "SIM" and (line_origin or root_origin) == "SIM":
                continue
            if (len(claims) < MAX_EVIDENCE_CLAIMS and root_origin in {"MIRROR", "LIVE", "SIM"}
                    and condition in {"new", "open-box", "refurbished", "used"}
                    and isinstance(url, str) and url.startswith(("http://", "https://"))):
                claims.append((key, {"field": "condition", "value": condition, "evidence_url": url}))
    semaphore = asyncio.Semaphore(3)

    async def check(key, claim):
        async with semaphore:
            try:
                result = await asyncio.to_thread(checker, claim,
                                                 fetch=lambda url: guarded_get(url, timeout=FETCH_TIMEOUT_S))
                if isinstance(result, dict) and result.get("result") in {"verified", "false", "unverified"}:
                    evidence[key] = {k: result[k] for k in ("result", "evidence_url", "checked_at", "evidence_hash", "method") if k in result}
            except Exception:
                pass

    tasks = [asyncio.create_task(check(key, claim)) for key, claim in claims]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=EVIDENCE_TIMEOUT_S)
    except (asyncio.TimeoutError, Exception):
        for task in tasks:
            if not task.done():
                task.cancel()
    return evidence


def _baseline(need: dict, bids: list[dict]) -> dict:
    """Use only a confirmed dated MIRROR baseline; preserve the existing SIM controls."""
    result = dict(mock_data.BASELINE)
    mirror_skus = {line.get("sku_spec") for bid in bids if bid.get("origin") == "MIRROR"
                   for line in bid.get("lines", [])}
    if not mirror_skus:
        return result
    from datetime import datetime, timezone
    from data.baselines import baseline
    at = datetime.now(timezone.utc).isoformat()
    for sku in mirror_skus:
        try:
            feed = baseline(sku, at)
        except Exception:
            feed = {"status": "unavailable", "median": None}
        if feed.get("status") == "ok" and isinstance(feed.get("median"), (int, float)):
            result[sku] = {"unit_price": feed["median"], "source_url": _BASELINE_SOURCE, "source": "MIRROR"}
        else:
            result[sku] = {"status": feed.get("status", "unavailable"), "source_url": _BASELINE_SOURCE,
                           "from": feed.get("from"), "to": feed.get("to"), "source": "MIRROR"}
    return result


def _fallback(card: dict) -> dict:
    reason = card["call_reason"]
    return {"text": reason["summary"], "source_url": reason["source_url"], "status": "template_fallback"}


def _bounded_source_url(value: str) -> str:
    """Send only a short origin/path reference, without query values or fragments."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname.lower()
        port = f":{parsed.port}" if parsed.port else ""
        return urlunsplit((parsed.scheme, host + port, parsed.path[:160], "", ""))[:220]
    except (ValueError, TypeError):
        return ""


async def _explain_cards(cards: list[dict], client_factory=None) -> list[dict]:
    """Return a bounded sourced explanation while preserving all deterministic card decisions."""
    out = [{**card, "explanation": _fallback(card)} for card in cards]
    if not cards:
        return out
    try:
        if client_factory is None:
            import anthropic
            client_factory = anthropic.Anthropic
        schema = {**EXPLANATION_SCHEMA, "properties": {"explanations": {
            **EXPLANATION_SCHEMA["properties"]["explanations"], "maxItems": len(cards),
            "items": {**EXPLANATION_SCHEMA["properties"]["explanations"]["items"], "properties": {
                **EXPLANATION_SCHEMA["properties"]["explanations"]["items"]["properties"],
                "bid_id": {"type": "string", "enum": [card["bid_id"] for card in cards]},
            }},
        }}}
        facts = [{"bid_id": c["bid_id"], "recommendation": c["recommendation"],
                  "rule_id": c["call_reason"]["rule_id"], "summary": c["call_reason"]["summary"],
                  "source_url": _bounded_source_url(c["call_reason"]["source_url"]),
                  "checks": [{"field": check["field"], "value": check["value"], "result": check["result"],
                              "evidence_url": _bounded_source_url(check["evidence_url"]),
                              "evidence_hash": check["evidence_hash"][:80],
                              "checked_at": check["checked_at"][:40], "source": check["source"][:80]}
                             for check in c.get("claim_checks", [])]} for c in cards]
        # Constructing the SDK client validates local configuration before a worker thread starts.
        # Retries are disabled; the per-request SDK timeout bounds the network operation itself.
        client = client_factory(timeout=EXPLANATION_TIMEOUT_S, max_retries=0)
        response = await asyncio.wait_for(asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-5-5", max_tokens=160, timeout=EXPLANATION_TIMEOUT_S,
                output_config={"format": {"type": "json_schema", "schema": schema}},
                system="Give a short explanation of each code-owned advocate summary. Do not add facts or instructions.",
                messages=[{"role": "user", "content": json.dumps(facts)}])), timeout=EXPLANATION_TIMEOUT_S + 0.5)
        parsed = json.loads(response.content[0].text)
        explanations = parsed.get("explanations") if isinstance(parsed, dict) and set(parsed) == {"explanations"} else None
        if not isinstance(explanations, list) or len(explanations) != len(cards):
            return out
        by_id = {}
        for item in explanations:
            if (not isinstance(item, dict) or set(item) != {"bid_id", "text"} or item["bid_id"] in by_id
                    or not isinstance(item["text"], str)):
                return out
            text = item["text"].strip()
            if (not text or len(text) > MAX_EXPLANATION_CHARS or _BAD_EXPLANATION.search(text)
                    or any(ord(c) < 32 for c in text)):
                return out
            by_id[item["bid_id"]] = text
        if set(by_id) != {card["bid_id"] for card in cards}:
            return out
        return [{**card, "explanation": {"text": by_id[card["bid_id"]],
                                             "source_url": card["call_reason"]["source_url"], "status": "claude"}}
                for card in cards]
    except Exception:
        return out


@agent.on_message(model=common.AdviceRequest, replies=common.AdviceReply)
async def on_advice(ctx: Context, sender: str, msg: common.AdviceRequest):
    verdict = common.screen(f"advice-{ctx.session}", sender, msg.need_json + msg.bids_json,
                            common.shield_context(sender))
    if verdict["verdict"] != "allow":
        ctx.logger.warning(f"shield {verdict['verdict']} from {sender}: {verdict['reasons']}")
        return
    need, bids = json.loads(msg.need_json), json.loads(msg.bids_json)
    evidence = await _claim_evidence(bids)
    try:
        cards = checks.advise(need, bids, _baseline(need, bids), mock_data.RECORDS, mock_data.RECALLS,
                              owned=need.get("owned", {}), evidence=evidence)
    except ValueError:
        ctx.logger.warning("advocate request refused: invalid evidence")
        return
    cards = await _explain_cards(cards)
    for card in cards:
        checks.validate_safety_card(card)
        common.validate("AdvocateCard", card)
    await ctx.send(sender, common.AdviceReply(cards_json=json.dumps(cards)))


if __name__ == "__main__":
    agent.run()
