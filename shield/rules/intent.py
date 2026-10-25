"""Intent rules: lexicons plus co-occurrence scoring, so a paraphrase is caught without its exact words.

Each intent has word lists (English, Spanish, Hindi transliteration) grouped into roles, for example SKIP
("bypass", "without", "no need to", "omita", "zaroorat nahi") and GATE ("approval", "buyer", "advocate",
"verification"). A role pair counts only when the two matches sit close together (NEAR characters) inside one
sentence or two adjacent sentences. Strong pairs score 3, boosters (urgency, an authority claim, an assumed
role) add 1 and never fire on their own; an intent fires at 3 or more. Rules run on the normalised text and
on the folded views, so "1gn0re", "s k i p" and "omita la aprobación" are read like plain English.

Ids: shield.intent.approval_bypass (block), shield.intent.override (block), shield.intent.payment_redirect
(quarantine), shield.intent.authority_claim (quarantine), shield.intent.agent_directed (quarantine).
Everything here only reads text; no model is involved and the verdict carries no free text.
"""
from __future__ import annotations

import re
from typing import Iterable

from shield.rules.base import BLOCK, QUARANTINE, Rule, rx

NEAR = 70  # characters between the two halves of a pair
THRESHOLD = 3.0


def _w(*alts: str) -> "re.Pattern[str]":
    return rx(r"\b(?:" + "|".join(alts) + r")\b")


# ---- role lexicons ---------------------------------------------------------------------------------------
SKIP = _w(
    r"skip(?:s|ped|ping)?(?!\s+(?:to|ahead|the\s+(?:queue|line|wait|reviews?)))", r"bypass(?:es|ed|ing)?", r"waiv(?:e|es|ed|ing)", r"omit(?:s|ted|ting)?",
    r"leav(?:e|ing)\s+(?:out|off)", r"dispens(?:e|es|ed|ing)\s+with", r"forgo(?:ing)?", r"forego",
    r"do\s+without", r"circumvent(?:ing)?", r"no\s+need\s+(?:to|for)", r"need\s+not",
    r"(?:do|does|did|will|would)\s+not\s+(?:need|apply|require|have\s+to)", r"(?:don'?t|doesn'?t)\s+(?:need|have\s+to|apply)",
    r"not\s+(?:be\s+)?(?:necessary|needed|required|applicable|mandatory)", r"no\s+longer\s+(?:needed|required|necessary)",
    r"unnecessary", r"exempt(?:ed)?", r"optional", r"override[sd]?|overriding", r"stop\s+(?:asking|checking|requiring)",
    r"there\s+is\s+no\s+(?:requirement|need)", r"drop\s+the",
    # Spanish (accents are stripped by the folded view)
    r"omit\w+", r"salt(?:a|e|ar|ate)\w*",
    r"no\s+(?:es\s+)?(?:necesari[oa]|hace\s+falta|necesit\w+)", r"prescind\w+", r"evit(?:a|e|ar)\b", r"dispens\w+",
    # Hindi transliteration
    r"zaroorat\s+nahi", r"zarurat\s+nahi", r"jarurat\s+nahi", r"zaroori\s+nahi", r"chh?od\s+(?:do|dijiye|dena|den)",
    r"skip\s+kar\w*", r"mat\s+(?:karo|puchho|poochho|pucho|bulao)", r"avoid\s+kar\w*",
)
# "without ..." only counts when the gate word FOLLOWS it ("without waiting for your owner"), never "approval ... without a deposit".
SKIP_BEFORE_GATE = _w(r"without", r"sin\s+(?:pedir|consultar|llamar|esperar|preguntar|avisar|requerir)?", r"bina")
# bounded gaps: two unbounded \s* here took 9.6 s on "advocate" + 19,900 spaces (#236)
_NOT_MANUAL = r"(?!\s{0,20}(?:'s)?\s{0,20}(?:manual|guide|handbook|interface|account|manuals|reviews))"   # a lookahead, so wider gaps stay linear (#273)
GATE = rx(
    r"\b(?:the\s+|your\s+|our\s+|its\s+)?(?:buyer|owner|human|principal|advocate|approver)(?:'s|s')?\b" + _NOT_MANUAL
    + r"|\b(?:the|your)\s+user(?:'s)?\b" + _NOT_MANUAL
    + r"|\bapprov(?:e|al|als|ing)\b|\bverif(?:y|ication|ications|ying)\b|\bvetting\b|\bdue\s+diligence\b"
    + r"|\bsign-?\s?off\b|\bsign\s+off\b|\bauthori[sz]ation\b|\bconsent\b|\bpermission\b|\breview\b|\bchecks\b"
    + r"|\b(?:safety|security|second|manual|phone|voice|advocate)\s+checks?\b|\bcall-?back\b"
    + r"|\b(?:voice|phone)\s+(?:call|approval|check)\b|\bthe\s+call\b|\bverification\s+call\b"
    # Spanish
    + r"|\baprobaci\w+|\baprobar\b|\bverificaci\w+|\bverificar\b|\bcomprador\w*|\bpropietari[oa]\b|\bduen[oa]\b"
    + r"|\babogad[oa]\b|\bautorizaci\w+|\bpermiso\b|\bconsentimiento\b|\brevisi\w+"
    # Hindi transliteration
    + r"|\bmaalik\b|\bmalik\b|\bmanzoori\b|\bmanjuri\b|\bmanjoori\b|\banumati\b|\bijazat\b"
)
CLEARED = _w(
    r"already\s+(?:been\s+)?(?:cleared|approved|authori[sz]ed|signed\s+off|okayed|greenlit|green-?lit)",
    r"pre-?\s?(?:cleared|approved|authori[sz]ed|vetted|okayed)",
    r"(?:has|have|had)\s+(?:been\s+)?(?:cleared|signed\s+off|okayed|green-?lit|approved)\s+(?:by|with)",
    r"(?:was|were|been)\s+(?:cleared|approved|authori[sz]ed|signed\s+off)\s+(?:by|with)",
    r"cleared\s+(?:\w+\s+){0,3}?(?:with|by)",
    r"ya\s+(?:fue|esta|ha\s+sido|se\s+ha)\s+(?:aprobad|autorizad)\w*", r"pre-?aprobad\w*", r"ya\s+aprobad\w+",
    r"pehle\s+se(?:\s+hi)?\s+(?:approved|approve|manjoor|manzoor)\w*",
)
PROCEED = _w(
    r"go\s+ahead", r"proceed(?:ing)?(?!\s+to\s+(?:checkout|payment|cart|the\s+cart))", r"move\s+(?:ahead|forward)",
    r"(?:please\s+|kindly\s+|just\s+|simply\s+)ship\s+(?:it|this|the\s+(?:order|goods|item|unit)|now|out)",
    r"release(?:\s+the)?\s+(?:goods|payment|funds|order|item|shipment)", r"finali[sz](?:e|es|ing)",
    r"complet(?:e|ed|ing)\s+(?:the|this|your)\s+(?:order|purchase|deal|payment|transaction)",
    r"process\s+(?:the|this)\s+(?:order|payment|purchase)", r"charge\s+(?:the\s+card|it|now|them)",
    r"send\s+(?:the\s+)?(?:payment|money|funds)", r"settle\s+(?:the|this)", r"confirm\s+(?:the|this)\s+(?:order|deal|purchase|transaction|payment)",
    r"place\s+the\s+order", r"close\s+(?:the|this)\s+deal", r"accept\s+(?:the|this)\s+(?:offer|bid|deal)",
    r"you\s+may\s+charge",
    # Spanish
    r"proced\w+", r"adelante", r"env[ií]\w*\s+(?:el\s+)?pedido", r"libera\w*", r"finaliza\w*",
    # Hindi transliteration
    r"aage\s+bad\w+", r"bhej\s+(?:do|dijiye|dena|den)", r"bhejiye", r"bhejo", r"payment\s+kar\w*", r"bhugtan\s+kar\w*",
    r"process\s+kar\w*", r"ship\s+kar\w*", r"order\s+bhej\w*", r"confirm\s+kar\w*", r"paisa\s+bhej\w*",
)
APPROVE = _w(
    r"approv(?:e|es|ing)", r"authori[sz](?:e|es|ing)", r"sign(?:ing)?\s+off", r"green-?\s?light(?:ing)?",
    r"okay(?:ing)?", r"clear(?:ing)?\s+(?:this|it)", r"accept(?:ing)?",
    r"confirm(?:s|ing)?\s+(?:the|this|every|all)\s+(?:\w+\s+){0,2}?(?:order|deal|purchase|transaction|payment|shipment|bid|offer|claims?)",
    r"lift(?:ed|ing)?\s+(?:the\s+)?veto", r"veto\s+(?:is\s+|was\s+)?(?:lifted|withdrawn|removed|cancell?ed)",
    r"mark\s+(?:\w+\s+){0,3}?(?:as\s+)?verified",
    r"aprueb\w+|apruebe|autoriz[ao]\w*", r"approve\s+kar\w*", r"manjoor\s+kar\w*",
)
URGENT = _w(
    r"urgent(?:ly)?", r"immediate(?:ly)?", r"right\s+away", r"straight\s+away", r"asap", r"today", r"deadline",
    r"last\s+chance", r"expires?", r"time-?sensitive", r"hurry", r"without\s+delay", r"this\s+instant",
    r"within\s+(?:the|an?|\d+)\s+(?:hour|minutes?|day)", r"right\s+now", r"before\s+(?:midnight|close|the\s+deadline)",
    r"urgente", r"inmediat\w+", r"ahora\s+mismo", r"de\s+inmediato", r"hoy\s+mismo", r"cuanto\s+antes",
    r"turant", r"abhi", r"jaldi", r"foran", r"fauran",
)
AUTH = _w(
    r"compliance\s+(?:requires?|team|department|officer|policy|rules?|reasons?|says|demands?)",
    r"(?:legal|regulatory|regulation|audit|security|fraud|finance|treasury|risk)\s+(?:department|team|requirements?|reasons?|rules?|policy|audit|review|requires?|demands?)",
    r"by\s+order\s+of", r"on\s+the\s+orders?\s+of", r"under\s+(?:regulation|section|article|policy|law)",
    r"per\s+(?:regulation|policy|section|article|law|compliance)", r"required\s+by\s+(?:law|regulation|policy)",
    r"(?:the\s+)?(?:management|executives?|ceo|cfo|head\s+office|headquarters|administrators?|admins?|supervisor|marketplace|platform|fish\s*market|smell\s*test|tech\s*bazaar|bazaar\s*shield)\s+(?:has|have|requires?|demands?|instructs?|orders?|authori[sz]es?|decided|ruled|needs?)",
    r"mandatory", r"official\s+(?:notice|instruction|directive|request)", r"security\s+audit", r"regulations?\s+\d+",
    r"cumplimiento", r"normativa", r"auditor\w+", r"por\s+orden\s+de", r"gerencia", r"regulaci\w+",
    r"compliance\s+ke\s+liye", r"sarkari\s+niyam", r"management\s+ka\s+aadesh", r"kanoon\w*",
)
ROLE = rx(
    r"\b(?:as|speaking\s+as|writing\s+as|acting\s+as|playing)\s+(?:the\s+|an?\s+|your\s+|their\s+)?"
    r"(?:buyer|owner|advocate|purchasing|procurement|finance|admin|manager|approver|principal|deputy|delegate|marketplace|authori[sz]ed)"
    r"\w*(?!\s+of\s+(?:this|our|the)\s+(?:shop|store|company|business|brand))"
    r"|\b(?:deputy|delegate|representative|proxy)\s+of\s+(?:the\s+)?(?:buyer|owner|advocate|marketplace)"
    r"|\bon\s+behalf\s+of\s+(?:the\s+|your\s+)?(?:buyer|owner|advocate|purchasing)"
    r"|\brole-?\s?play\b|\bimagine\s+(?:you\s+are|that\s+you)\b"
    r"|\byou\s+(?:are|have\s+become)\s+(?:now\s+)?the\s+(?:purchasing|procurement|final|approving|decision|admin|manager|approver)"
    r"|\bi\s+(?:am|represent|speak\s+for)\s+(?:the\s+)?(?:buyer|owner|advocate)'?s?\s+\w+"
    r"|\bcomo\s+(?:el\s+)?(?:asistente|agente|representante)\s+del\s+(?:comprador|propietario)"
)
DISCARD = _w(
    r"ignor(?:e|es|ed|ing)", r"disregard(?:s|ed|ing)?", r"forget(?:ting)?", r"set(?:ting)?\s+aside", r"put(?:ting)?\s+aside",
    r"lay(?:ing)?\s+aside", r"discard(?:s|ed|ing)?", r"drop(?:ping)?", r"overrid(?:e|es|ing)", r"supersed(?:e|es|ing)",
    r"abandon(?:ing)?", r"stop\s+following", r"(?:do\s+not|don'?t)\s+follow", r"overlook(?:ing)?", r"neglect(?:ing)?",
    r"cast(?:ing)?\s+aside", r"throw(?:ing)?\s+out", r"pay\s+no\s+(?:attention|heed)\s+to", r"dismiss(?:ing)?", r"ditch(?:ing)?",
    r"ignor[ae]\w*", r"olvid[ae]\w*", r"descart[ae]\w*", r"anul[ae]\w*",
    r"ignore\s+kar\w*", r"bhool\s+(?:jao|jaiye|ja)", r"ignore\s+karo", r"nazarandaz\w*",
)
INSTR = _w(
    r"instructions?", r"guidance", r"guidelines?", r"rules?", r"directives?", r"directions?", r"prompts?",
    r"programming", r"constraints?", r"orders", r"polic(?:y|ies)", r"what\s+you\s+(?:were|have\s+been)\s+(?:told|given)",
    r"instrucciones", r"reglas", r"indicaciones", r"nirdesh\w*", r"niyam\w*",
)
QUAL = _w(
    r"earlier", r"previous", r"prior", r"above", r"before", r"original", r"initial", r"existing", r"given", r"your",
    r"all", r"any", r"every", r"former", r"old", r"anteriores?", r"previas?", r"pichle", r"purane", r"pehle\s+ke",
)
CHANGE = _w(
    r"new(?:er)?", r"updated?", r"chang(?:e|ed|es|ing)", r"revised?", r"different", r"alternat(?:e|ive)", r"another",
    r"replac(?:ed|ement)", r"moved", r"switch(?:ed|ing)?", r"instead\s+of", r"rather\s+than", r"going\s+forward",
    r"from\s+now\s+on", r"nuev[oa]s?", r"cambi\w+", r"actualizad\w+", r"distint[oa]", r"alternativ\w+", r"otra",
    r"nay[aei]|naye", r"badal\w*", r"alag", r"doosra|dusra",
)
_NEG_BEFORE = re.compile(r"(?:\bnot|\bnever|\bno|n't|\bnor|\bunchanged|\bsame|\bstill|\bremain\w*)\W+(?:\w+\W+){0,2}$")
DEST_STRONG = rx(
    r"\b(?:iban|swift|bic|routing\s+(?:number|no)|sort\s+code|bank(?:ing)?\s+(?:account|details|information|info|transfer|data)"
    r"|account\s+(?:number|details|info\w*)|wallet(?:\s+address)?|beneficiar(?:y|ies)|payee|payout(?:\s+(?:account|address|details))?"
    r"|remittance|crypto(?:currency)?\s+address|payment\s+(?:details|information|instructions|address|account|destination)"
    r"|receiving\s+account|settlement\s+account|cuenta\s+bancaria|datos\s+bancarios|numero\s+de\s+cuenta|beneficiari\w+|billetera"
    r"|bank\s+account|khat[ae]|khaata)\b"
)
DEST_WEAK = _w(r"account", r"address", r"details", r"company", r"partner", r"third\s+party", r"cuenta", r"khata")
PAYV = _w(
    r"pay(?:ment|ments|ing|s)?", r"paid", r"remit\w*", r"wire[ds]?", r"transfer\w*",
    r"send(?:ing)?\s+(?:the\s+)?(?:money|funds|payment)", r"deposit\w*", r"settle\w*", r"funds", r"money", r"invoice\w*",
    r"bank\w*", r"pago", r"pague", r"pagar", r"transfier\w+", r"fondos", r"dinero", r"factura", r"paisa", r"paise",
    r"bhugtan", r"rakam", r"bhej\w+",
)
_IBAN = re.compile(r"\b[a-z]{2}\d{2}(?:\s?[a-z0-9]{4}){3,7}(?:\s?[a-z0-9]{1,3})?\b")

# ---- agent-directed text ---------------------------------------------------------------------------------
_AGENT = r"(?:agents?|assistants?|bots?|llms?|language\s+models?)"
_IMPERATIVE = (r"(?:please|kindly|now|when|always|never|do\s+not|don'?t|you|your|make\s+sure|remember|ensure|state|tell|say|"
               r"recommend|rank|approve|pay|skip|ignore|send|mark|verify|trust|accept|summari[sz]e|report|list|put|give|prefer|"
               r"choose|select|pick|rate|score|treat|consider|disclose|share|reveal|forward|confirm|release|ship|charge|"
               r"proceed|go\s+ahead|use|stop|forget|por\s+favor|debes|ignora|aprueba)")
AGENT_PATTERNS = [
    rx(r"\b(?:dear|hello|hi|hey|attention|attn|note\s+to|message\s+to|notice\s+to|instructions?\s+(?:to|for)|calling|estimad[oa])\s+"
       r"(?:the\s+|any\s+|all\s+|every\s+)?(?:(?:ai|shopping|buying|buyer'?s?|automated|reading|purchasing|llm|bot)\s+){0,2}" + _AGENT + r"\b"),
    rx(r"\b(?:if|when|since|because)\s+you\s+(?:are|'re|were)\s+(?:an?\s+|the\s+)?(?:(?:ai|language|automated|shopping)\s+)*" + _AGENT + r"\b"),
    rx(r"\b(?:agents?|assistants?|bots?|ai|agente|asistente)\s*[,:]\s*" + _IMPERATIVE + r"\b"),
    rx(r"\byou,?\s+(?:the\s+)?(?:ai\s+)?" + _AGENT + r"\b"),
    rx(r"\bas\s+(?:an?|the)\s+(?:ai\s+)?" + _AGENT + r",?\s+you\s+(?:must|should|need|have|will|are|shall|can|may)\b"),
    rx(r"\b(?:the|your|this)\s+(?:(?:buyer'?s?|shopping|purchasing|ai|automated|reading)\s+){0,2}(?:agents?|assistants?|bots?)\s+"
       r"(?:should|must|shall|needs?\s+to|has\s+to|have\s+to|is\s+to|are\s+to|is\s+required\s+to|is\s+instructed\s+to|ought\s+to)\b"),
]


# ---- scoring ---------------------------------------------------------------------------------------------
Span = tuple[int, int]


def _spans(p: "re.Pattern[str]", text: str) -> list[Span]:
    return [(m.start(), m.end()) for m in p.finditer(text) if m.end() > m.start()]


def _near(a: list[Span], b: list[Span], limit: int = NEAR) -> Span | None:
    """Hull of the first pair (one from each list, different matches) that lies within `limit` characters."""
    for s1, e1 in a:
        for s2, e2 in b:
            if (s1, e1) == (s2, e2):
                continue
            gap = max(s2 - e1, s1 - e2)
            if gap <= limit:
                return min(s1, s2), max(e1, e2)
    return None


def _follows(first: list[Span], second: list[Span], limit: int = 45) -> Span | None:
    """Hull of the first pair where a `second` match starts after a `first` match, within `limit` characters."""
    for s1, e1 in first:
        for s2, e2 in second:
            if s2 >= e1 and s2 - e1 <= limit:
                return s1, e2
    return None


def _changes(text: str) -> list[Span]:
    """CHANGE matches that are not negated ("banking details have NOT changed", "the same account")."""
    out = []
    for s, e in _spans(CHANGE, text):
        if _NEG_BEFORE.search(text[max(0, s - 30):s]):
            continue
        out.append((s, e))
    return out


def _sentences(text: str) -> list[Span]:
    return [(m.start(), m.end()) for m in re.finditer(r"[^.!?;\n]+", text) if m.group(0).strip()]


def _units(text: str) -> Iterable[tuple[int, int, bool]]:
    """(start, end, is_pair): every sentence, then every two adjacent sentences."""
    sents = _sentences(text)
    for a in sents:
        yield a[0], a[1], False
    for a, b in zip(sents, sents[1:]):
        yield a[0], b[1], True


_LEX_PATTERNS = {"skip": SKIP, "gate": GATE, "cleared": CLEARED, "proceed": PROCEED, "approve": APPROVE,
                 "urgent": URGENT, "auth": AUTH, "role": ROLE, "discard": DISCARD, "instr": INSTR, "qual": QUAL,
                 "strong": DEST_STRONG, "weak": DEST_WEAK, "payv": PAYV, "sbg": SKIP_BEFORE_GATE}


_HAS_WORD = re.compile(r"[a-z]{3}")


def _lex(sentence: str) -> dict[str, list[Span]]:
    """Every lexicon role's matches in one sentence (offsets inside the sentence). Computed once per sentence."""
    if not _HAS_WORD.search(sentence):  # markup debris such as "</p>" or "<br/>": nothing to score
        return {**{name: [] for name in _LEX_PATTERNS}, "chg": [], "iban": []}
    lex = {name: _spans(p, sentence) for name, p in _LEX_PATTERNS.items()}
    lex["chg"] = _changes(sentence)
    m = _IBAN.search(sentence)  # digits survive only in the plain view; folded views read them as letters
    lex["iban"] = [(m.start(), m.end())] if m else []
    return lex


def _merge(a: dict, a_off: int, b: dict, b_off: int) -> dict:
    return {k: [(s + a_off, e + a_off) for s, e in a[k]] + [(s + b_off, e + b_off) for s, e in b[k]] for k in a}


def _eval(lex: dict, off: int, pair: bool) -> dict[str, tuple[float, Span]]:
    """Score one unit for every intent. Returns rule_id -> (score, evidence span in this view's offsets)."""
    skip, gate, cleared = lex["skip"], lex["gate"], lex["cleared"]
    proceed, approve = lex["proceed"], lex["approve"]
    urgent, auth, role = lex["urgent"], lex["auth"], lex["role"]
    found: dict[str, tuple[float, Span]] = {}

    def put(rule_id: str, score: float, span: Span | None):
        if span is not None and score > found.get(rule_id, (0, (0, 0)))[0]:
            found[rule_id] = (score, (span[0] + off, span[1] + off))

    # approval bypass
    sg = None if pair else (_near(skip, gate) or _follows(lex["sbg"], gate))  # one sentence only: a skip in one and a gate in the next is no pair
    if sg:
        put("approval_bypass", 3 + bool(urgent) + bool(auth), sg)
    cg = None if pair else _near(cleared, gate)
    if cg:
        put("approval_bypass", 3 + bool(urgent), cg)
    elif cleared and proceed:
        put("approval_bypass", 3 + bool(urgent) + bool(auth), (min(cleared[0][0], proceed[0][0]), max(cleared[0][1], proceed[0][1])))

    # override of the reader's instructions
    discard, instr, qual = lex["discard"], lex["instr"], lex["qual"]
    di = None if pair else _near(discard, instr)
    if di and _near([di], qual, 30):
        put("override", 3, di)

    # payment redirect
    chg, strong, weak, payv = lex["chg"], lex["strong"], lex["weak"], lex["payv"]
    cs = None if pair else _near(chg, strong)
    if cs:
        put("payment_redirect", 3, cs)
    elif not pair:
        cw = _near(chg, weak)
        if cw and payv:
            put("payment_redirect", 3, cw)
    if lex["iban"] and payv and not pair:
        put("payment_redirect", 3, lex["iban"][0])

    # authority claim or assumed role, plus an action
    act = bool(approve or proceed or cleared or _near(skip, gate) or _follows(lex["sbg"], gate))
    if act and (auth or role):
        hull = (auth or role)[0]
        put("authority_claim", 3 + (1 if (auth and role) else 0) + bool(urgent), hull)
    return found


def analyse(doc) -> dict[str, list[Span]]:
    """rule id suffix -> evidence spans (offsets of doc.norm) for this view of the message."""
    if "intent" in doc.cache:
        return doc.cache["intent"]
    text, result = doc.norm, {}
    if text:
        sents = _sentences(text)
        lexes = [_lex(text[s0:e0]) for s0, e0 in sents]
        units = [(s0, lx, False) for (s0, _), lx in zip(sents, lexes)]
        full = [any(lx.values()) for lx in lexes]
        for i in range(len(sents) - 1):
            if not (full[i] and full[i + 1]):  # a pair adds nothing when one half matched no lexicon word
                continue
            (s0, _), (s1, _) = sents[i], sents[i + 1]
            units.append((s0, _merge(lexes[i], 0, lexes[i + 1], s1 - s0), True))
        for off, lx, pair in units:
            for rule_id, (score, span) in _eval(lx, off, pair).items():
                if score >= THRESHOLD:
                    result.setdefault(rule_id, []).append(span)
    doc.cache["intent"] = result
    return result


def _role_allows_agent_rule(ctx) -> bool:
    return str((ctx or {}).get("sender_role") or "seller").lower() in ("seller", "unknown", "")


def _make(key: str):
    def check(doc, ctx):
        if key == "authority_claim" and not _role_allows_agent_rule(ctx):
            return []  # the buyer's own agent, the advocate and the marketplace may speak with their own authority
        return [doc.raw_span(s, e) for s, e in analyse(doc).get(key, [])]
    return check


def check_agent_directed(doc, ctx):
    if not _role_allows_agent_rule(ctx):
        return []
    return [doc.raw_span(m.start(), m.end()) for p in AGENT_PATTERNS for m in p.finditer(doc.norm) if m.end() > m.start()]


APPROVAL_BYPASS = Rule("shield.intent.approval_bypass", BLOCK, "high",
                       "text that tells the buyer side to skip, waive or pre-clear an approval", _make("approval_bypass"), fold=True)
OVERRIDE = Rule("shield.intent.override", BLOCK, "high",
                "paraphrased attempt to discard the reader's earlier instructions", _make("override"), fold=True)
PAYMENT_REDIRECT = Rule("shield.intent.payment_redirect", QUARANTINE, "critical",
                        "a changed payee, account or wallet for the payment", _make("payment_redirect"), fold=True)
AUTHORITY_CLAIM = Rule("shield.intent.authority_claim", QUARANTINE, "high",
                       "an authority or role claim used to push an approval, payment or shipment", _make("authority_claim"), fold=True)
AGENT_DIRECTED = Rule("shield.intent.agent_directed", QUARANTINE, "medium",
                      "an instruction aimed at the reading agent or assistant inside seller text", check_agent_directed, fold=True)
RULES = [APPROVAL_BYPASS, OVERRIDE, PAYMENT_REDIRECT, AUTHORITY_CLAIM, AGENT_DIRECTED]


def fires(doc, ctx=None) -> bool:
    """True when any intent rule fires on the doc or its folded views (used for hidden-element content)."""
    for view in [doc, *doc.views()]:
        if any(r.check(view, ctx or {}) for r in RULES):
            return True
    return False
