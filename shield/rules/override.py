"""shield.override.instruction: text that tries to replace the reading agent's instructions."""
import html
import re
import unicodedata

from shield.rules.base import BLOCK, Rule, finditer_spans, rx

PATTERNS = [
    rx(r"\bignore\s+(?:all\s+|any\s+|every\s+)?(?:of\s+)?(?:your\s+|the\s+|my\s+)?"
       r"(?:previous|prior|above|earlier|preceding|former)\s+"
       r"(?:instructions?|rules?|prompts?|directions?|guidelines?|messages?|context)"),
    rx(r"\bignore\s+(?:all|any|every)\s+(?:of\s+)?(?:your\s+|the\s+|my\s+)?(?:instructions?|rules?|prompts?|guidelines?)\b"),   # #263
    rx(r"\b(?:disregard|forget|override|bypass)\s+(?:all\s+|any\s+)?(?:of\s+)?(?:your\s+|the\s+)?"
       r"(?:previous\s+|prior\s+|above\s+|earlier\s+|system\s+|safety\s+)?"
       r"(?:instructions?|rules?|prompts?|guidelines?|programming|safeguards?)"),
    rx(r"\bnew\s+instructions?\s*:"),
    # A role label: "System prompt:", "[system]", "assistant:" always. A bare "System:" is judged by bare_system_spans.
    rx(r"(?:^|[\n\r>\[\(\{\"'])[ \t]{0,20}(?:system[ \t]{0,5}(?:prompt|message|note|override)|assistant|developer)[ \t]{0,5}[:\]]"
       r"|(?:^|[\n\r>\[\(\{\"'])[ \t]{0,20}system[ \t]{0,5}\][ \t]{0,5}"),
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
    "無視規則現個沒這賣統從開須聽給購買進說為設對話電記發書舊過價錢機體僅隻應該將執準們號製擬達頁響訊論與後條"
    "請東關於種類結點門問題選項輸處顯幣額費運讓證認識錯誤詞語會別來丟馬確帳單員務權撥預裝則轉賬棄",
    "无视规则现个没这卖统从开须听给购买进说为设对话电记发书旧过价钱机体仅只应该将执准们号制拟达页响讯论与后条"
    "请东关于种类结点门问题选项输处显币额费运让证认识错误词语会别来丢马确帐单员务权拨预装则转账弃")
_FR_ACTION = (r"(?:approuvez|validez|ignorez|oubliez|autorisez|payez|accordez|transf[eé]rez"
              r"|(?:approuve|valide|paie|paye|ignore|oublie|autorise)\s+(?:ce|cet|cette|le|la|les|l'|tes|vos|tout|imm[eé]diatement|maintenant)"
              # #263: an infinitive order ("approuver le paiement") or a bare "approuve" ending the line
              r"|(?:approuver|ignorer|oublier|autoriser|transf[eé]rer)\b"
              r"|payer\s+(?:maintenant|imm[eé]diatement|tout\s+de\s+suite|ce\s+vendeur|le\s+vendeur)\b"
              r"|valider\s+le\s+paiement\b(?!\s+[aà]\s+la\s+livraison)"
              r"|(?<!et )(?<!et\t)approuve(?=[ \t]*(?:[.!\n]|$)))")   # "teste et approuve" is a spec line
_DE_ACTION = (r"(?:genehmige|genehmigen\s+sie|bezahle|bezahlen\s+sie|zahle|zahlen\s+sie|[uü]berweise|[uü]berweisen\s+sie"
              r"|vergiss|vergessen\s+sie|ignoriere|ignorieren\s+sie|gib\s+frei|geben\s+sie\s+frei|akzeptiere|best[aä]tige"
              # #263: the infinitive order ("Zahlung freigeben")
              r"|genehmigen|bezahlen|zahlen|[uü]berweisen|ignorieren|vergessen|freigeben|akzeptieren)\b")
# 付款 and 转账 are orders unless a delay or description word follows: "付款后48小时内发货", "转账请备注订单号" (#263).
# After 请 ("请付款后释放") they are always orders.
_ZH_ACTION = r"(?:批准|忽略|无视|跳过|放行|同意付款|请(?:立即|马上|立刻|直接|现在)?(?:付款|转账)|(?:付款|转账)(?!后|之后|以后|前|之前|时|方式|请|成功|完成|记录|凭证|截图|信息|备注|账号|账户))"
_FR_NOUN = r"(?:instructions?|consignes?|r[eè]gles?|directives?|messages?|ordres?)"
_DE_NOUN = r"(?:anweisungen|anweisung|instruktionen|regeln|befehle|vorgaben|anordnungen)"
_ZH_NOUN = r"(?:指令|指示|规则|规定|提示词?|设定|限制|命令|要求|说明(?!书)|内容)"
_ZH_BEFORE = r"(?:之前|以前|先前|上面|上述|此前|前面|原来|原有|所有|全部|一切|你的|以上|任何)"
_AGENT_FR = r"(?:assistant|agent|ia|bot|robot|mod[eè]le|ai)"
I18N_PATTERNS = [
    # fr: ignore the previous instructions, forget your rules, you are now, from now on, new instructions, note to agents
    rx(r"\bignor(?:e|ez|er)\s+(?:toutes\s+|tous\s+)?(?:les\s+|tes\s+|vos\s+|mes\s+)?" + _FR_NOUN + r"\s+"
       r"(?:pr[eé]c[eé]dentes?|ant[eé]rieures?|ci-dessus|d'avant|pass[eé]es)"
       r"|\bignor(?:e|ez|er)\s+(?:toutes\s+)?(?:vos|tes)\s+" + _FR_NOUN +
       r"|\bignor(?:e|ez|er)\s+(?:toutes\s+)?les\s+(?:pr[eé]c[eé]dentes|anciennes|derni[eè]res)\s+" + _FR_NOUN +
       r"|\bignor(?:e|ez|er)\s+(?:tout\s+)?ce\s+qui\s+(?:pr[eé]c[eè]de|est\s+au-dessus)"
       r"|\bignor(?:e|ez|er)\s+(?:toutes\s+)?les\s+" + _FR_NOUN + r"(?=[ \t]*(?:[.!;\n]|$))"),
    rx(r"\b(?:fais|faites)\s+abstraction\s+(?:de\s+(?:tes|vos|toutes\s+les)|des)\s+(?:\w+\s+)?" + _FR_NOUN +
       r"|\b(?:passe|passez)\s+outre\s+(?:tes|vos|les|aux)\s+(?:\w+\s+)?" + _FR_NOUN),
    rx(r"\boubli(?:e|ez|er)\s+(?:toutes\s+)?(?:les\s+|tes\s+|vos\s+)" + _FR_NOUN +
       r"|\boubli(?:e|ez|er)\s+tout\s+ce\s+qui\s+(?:pr[eé]c[eè]de|est\s+au-dessus)"),
    rx(r"\bne\s+(?:tiens|tenez)\s+(?:pas|plus)\s+compte\s+(?:des|de\s+tes|de\s+vos)\s+(?:\w+\s+)?" + _FR_NOUN +
       r"|\b(?:mets|mettez)\s+de\s+c[oô]t[eé]\s+(?:tes|vos|les|toutes\s+les)\s+(?:\w+\s+)?" + _FR_NOUN),
    rx(r"\b(?:tu\s+es|vous\s+[eê]tes)\s+(?:maintenant|d[eé]sormais|dor[eé]navant)\s+"
       r"(?:(?:un|une|l'|le|la|en\s+mode)\s*(?:\w+\s+){0,2}?" + _AGENT_FR + r"\b"
       r"|libre\b|dan\b|sans\s+(?:r[eè]gles?|limites?|restrictions?|filtres?)"
       r"|en\s+mode\s+(?:d[eé]veloppeur|dan|libre|admin\w*|debug|sans\s+\w+))"),
    rx(r"\b(?:[aà]\s+partir\s+de\s+maintenant|d[eé]sormais|dor[eé]navant),?\s+(?:tu|vous)\s+"
       r"(?:ignor\w*|approuv\w*|valid\w*|oubli\w*|ob[eé]i\w*|(?:dois|devez)\s+(?:ignorer|approuver|valider|ob[eé]ir|oublier))"),
    rx(r"\bnouvelles?\s+(?:instructions?|consignes?)\s*:"),
    rx(r"\b(?:note|message|avis|consigne|instruction)s?\s+(?:aux|pour\s+les|[aà]\s+tous\s+les|[aà]\s+l'|pour\s+l')\s*(?:\w+\s+){0,2}?"
       r"(?:agents?|assistants?|bots?|ia)\b"
       # "Note aux agents de transport" is a note to delivery staff (#263)
       r"(?!\s+(?:de\s+(?:transport|livraison|voyage|s[eé]curit[eé]|nettoyage|service|maintenance|quai)|immobiliers?|commerciaux)"
       r"(?![^\n]{0,120}?" + _FR_ACTION + r"))"),
    # de: ignore the previous instructions, forget your rules, you are now, from now on, new instructions, note to agents
    rx(r"\b(?:ignorier(?:e|en|t)?|missacht(?:e|en|et)?)\s+(?:sie\s+)?(?:bitte\s+)?(?:alle\s+|s[aä]mtliche\s+)?(?:deine\s+|die\s+|ihre\s+|meine\s+)?"
       r"(?:(?:vorherige|bisherige|obige|fr[uü]here|vorige|vorangegangene|alte)n?\s+)?" + _DE_NOUN + r"\b"),
    rx(r"\b(?:alle|die|deine|ihre|s[aä]mtliche)\s+(?:(?:vorherige|bisherige|obige|fr[uü]here|vorige|vorangegangene|alte)n?\s+)?"
       + _DE_NOUN + r"\s+(?:ignorieren|vergessen|missachten)\b"
       r"|\bsetze?n?\s+(?:sie\s+)?(?:alle\s+|s[aä]mtliche\s+)?(?:\w+\s+)?" + _DE_NOUN + r"\s+au(?:ß|ss)er\s+kraft"
       r"|\b(?:vorherige|bisherige|obige|fr[uü]here|vorige|vorangegangene)n?\s+" + _DE_NOUN + r"\s+(?:ignorieren|vergessen|missachten)\b"),
    rx(r"(?:\bvergiss\s+(?:alle\s+)?(?:deine|die|ihre|alle)\s+(?:\w+\s+)?" + _DE_NOUN +
       r"|\bvergessen\s+sie\s+(?:alle\s+)?(?:ihre|die)\s+(?:\w+\s+)?" + _DE_NOUN +
       r"|\bvergiss\s+alles\s+(?:davor|vorher|bisherige|oben)"
       r"|\bignorier(?:e|en)\s+(?:sie\s+)?alles\s+(?:davor|vorher|bisherige|oben)"
       # "Vergiss die Anweisungen zur Montage nicht" reminds, it does not order (#263)
       r")(?![^.!?\n,;]{0,40}\bnicht[ \t]*(?:[.!?\n]|$))"),
    rx(r"(?:\b(?:du\s+bist|sie\s+sind)\s+(?:jetzt|nun|ab\s+sofort|ab\s+jetzt|von\s+(?:nun|jetzt)\s+an)"
       r"|\b(?:ab\s+sofort|ab\s+jetzt|jetzt|nun|von\s+(?:nun|jetzt)\s+an)\s+(?:bist\s+du|sind\s+sie))\s+"
       r"(?:(?:ein|eine|einer|der|die|im|kein|keine)\s+(?:\w+\s+){0,2}?(?:assistent\w*|agent\w*|ki|bot|modell|roboter)\b"
       r"|frei\b|dan\b|ohne\s+(?:regeln|einschr[aä]nkungen|grenzen|filter)"
       r"|im\s+(?:entwickler|debug|admin|dan)[\w-]*modus\b)"),
    rx(r"\b(?:ab\s+(?:jetzt|sofort)|von\s+(?:nun|jetzt)\s+an)\s+"
       r"(?:(?:ignorierst|vergisst|genehmigst|bezahlst|gehorchst|musst|sollst)\s+du"
       r"|(?:ignorieren|vergessen|genehmigen|gehorchen)\s+sie)\b"),
    rx(r"\bneue\s+(?:anweisung(?:en)?|instruktion(?:en)?|befehle?|vorgaben?)\s*:"),
    rx(r"\b(?:hinweis|nachricht|mitteilung|anweisung|befehl)\s+(?:an|f[uü]r)\s+(?:alle\s+|die\s+|den\s+)?(?:\w+\s+)?"
       r"(?:\w*agenten?|assistenten?|bots?|ki)\b"),
    # zh: ignore the previous instructions, you are now, from now on, new instructions, to all agents
    rx(r"(?:忽略|无视|忽视|忘记|忘掉|不要理会|别管|丢弃|不要再?遵守|不用遵守|别遵守|不必遵守|不再遵守|停止遵守|不要再?遵循|停止遵循|不再遵循)"
       r"[^。！？\n]{0,8}?" + _ZH_BEFORE + r"[^。！？\n]{0,6}?" + _ZH_NOUN +
       r"|(?:忽略|无视|忽视|忘记|忘掉|丢弃|不要再?遵守|停止遵守|不要再?遵循|停止遵循)掉?(?:你的)?(?:这些|这条|那些|系统)?"
       r"(?:指令|指示|规则|规定|提示词?|设定|命令)" +
       r"|(?:忘记|忘掉|忽略|无视)(?:之前|以前|上面|以上|前面)的?一切"),
    rx(r"(?:(?:你|您)(?:现在|从现在起|从现在开始|从此)|(?:现在|从现在起|从现在开始|从此)[,，]?\s*(?:你|您))(?:是|就是|扮演|成为)"
       r"[^。！？\n]{0,10}?(?:助手|ai|机器人|模型|代理|没有限制|不受限制|不受任何限制|无限制|没有规则|dan|开发者模式|开发模式|调试模式)"
       r"|(?:你|您)是(?:一个|一名)?(?:没有|不受|无)(?:任何)?(?:限制|规则|约束)的(?:ai|助手|机器人|模型|代理|智能体)"),
    rx(r"(?:从(?:现在|今天|此刻)(?:起|开始)[,，]?\s*(?:你|您)(?:只|必须|要|将|应该|就)?"
       r"(?:听|服从|批准|同意|忽略|无视|跳过|执行|遵守|扮演))"),
    rx(r"新的?(?:指令|指示|命令)\s*[:：]"),
    rx(r"(?:致|给)(?:所有)?[^。！？\n]{0,6}?(?:代理|智能体|助手|机器人|ai)[^。！？\n]{0,3}?[:：]"),
    # labels in all three: système, Systemhinweis, 系统提示, with an imperative right after them
    rx(r"(?:^|[\n\r>\[\(\{\"'【「])[ \t]{0,20}(?:(?:instruction|message|note|consigne)s?\s+syst[eè]me|syst[eè]me|system|d[eé]veloppeur"
       r"|systemhinweis|systemnachricht|systemanweisung|entwickler|系统(?:提示|消息|通知|指令)?|开发者)[ \t]{0,5}[\]】」]?[ \t]{0,5}[:：\]】」][ \t]{0,5}"
       r"(?:\w+[ \t]+){0,2}?(?:" + _FR_ACTION + "|" + _DE_ACTION + r")"),
    rx(r"(?:^|[\n\r>\[\(\{\"'【「])[ \t]{0,20}(?:系统(?:提示|消息|通知|指令)?|开发者)[ \t]{0,5}[\]】」]?[ \t]{0,5}[:：\]】」][ \t]{0,5}"
       r"(?:请)?(?:立即|马上|立刻|直接|现在)?" + _ZH_ACTION +
       # a delay word does not excuse an order later on the line: "系统：付款成功后放行", "付款方式改为转账给我" (#263)
       r"|(?:^|[\n\r>\[\(\{\"'【「])[ \t]{0,20}(?:系统(?:提示|消息|通知|指令)?|开发者)[ \t]{0,5}[\]】」]?[ \t]{0,5}[:：\]】」]"
       r"[^\n]{0,30}?(?:付款|转账)[^\n]{0,20}?(?:放行|批准|释放|转给|转到我|给我|改为|即放|立即转|马上转|同意)"),
]


# #250: a bare "System:" at a line start (after a bullet or bold marker too) passes only when the rest of its line, or
# the next non-blank line, is made of spec words: an OS, a maker or product line, a model number, a unit or a build
# word. Any other word (approve, pay, trust, now ...) makes it a label aimed at the agent: fail closed.
_SYS_LABEL = rx(r"(?:^|[\n\r>\[\(\{\"'])[ \t]{0,20}(?:[-*\u2022#]+[ \t]{0,5})?[*_]{0,2}system[*_]{0,2}[ \t]{0,5}:[*_]{0,2}")
_SPEC_WORDS = frozenset("""
windows win home pro edition linux ubuntu fedora debian mint mac macos os chrome chromeos steam deck amd intel ryzen core ultra
threadripper xeon celeron pentium athlon apple nvidia geforce rtx gtx radeon rx arc ti super xt xtx gb tb mb ghz mhz w watt watts
ddr ssd hdd nvme ram memory storage cpu gpu psu case atx matx itx eatx mini micro mid full tower desktop laptop gaming prebuilt
pre built custom oem with and plus x in of asus msi gigabyte asrock evga zotac pny sapphire xfx corsair nzxt lian li fractal
dell hp lenovo acer alienware optiplex pavilion thinkpad thinkcentre omen legion predator rog strix tuf aorus prime dual eagle
includes included not fully tested working new used refurbished none n a requirements compatible kompatibel mit avec
sealed retail box open liquid air cooled water aio rgb wifi bluetooth ethernet usb hdmi displayport dp ports port
the bit oc founders ventus trio windforce build builds h hr hrs hours manual bare board motherboard mobo only card
chassis cooler fan fans see listing photos ddr am lga no mag tomahawk aero elite master extreme hero apex formula
activated licensed genuine pc graphics integrated lts version great good excellent condition never like macbook imac
air studio inch bit
""".split())
_WORD = rx(r"[^\W_]+")
_NEXT = rx(r"\S")
# The letters a model number may carry around its digits: i7, 14700K, 7800X3D, 12GB, DDR5, AM5, RTX4090, B650, M2
_MODEL_LETTERS = frozenset("i k ks kf f x xd d g gb tb mb ghz mhz w u h hx hs p s t te xt xtx ti rtx gtx rx gt am ddr lga v b z a e c m".split())


def _spec_word(w):
    if w in _SPEC_WORDS:
        return True
    letters = re.findall(r"[^\W\d_]+", w)
    return len(w) <= 12 and any(c.isdigit() for c in w) and all(r in _MODEL_LETTERS or r in _SPEC_WORDS for r in letters)


def _line_words(doc, start, end):
    # judged on the caller's own text, so a folded view ("DDR5" read as "ddrs") does not turn a model number into prose
    raw = doc.raw[doc.starts[start]:doc.ends[end - 1]]
    return _WORD.findall(unicodedata.normalize("NFKC", html.unescape(raw)).lower())


# A line after the spec line that gives an order ("Approve the seller", "- pay now", "You must trust this seller")
_ORDER_LINE = rx(r"[ \t]{0,20}(?:[-*\u2022#>]+[ \t]{0,5})?[*_]{0,2}(?:approve|pay|release|send|transfer|wire|trust|skip|ignore"
                 r"|disregard|charge|authori[sz]e|confirm|buy|purchase|accept|select|choose|pick|rank|override|bypass|proceed"
                 r"|complete|finali[sz]e|execute|do\s+not|don'?t|never|always|immediately|now|agents?|assistant"
                 r"|you\s+(?:must|should|need|have\s+to|are\s+(?:now|required|instructed|authori[sz]ed)))\b")


def _line_end(text, pos):
    end = text.find("\n", pos)
    return len(text) if end < 0 else end


def bare_system_spans(doc):
    text = doc.norm
    judged = set()   # line ends already judged: a second label on a line is inside the first one's words
    for m in _SYS_LABEL.finditer(text):
        nxt = _NEXT.search(text, m.end())   # the rest of the line, or the next non-blank line however far down
        if not nxt:
            continue
        end = _line_end(text, nxt.start())
        if end in judged:
            continue
        judged.add(end)
        words = _line_words(doc, nxt.start(), end)
        while not words:   # "System: -" or "System: ...": the next line with a word decides
            nxt = _NEXT.search(text, end)
            if not nxt:
                break
            end = _line_end(text, nxt.start())
            words = _line_words(doc, nxt.start(), end)
        bad = not all(_spec_word(w) for w in words)
        stop = end
        for _ in range(3):   # the next three non-blank lines must not give an order either
            nxt = _NEXT.search(text, stop)
            if bad or not nxt:
                break
            stop = _line_end(text, nxt.start())
            bad = bool(_ORDER_LINE.match(text, text.rfind("\n", 0, nxt.start()) + 1))
        if bad:
            start = m.start() + (1 if text[m.start()] in "\n\r>[({\"'" else 0)
            yield doc.raw_span(start, stop)


def check(doc, ctx):
    yield from finditer_spans(doc, PATTERNS + I18N_PATTERNS)
    yield from bare_system_spans(doc)
    simplified = doc.norm.translate(_T2S)
    if simplified != doc.norm:
        for p in I18N_PATTERNS:
            for m in p.finditer(simplified):
                if m.end() > m.start():
                    yield doc.raw_span(m.start(), m.end())


RULE = Rule("shield.override.instruction", BLOCK, "high",
            "instruction override aimed at the reading agent", check, fold=True)
