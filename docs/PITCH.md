# Pitch (Sat Oct 24, 09:05 PDT, buyer-first reframe; every clause is built or labelled planned, not built)

Store prices are real dated mirrors; the bidding agents are ours (SIM) until a shop runs the Seller Kit.

**The demo order:** an RTX 5070 Ti that fits a 305 mm case, under $1,300. The winner is the ASUS Prime RTX 5070 Ti OC Edition, 304 mm (maker spec), at Best Buy, $1,299.99 before sales tax, shipping: not captured (a MIRROR listing, bid by a SIM seller; proof: `demo/tests/test_demo_winner.py`). Say "before sales tax" every time.

**One line:** Fish Market is a buyer's agent that is hard to fool and can't pay without you, starting with computer gear. You give it a goal; it reads real store listings, an advocate vetoes the traps with a source, Shield blocks listings that try to hijack it, and above your allowance nothing is paid until you approve on a phone call.

**Category:** buyer protection for agent commerce, with a deterministic referee.

**10 seconds:** Agents are starting to buy for us, and agents get fooled. Fish Market is a buyer's agent for computer gear that checks every deal against its source and can't pay past your allowance without calling you. It works today on real store listings, with no seller agent needed.

**30 seconds:** An RTX 5070 Ti lists 49 percent over launch price (Capital & Compute citing Tom's Hardware, Sep 1 2026). You give the agent a goal: this card, under $1,300, in a case that takes 305 mm, by Friday. It reads real, dated store listings and turns each into a sealed bid. Your advocate checks fit with code and every claim against the seller's page, and vetoes the trap, with the source. Smell Test screens every listing before the agent acts on it. Above your allowance it calls you. You ask "why not the cheaper one?" and it answers aloud. Your spoken code signs that exact deal; if the call fails, nothing is paid. Everything on screen is labelled LIVE, MIRROR or SIM.

**Shield, said honestly:** on 12 attacks written after we froze the rules it stopped 6 of 12 on the first run (`shield/corpus/RESULTS.md`, 2026-10-23); the misses are listed there, so a rerun is no longer blind. We say that number, not "secure".

**Seller side, the growth story (Vidyut's words, planned beyond what is listed as built):** seller agents should be intelligent and look for leeway to help the buyer get the best deal, trained to become better salespeople while staying within company policy and prices, so if a strategy works the company can learn from it. Built today: the Seller Kit (`seller_kit/api.py`, every shop it makes is SIM), floors the referee enforces, loss reports with a banded gap and a cited reason, and one deterministic learning step (`demo/learning.py`). A shop-level report of winning strategies is planned, not built.

**The referee is deterministic:** the same bids always rank the same way; outcomes vary only through the sellers and their stock (`docs/ARENA_RULES.md`).

## The five beats (stage order: buyer protection first, then sellers)

Buyer protection, which works with no outside seller agent:

1. Set a goal (typed in ASI:One on the Agentverse path; the stage run uses a scripted SIM goal; the rig Vidyut owns is a scripted SIM rig).
2. Offers arrive from real store listings (MIRROR) and labelled SIM sellers; the advocate vetoes a trap with a source (fit by code; origin badges on every bid).
3. Shield blocks an injected listing live. A "Hack the market" console for judges is planned, not built; a judge can send attacks to the Shield API or `shield-bench`.
4. The phone call approves above the allowance (word-pair code, amount read back, replay fails). Phone call only: a failed call means nothing is paid.

Seller growth:

5. The seller's loss report and learning: Gadget Grove (Vedant), a SIM shop, adjusts within its floor (one deterministic strategy diff; the "what to change" line is a SIM template today, and Claude writing it is planned, not built).

Hyphenate is built (`hyphenate/`) and is an add-on, not a beat. The IT fleet view is planned, not built. Bright Data (`data/baselines/brightdata.py`), the CRS payee gate (`pay/crs_gate.py`) and Tiger Data (`data/tiger/store.py`) are built, env-gated and not run live (no key in the run). Do not claim any of them as live on stage.

## The multiverse line (say it exactly)

"This is one real request, Vidyut's. When many requests pool, this is what a seller sees." Never say "many buyers use it". The Lot Wall (Vidyut's gold REAL brick, the rest grey SIM, the price ladder, folded back to one brick) is planned, not built; cut this line unless it exists by the freeze.

## Sourced facts (only these)

- RTX 5090 $4,999 vs $1,999 launch; RTX 5070 Ti $1,119 vs $749 (+49 percent), Sep 1 2026 (Capital & Compute citing Tom's Hardware; tier 3).
- 32 GB DDR5 costs at least $375 (Tom's Hardware headline).
- PC gaming hardware (prebuilt desktops, notebooks, DIY parts, peripherals) was a $44.5B market in 2025, up 35 percent, by Jon Peddie Research's forecast (Sep 18 2025). Say "PC gaming hardware" and "forecast", never "PC parts" or "spent".
- Microsoft Research (Magentic Marketplace, arXiv 2510.25779, Oct 2025): shopping agents show first-proposal bias, giving fast sellers a 10 to 30 times edge over better ones.
- Anthropic's browser agent pilot (Aug 25 2025): prompt injection succeeded 23.6 percent of the time against the undefended browser agent, 11.2 percent with mitigations. Prompt injection is LLM01, first on the OWASP Top 10 for LLM Applications (2025).
- Guardio Labs (Scamlexity, Aug 20 2025): an AI browser bought an Apple Watch from a fake Walmart store and filled in the saved card without asking.
- NRF and Happy Returns (Oct 15 2025): 19.3 percent of US online sales were expected to be returned in 2025.
- Morgan Stanley (Dec 8 2025): shopping agents could handle $190B to $385B of US online spending by 2030; about 23 percent of Americans bought something with AI in the past month.
- Amazon shipped an RTX 5090 with the chip missing: REPORTED. Open the article before saying it on stage.
- Never a number for research time, incompatibility rate or return rate (none found). Never "Windows 10 now": support ended Oct 14 2025.

## Q&A answers to have ready

- **Why would a seller bid?** The buyer side does not need them to: it runs on real store listings today. Sellers bid because the round is where the buyer is, and the Seller Kit (`seller_kit/api.py`) gives a shop an agent that stays above its own floor and learns from every loss. Our first sellers are marketplace, used, refurbisher and local PC shop sellers; big-box stores will not bid. The three seller agents on Agentverse are registered (`agents/README.md`), with SIM listings. A real non-agent seller side (a shop with no agent) is planned, not built.
- **Do real sellers really bid?** Not yet. No outside seller has bid. Every bid today comes from our agent: either on a real, dated store listing (MIRROR, with the link and floor) or a labelled SIM seller. LIVE is for an outside Agentverse agent. Every bid carries an origin badge: LIVE (an outside Agentverse agent; none has bid yet), MIRROR (our agent on a real listing, with the link and floor), SIM. If no seller bids at all, the agent names the best public listing and buys nothing (`agents/buyer/hunt.py`).
- **What did you prove about seller learning?** Not much yet, and we say so: in our simulator the learner beat the field-median control on 1 of 4 held-out archetypes and the gate needs 2, so there is no headline lift (`sim/RESULTS-2026-10-24-b48x3.md`, 2026-10-24). It is a simulator we built, not the market. What is real: fit by code, the veto with sources, the call client and the approval judge, and the mandate gate. A teammate purchase is planned, not built (task d6, Sat 14:00 to 15:30), and a rehearsed live call is not recorded in this repo yet.
- **Who pays, and who are the incumbents?** Consumers are free. The first payer is the small IT buyer, priced per refresh (proposed, finalized later; monthly Team $49 and Business $199 are alternatives). Sellers pay 3 percent, minimum $1, capped at $25, only on a delivered sale that passed the receiving check. Incumbents (Amazon Business, CDW and Dell business stores do approvals and POs; none referees an agent-to-agent deal or argues against a bad deal): naming them on slides is finalized later; keep it in Q&A until then. All prices are proposals, not built.
- **Is it secure?** No, and we do not say that. Say "blocked X of Y on this corpus": dev 30 of 30 and 30 of 30 (in-sample, rules written against them), the frozen probe 6 of 10 on its first run (an upper bound, the author had read it), the post-freeze check 6 of 12 on its first run, both no longer blind now that their misses are listed (`shield/corpus/RESULTS.md`, 2026-10-23). The adaptive set is planned, not built.
- **Can a cloned voice approve a buy?** No. The credential is a one-time code on the authenticated screen, bound to one mandate; a "yes" alone never approves, and a replay fails on screen.
- **Is it a chatbot?** No. The agent runs the hunt and calls you only above the allowance.
- **Why did Micro Center at $1,199.99 lose?** Its listing states no condition in our snapshot, so it cannot be ranked as new or open-box, and we do not guess one (`demo/out/sample-run.json` shows "Micro Center: unknown 1,199.99"; the winner is pinned in `demo/tests/test_demo_winner.py`).
- **Does a model decide the veto?** No. The advocate is code (`agents/advocate/checks.py`); Claude is optional for a seller's persona line and Shield's classifier (`shield/classifier.py`, off by default).
- **Do you use Bright Data, CRS or Tiger Data?** Built, env-gated, not run live (no key in the run): Bright Data (`data/baselines/brightdata.py`), the CRS payee gate (`pay/crs_gate.py`, nothing calls it before the charge yet) and Tiger Data (`data/tiger/store.py`). The demo runs without any of them.

Every clause must be built, or labelled SIM or planned, by the Sun 03:00 freeze; cut any clause that is not.
