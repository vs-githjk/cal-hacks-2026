"""shield.override.instruction: text that tries to replace the reading agent's instructions."""
from shield.rules.base import BLOCK, Rule, finditer_spans, rx

PATTERNS = [
    rx(r"\bignore\s+(?:all\s+|any\s+|every\s+)?(?:of\s+)?(?:your\s+|the\s+|my\s+)?"
       r"(?:previous|prior|above|earlier|preceding|former)\s+"
       r"(?:instructions?|rules?|prompts?|directions?|guidelines?|messages?|context)"),
    rx(r"\b(?:disregard|forget|override|bypass)\s+(?:all\s+|any\s+)?(?:of\s+)?(?:your\s+|the\s+)?"
       r"(?:previous\s+|prior\s+|above\s+|earlier\s+|system\s+|safety\s+)?"
       r"(?:instructions?|rules?|prompts?|guidelines?|programming|safeguards?)"),
    rx(r"\bnew\s+instructions?\s*:"),
    rx(r"(?:^|[\n\r>\[\(\{\"'])\s*(?:system|assistant|developer)\s*(?:prompt|message|note|override)?\s*[:\]]"),
    rx(r"\byou\s+are\s+now\s+(?:a|an|the|in|my|acting|operating|unrestricted|free|dan|no\s+longer)\b"),
    rx(r"\bfrom\s+now\s+on,?\s+(?:you|ignore|always|only)\b"),
    rx(r"\bpretend\s+(?:to\s+be|you\s+are)\b"),
    rx(r"\b(?:jailbreak|developer\s+mode|dan\s+mode)\b"),
    rx(r"\bact\s+as\s+(?:if\s+you\s+(?:are|were)|an?\s+(?:unrestricted|different|new|system|admin))"),
    rx(r"\b(?:note|message|instructions?|attention|notice|memo)s?\s+(?:to|for)\s+(?:all\s+|the\s+)?"
       r"(?:shopping\s+|buyer\s+|seller\s+|ai\s+)?(?:agents?|assistants?|bots?|llms?|models?)\b"),
    rx(r"\bdo\s+not\s+(?:tell|mention|reveal|show)\s+(?:this|it)?\s*to\s+the\s+(?:buyer|owner|user|advocate)"),
    rx(r"\breveal\s+(?:your|the)\s+(?:system\s+)?prompt"),
]

# French, German and Chinese (#187). The folded view also strips accents, so "precedentes" matches as well.
# A "System:" label in these languages blocks only when an action follows on the same line, so a spec line such as
# "Systeme : Windows 11" or "系统：Windows 11" stays allowed.
_ACTION = (r"(?:approuv|valid|ignor|oubli|autoris|payez|genehmig|bezahl|zahle|vergiss|freigeb|akzeptier"
           r"|批准|同意|忽略|执行|跳过|放行|无需|立即付款)")
I18N_PATTERNS = [
    # fr: ignore the previous instructions, forget your rules, you are now, from now on, new instructions, note to agents
    rx(r"\bignor(?:e|ez|er)\s+(?:toutes\s+|tous\s+)?(?:les\s+|tes\s+|vos\s+|mes\s+)?"
       r"(?:instructions?|consignes?|r[eè]gles?|directives?|messages?)\s+"
       r"(?:pr[eé]c[eé]dentes?|ant[eé]rieures?|ci-dessus|d'avant|pass[eé]es)"),
    rx(r"\boubli(?:e|ez|er)\s+(?:toutes\s+)?(?:les\s+|tes\s+|vos\s+)(?:instructions?|consignes?|r[eè]gles?|directives?)"),
    rx(r"\b(?:tu\s+es|vous\s+[eê]tes)\s+(?:maintenant|d[eé]sormais|dor[eé]navant)\s+"
       r"(?:(?:un|une|l'|le|la|en\s+mode)\s*(?:\w+\s+){0,2}?(?:assistant|agent|ia|bot|robot|mod[eè]le|ai)\b"
       r"|libre\b|sans\s+(?:r[eè]gles?|limites?|restrictions?))"),
    rx(r"\b(?:[aà]\s+partir\s+de\s+maintenant|d[eé]sormais|dor[eé]navant),?\s+(?:tu|vous)\s+"
       r"(?:ignor\w*|dois|devez|approuv\w*|valid\w*|oubli\w*|ob[eé]i\w*|n'|ne\s)"),
    rx(r"\bnouvelles?\s+(?:instructions?|consignes?)\s*:"),
    rx(r"\b(?:note|message|avis|consigne)s?\s+(?:aux|pour\s+les|[aà]\s+tous\s+les)\s+(?:\w+\s+){0,2}?(?:agents?|assistants?|bots?|ia)\b"),
    # de: ignore the previous instructions, forget your rules, you are now, from now on, new instructions, note to agents
    rx(r"\bignorier(?:e|en|t)?\s+(?:sie\s+)?(?:alle\s+)?(?:deine\s+|die\s+|ihre\s+|meine\s+)?"
       r"(?:vorherigen|bisherigen|obigen|fr[uü]heren|vorigen|vorangegangenen|alten)\s+"
       r"(?:anweisungen|instruktionen|regeln|befehle|vorgaben|anordnungen)"
       r"|\bignorier(?:e|en|t)?\s+(?:sie\s+)?alle\s+(?:deine\s+|ihre\s+)?(?:anweisungen|instruktionen|regeln|befehle|vorgaben)"),
    rx(r"\bvergiss\s+(?:alle\s+)?(?:deine|die|ihre|alle)\s+(?:\w+\s+)?(?:anweisungen|instruktionen|regeln|befehle|vorgaben)"
       r"|\bvergessen\s+sie\s+(?:alle\s+)?(?:ihre|die)\s+(?:\w+\s+)?(?:anweisungen|instruktionen|regeln|vorgaben)"),
    rx(r"\b(?:du\s+bist|sie\s+sind)\s+(?:jetzt|nun|ab\s+sofort|ab\s+jetzt)\s+"
       r"(?:(?:ein|eine|einer|der|die|im|kein|keine)\s+(?:\w+\s+){0,2}?(?:assistent\w*|agent\w*|ki|bot|modell|roboter)\b"
       r"|frei\b|ohne\s+(?:regeln|einschr[aä]nkungen|grenzen))"),
    rx(r"\b(?:ab\s+(?:jetzt|sofort)|von\s+nun\s+an)\s+(?:ignorierst|vergisst|genehmigst|bezahlst|gehorchst|musst|sollst)\s+du\b"),
    rx(r"\bneue\s+(?:anweisungen|instruktionen|befehle|vorgaben)\s*:"),
    rx(r"\b(?:hinweis|nachricht|mitteilung)\s+(?:an|f[uü]r)\s+(?:alle\s+)?(?:\w+\s+)?(?:\w*agenten|assistenten|bots|ki)\b"),
    # zh: ignore the previous instructions, you are now, from now on, new instructions, to all agents
    rx(r"(?:忽略|无视|忽视|忘记|忘掉|不要理会|别管|丢弃)掉?你?(?:之前|以前|先前|上面|上述|此前|前面|原来|原有|所有|全部|一切|你的|以上)"
       r"[^。！？\n]{0,6}?(?:指令|指示|规则|提示词?|设定|限制|命令|要求|说明)"),
    rx(r"(?:你|您)(?:现在|从现在起|从此)(?:是|就是|扮演|成为)[^。！？\n]{0,10}?(?:助手|ai|机器人|模型|代理|没有限制|不受限制|无限制|没有规则)"),
    rx(r"从(?:现在|今天|此刻)(?:起|开始)[,，]?\s*(?:你|您)(?:只|必须|要|将|应该|不要|不必|无需)"),
    rx(r"新的?(?:指令|指示|命令)\s*[:：]"),
    rx(r"(?:致|给)(?:所有)?[^。！？\n]{0,6}?(?:代理|智能体|助手|机器人|ai)[^。！？\n]{0,3}?[:：]"),
    # labels in all three: système, Systemhinweis, 系统提示, with an action after them on the same line
    rx(r"(?:^|[\n\r>\[\(\{\"'【「])\s*(?:syst[eè]me|d[eé]veloppeur|systemhinweis|systemnachricht|systemanweisung|entwickler"
       r"|系统(?:提示|消息|通知|指令)?|开发者)\s*[:：\]】」]\s*(?=[^\n]{0,40}?" + _ACTION + r")"),
]


def check(doc, ctx):
    return finditer_spans(doc, PATTERNS + I18N_PATTERNS)


RULE = Rule("shield.override.instruction", BLOCK, "high",
            "instruction override aimed at the reading agent", check, fold=True)
