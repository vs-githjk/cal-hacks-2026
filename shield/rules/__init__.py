"""Rules as files: one module per rule family, each exposing Rule objects with a stable id."""
from shield.rules import encoded, exfil, hidden, impersonation, intent, money, override, payee, price, private_ask, screen_code

RULES = [
    override.RULE,
    hidden.TEXT_RULE,
    hidden.INSTRUCTION_RULE,
    payee.RULE,
    money.RULE,
    price.RULE,
    exfil.RULE,
    screen_code.RULE,
    private_ask.RULE,
    encoded.RULE,
    impersonation.RULE,
    impersonation.OUTPUT_RULE,
    *intent.RULES,
]
RULES_BY_ID = {r.id: r for r in RULES}
