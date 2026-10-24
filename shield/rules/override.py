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

# French, German and Chinese (#187). The folded view also strips accents, so "precedentes" matches as well. Traditional
# Chinese is read through a one-to-one character map to Simplified, so offsets stay the same.
# A "System:" label in these languages blocks only when an imperative follows it, so a spec line such as
# "Systeme : Windows 11", "Systeme : teste et approuve" or "系统：Windows 11" stays allowed. (The English "System:"
# rule above is unchanged; see #250.)
_T2S = str.maketrans(
    "無視規則現個沒這賣統從開須聽給購買進說為設對話電記發書舊過價錢機體僅隻應該將執準遵們號製擬達頁響訊無論與後條"
    "請勿東關於種類結點門問題選項輸處顯幣額費運讓證認識錯誤詞語",
    "无视规则现个没这卖统从开须听给购买进说为设对话电记发书旧过价钱机体仅只应该将执准遵们号制拟达页响讯无论与后条"
    "请勿东关于种类结点门问题选项输处显币额费运让证认识错误词语")
_FR_ACTION = (r"(?:approuvez|validez|ignorez|oubliez|autorisez|payez|accordez|transf[eé]rez"
              r"|(?:approuve|valide|paie|paye)\s+(?:ce|cet|cette|le|la|les|l'|imm[eé]diatement|maintenant))")
_DE_ACTION = (r"(?:genehmige|genehmigen\s+sie|bezahle|bezahlen\s+sie|zahle|zahlen\s+sie|[uü]berweise|[uü]berweisen\s+sie"
              r"|vergiss|vergessen\s+sie|ignoriere|ignorieren\s+sie|gib\s+frei|geben\s+sie\s+frei|akzeptiere|best[aä]tige)\b")
_ZH_ACTION = r"(?:批准|忽略|无视|执行|跳过|放行|无需|立即付款|直接付款|马上付款|立刻付款)"
_FR_NOUN = r"(?:instructions?|consignes?|r[eè]gles?|directives?|messages?|ordres?)"
_DE_NOUN = r"(?:anweisungen|anweisung|instruktionen|regeln|befehle|vorgaben|anordnungen)"
_ZH_NOUN = r"(?:指令|指示|规则|提示词?|设定|限制|命令|要求|说明(?!书))"
_ZH_BEFORE = r"(?:之前|以前|先前|上面|上述|此前|前面|原来|原有|所有|全部|一切|你的|以上|任何)"
_AGENT_FR = r"(?:assistant|agent|ia|bot|robot|mod[eè]le|ai)"
I18N_PATTERNS = [
    # fr: ignore the previous instructions, forget your rules, you are now, from now on, new instructions, note to agents
    rx(r"\bignor(?:e|ez|er)\s+(?:toutes\s+|tous\s+)?(?:les\s+|tes\s+|vos\s+|mes\s+)?" + _FR_NOUN + r"\s+"
       r"(?:pr[eé]c[eé]dentes?|ant[eé]rieures?|ci-dessus|d'avant|pass[eé]es)"
       r"|\bignor(?:e|ez|er)\s+(?:toutes\s+)?(?:vos|tes)\s+" + _FR_NOUN),
    rx(r"\boubli(?:e|ez|er)\s+(?:toutes\s+)?(?:les\s+|tes\s+|vos\s+)" + _FR_NOUN +
       r"|\boubli(?:e|ez|er)\s+tout\s+ce\s+qui\s+(?:pr[eé]c[eè]de|est\s+au-dessus)"),
    rx(r"\bne\s+(?:tiens|tenez)\s+(?:pas|plus)\s+compte\s+(?:des|de\s+tes|de\s+vos)\s+(?:\w+\s+)?" + _FR_NOUN +
       r"|\b(?:mets|mettez)\s+de\s+c[oô]t[eé]\s+(?:tes|vos|les|toutes\s+les)\s+(?:\w+\s+)?" + _FR_NOUN),
    rx(r"\b(?:tu\s+es|vous\s+[eê]tes)\s+(?:maintenant|d[eé]sormais|dor[eé]navant)\s+"
       r"(?:(?:un|une|l'|le|la|en\s+mode)\s*(?:\w+\s+){0,2}?" + _AGENT_FR + r"\b"
       r"|libre\b|dan\b|sans\s+(?:r[eè]gles?|limites?|restrictions?|filtres?))"),
    rx(r"\b(?:[aà]\s+partir\s+de\s+maintenant|d[eé]sormais|dor[eé]navant),?\s+(?:tu|vous)\s+"
       r"(?:ignor\w*|approuv\w*|valid\w*|oubli\w*|ob[eé]i\w*|(?:dois|devez)\s+(?:ignorer|approuver|valider|ob[eé]ir|oublier))"),
    rx(r"\bnouvelles?\s+(?:instructions?|consignes?)\s*:"),
    rx(r"\b(?:note|message|avis|consigne|instruction)s?\s+(?:aux|pour\s+les|[aà]\s+tous\s+les|[aà]\s+l'|pour\s+l')\s*(?:\w+\s+){0,2}?"
       r"(?:agents?|assistants?|bots?|ia)\b"),
    # de: ignore the previous instructions, forget your rules, you are now, from now on, new instructions, note to agents
    rx(r"\b(?:ignorier(?:e|en|t)?|missacht(?:e|en|et)?)\s+(?:sie\s+)?(?:alle\s+)?(?:deine\s+|die\s+|ihre\s+|meine\s+)?"
       r"(?:(?:vorherige|bisherige|obige|fr[uü]here|vorige|vorangegangene|alte)n?\s+)?" + _DE_NOUN + r"\b"),
    rx(r"\bvergiss\s+(?:alle\s+)?(?:deine|die|ihre|alle)\s+(?:\w+\s+)?" + _DE_NOUN +
       r"|\bvergessen\s+sie\s+(?:alle\s+)?(?:ihre|die)\s+(?:\w+\s+)?" + _DE_NOUN +
       r"|\bvergiss\s+alles\s+(?:davor|vorher|bisherige|oben)"),
    rx(r"(?:\b(?:du\s+bist|sie\s+sind)\s+(?:jetzt|nun|ab\s+sofort|ab\s+jetzt|von\s+(?:nun|jetzt)\s+an)"
       r"|\b(?:ab\s+sofort|ab\s+jetzt|jetzt|nun|von\s+(?:nun|jetzt)\s+an)\s+(?:bist\s+du|sind\s+sie))\s+"
       r"(?:(?:ein|eine|einer|der|die|im|kein|keine)\s+(?:\w+\s+){0,2}?(?:assistent\w*|agent\w*|ki|bot|modell|roboter)\b"
       r"|frei\b|dan\b|ohne\s+(?:regeln|einschr[aä]nkungen|grenzen|filter))"),
    rx(r"\b(?:ab\s+(?:jetzt|sofort)|von\s+(?:nun|jetzt)\s+an)\s+"
       r"(?:(?:ignorierst|vergisst|genehmigst|bezahlst|gehorchst|musst|sollst)\s+du"
       r"|(?:ignorieren|vergessen|genehmigen|gehorchen)\s+sie)\b"),
    rx(r"\bneue\s+(?:anweisung(?:en)?|instruktion(?:en)?|befehle?|vorgaben?)\s*:"),
    rx(r"\b(?:hinweis|nachricht|mitteilung|anweisung|befehl)\s+(?:an|f[uü]r)\s+(?:alle\s+|die\s+|den\s+)?(?:\w+\s+)?"
       r"(?:\w*agenten?|assistenten?|bots?|ki)\b"),
    # zh: ignore the previous instructions, you are now, from now on, new instructions, to all agents
    rx(r"(?:忽略|无视|忽视|忘记|忘掉|不要理会|别管|丢弃|不要遵守|不用遵守|别遵守|不必遵守|不再遵守)[^。！？\n]{0,8}?" + _ZH_BEFORE +
       r"[^。！？\n]{0,6}?" + _ZH_NOUN +
       r"|(?:忘记|忘掉|忽略|无视)(?:之前|以前|上面|以上|前面)的?一切"),
    rx(r"(?:(?:你|您)(?:现在|从现在起|从现在开始|从此)|(?:现在|从现在起|从现在开始|从此)[,，]?\s*(?:你|您))(?:是|就是|扮演|成为)"
       r"[^。！？\n]{0,10}?(?:助手|ai|机器人|模型|代理|没有限制|不受限制|不受任何限制|无限制|没有规则|dan)"),
    rx(r"从(?:现在|今天|此刻)(?:起|开始)[,，]?\s*(?:你|您)(?:只|必须|要|将|应该|就)?"
       r"(?:听|服从|批准|同意|忽略|无视|跳过|执行|遵守|扮演|是)"),
    rx(r"新的?(?:指令|指示|命令)\s*[:：]"),
    rx(r"(?:致|给)(?:所有)?[^。！？\n]{0,6}?(?:代理|智能体|助手|机器人|ai)[^。！？\n]{0,3}?[:：]"),
    # labels in all three: système, Systemhinweis, 系统提示, with an imperative right after them
    rx(r"(?:^|[\n\r>\[\(\{\"'【「])\s*(?:(?:instruction|message|note|consigne)\s+syst[eè]me|syst[eè]me|d[eé]veloppeur"
       r"|systemhinweis|systemnachricht|systemanweisung|entwickler|系统(?:提示|消息|通知|指令)?|开发者)\s*[\]】」]?\s*[:：\]】」]\s*"
       r"(?:\w+\s+){0,2}?(?:" + _FR_ACTION + "|" + _DE_ACTION + r")"),
    rx(r"(?:^|[\n\r>\[\(\{\"'【「])\s*(?:系统(?:提示|消息|通知|指令)?|开发者)\s*[\]】」]?\s*[:：\]】」][^\n]{0,20}?" + _ZH_ACTION),
]


def check(doc, ctx):
    yield from finditer_spans(doc, PATTERNS + I18N_PATTERNS)
    simplified = doc.norm.translate(_T2S)
    if simplified != doc.norm:
        for p in I18N_PATTERNS:
            for m in p.finditer(simplified):
                if m.end() > m.start():
                    yield doc.raw_span(m.start(), m.end())


RULE = Rule("shield.override.instruction", BLOCK, "high",
            "instruction override aimed at the reading agent", check, fold=True)
