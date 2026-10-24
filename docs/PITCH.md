# Pitch (Sat Oct 24, 03:00 PDT; every clause is built or labelled planned, not built)

Store prices are real dated mirrors; the bidding agents are ours (SIM) until a shop runs the Seller Kit.

**The demo order:** an RTX 5070 Ti that fits a 305 mm case, under $1,300. The winner is the ASUS Prime RTX 5070 Ti OC Edition, 304 mm (maker spec), at Best Buy, $1,299.99 before sales tax, shipping: not captured (a MIRROR listing, bid by a SIM seller; proof: `demo/tests/test_demo_winner.py`). Say "before sales tax" every time.

**One line:** Tech Bazaar is a buyer's agent for scarce, scam-prone goods, starting with computer gear. You give it a goal, seller agents bid for it, an advocate vetoes the traps with a source, and nothing is paid until you approve on a two-way voice call.

**Category:** a refereed arena for agent commerce.

**10 seconds:** Agents are starting to buy for us, and agents will be attacked. Tech Bazaar is a refereed arena for computer gear: sellers' agents bid for your goal, your advocate vetoes the traps, and nothing is paid until you say yes on a call.

**30 seconds:** An RTX 5070 Ti lists 49 percent over launch price (Capital & Compute citing Tom's Hardware, Sep 1 2026). You give the agent a goal: this card, under $1,300, in a case that takes 305 mm, by Friday. It hunts, and tells you after every step. Seller agents bid in a sealed round. Your advocate checks fit with code and every claim against the live page, and vetoes the cheapest bid when it is a trap, with the source. Above your allowance it calls you. You ask "why not the cheaper one?" and it answers aloud. Your spoken code signs that exact deal. Losing sellers get a loss report and the learner adjusts (a SIM stand-in). Bazaar Shield, our security API, is scored in the open: on 12 attacks written after we froze the rules it stopped 6 of 12 (`shield/corpus/RESULTS.md`, 2026-10-23). We say that number, not "secure". Everything on screen is labelled LIVE, MIRROR or SIM.

## The five beats (stage order)

1. Set a goal (typed in ASI:One on the Agentverse path; the stage run uses a scripted SIM goal; the rig Vidyut owns is a scripted SIM rig).
2. Sellers bid; the advocate vetoes a trap with a source (fit by code; origin badges on every bid).
3. Shield blocks an injected listing live. A "Hack the market" console for judges is planned, not built; a judge can send attacks to the Shield API or `shield-bench`.
4. The two-way call approves above the allowance (word-pair code, amount read back, replay fails).
5. The seller's loss report and learning (one deterministic strategy diff; the "what to change" line is a SIM template today, and Claude writing it is planned, not built).

Hyphenate is built (`hyphenate/`) and is an add-on, not a beat. The IT fleet view is planned, not built. Bright Data (`data/baselines/brightdata.py`), the CRS payee gate (`pay/crs_gate.py`) and Tiger Data (`data/tiger/store.py`) are built, env-gated and not run live (no key in the run). Do not claim any of them as live on stage.

## The multiverse line (say it exactly)

"This is one real order, Vidyut's. When many orders pool, this is what a seller sees. One or two bids here are real, the rest are labelled simulated." Never say "many buyers use it". The Lot Wall (Vidyut's gold REAL brick, the rest grey SIM, the price ladder, folded back to one brick) is planned, not built; cut this line unless it exists by the freeze.

## Sourced facts (only these)

- RTX 5090 $4,999 vs $1,999 launch; RTX 5070 Ti $1,119 vs $749 (+49 percent), Sep 1 2026 (Capital & Compute citing Tom's Hardware; tier 3).
- 32 GB DDR5 costs at least $375 (Tom's Hardware headline).
- PC gaming hardware $44.5B, up 35 percent in 2025 (Jon Peddie Research).
- Amazon shipped an RTX 5090 with the chip missing: REPORTED. Open the article before saying it on stage.
- Never a number for research time, incompatibility rate or return rate (none found). Never "Windows 10 now": support ended Oct 14 2025.

## Q&A answers to have ready

- **Why would a seller bid?** Our first sellers are marketplace, used, refurbisher and local PC shop sellers; big-box stores will not bid. The three seller agents on Agentverse are registered (`agents/README.md`), with SIM listings. A real non-agent seller side (a shop with no agent) is planned, not built.
- **Do real sellers really bid?** Not yet. No outside seller has bid. Every bid today comes from our agent: either on a real, dated store listing (MIRROR, with the link and floor) or a labelled SIM seller. LIVE is for an outside Agentverse agent. Every bid carries an origin badge: LIVE (an outside Agentverse agent; none has bid yet), MIRROR (our agent on a real listing, with the link and floor), SIM. If no real seller bids, the agent buys the best public listing and says so on the card.
- **What did you prove about seller learning?** Not much yet, and we say so: in our simulator the learner beat the field-median control on 1 of 4 held-out archetypes and the gate needs 2, so there is no headline lift (`sim/RESULTS-2026-10-24-b48x3.md`, 2026-10-24). It is a simulator we built, not the market. What is real: fit by code, the veto with sources, the call client and the approval judge, and the mandate gate. A teammate purchase is planned, not built (task d6, Sat 14:00 to 15:30), and a rehearsed live call is not recorded in this repo yet.
- **Who pays, and who are the incumbents?** Consumers are free. The first payer is the small IT buyer, priced per refresh (proposed, finalized later; monthly Team $49 and Business $199 are alternatives). Sellers pay 3 percent, minimum $1, capped at $25, only on a delivered sale that passed the receiving check. Incumbents (Amazon Business, CDW and Dell business stores do approvals and POs; none referees an agent-to-agent deal or argues against a bad deal): naming them on slides is finalized later; keep it in Q&A until then. All prices are proposals, not built.
- **Is it secure?** No, and we do not say that. Say "blocked X of Y on this corpus": dev 30 of 30 and 30 of 30 (in-sample, rules written against them), the frozen probe 6 of 10 (an upper bound, the author had read it), the post-freeze check 6 of 12 (`shield/corpus/RESULTS.md`, 2026-10-23). The adaptive set is planned, not built.
- **Can a cloned voice approve a buy?** No. The credential is a one-time code on the authenticated screen, bound to one mandate; a "yes" alone never approves, and a replay fails on screen.
- **Is it a chatbot?** No. The agent runs the hunt and calls you only above the allowance.
- **Why did Micro Center at $1,199.99 lose?** Its listing states no condition in our snapshot, so it cannot be ranked as new or open-box, and we do not guess one (`demo/out/sample-run.json` shows "Micro Center: unknown 1,199.99"; the winner is pinned in `demo/tests/test_demo_winner.py`).
- **Does a model decide the veto?** No. The advocate is code (`agents/advocate/checks.py`); Claude is optional for a seller's persona line and Shield's classifier (`shield/classifier.py`, off by default).
- **Do you use Bright Data, CRS or Tiger Data?** Built, env-gated, not run live (no key in the run): Bright Data (`data/baselines/brightdata.py`), the CRS payee gate (`pay/crs_gate.py`, nothing calls it before the charge yet) and Tiger Data (`data/tiger/store.py`). The demo runs without any of them.

Every clause must be built, or labelled SIM or planned, by the Sun 03:00 freeze; cut any clause that is not.
