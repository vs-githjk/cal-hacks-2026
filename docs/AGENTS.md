# AGENTS.md: shared memory for every coding agent on Tech Bazaar (teammates' Claude sessions included)
Read this first. Append what you learn at the bottom (one line, `[HH:MM] agent: fact | why it matters`). Never delete others' lines.

## Ground truth (read, do not re-derive)
- Product: Tech Bazaar, "the refereed arena for agent commerce". Security API: Bazaar Shield. Scope: all computer gear. Five beats: goal set; sellers bid + advocate vetoes a trap with source; Shield blocks an injected listing live; two-way call approves above allowance; losing seller gets loss report and learns.
- Decisions: (conductor file) (LOCKED wins; SUPERSEDED lines at the end override older ones). Idea: (conductor file) (rulings at top). Lane plans: repo docs/kickoff/*.md.
- Repo: github.com/vs-githjk/fish-market-nothing-fishy. Main clone (local path) (watcher uses it; do not leave it dirty). Lane D worktree (local path) (branch lane-d-pay-trust).
- Only Vidyut and the conductor push to main. Teammates use PRs. Squash-merge on reviewer PASS.
- Hub page: https://claude.ai/artifact/Hjrg6QgJ8FgdmkoEAaLCeU (source (conductor file)). Survey: https://claude.ai/artifact/Mn4FGTUteLBhUiDJSRTvad.
- Progress tracker: (conductor file) Review log: (conductor file)

## Conventions (every agent)
- Never Co-Authored-By. No secrets, no .env in git. No em or en dashes. Never "Visa settles" (Stripe test mode on a Visa test card + TAP-style signatures). Never call a real store a liar. Label everything LIVE, MIRROR or SIM.
- Contract change: one NEW file in docs/changes/<HHMM>-<lane>-<topic>.md. Board lines: docs/board/<lane>.md. Never append to docs/CHANGES.md or docs/BOARD.md (frozen).
- Python: use python3 (no `python` on PATH). Install nothing without Vidyut's OK. Spending (Apify runs, Twilio, purchases) needs Vidyut's OK; Apify and CRS credits are in hand.
- Lane B tests need node_modules that are not installed; say so rather than claiming green.

## Contracts on main (do not break)
- SpecCard (C), Mandate, VoiceApproval, Allowance (D; Allowance = per_purchase_limit, period_limit, period, spent_this_period, ladder_step).
- pay/: mandate_hash over deal_id, amount, currency, payee, tier_price, nonce, expires_at (sorted keys, no spaces). Merchant simulator must call pay.tap.verify_request with expected_mandate_hash; body carries the mandate under "mandate". Headers: Content-Digest, Mandate-Hash, Signature-Input, Signature.

## Gotchas found in reviews (learn from these)
- [22:07] Writes outside try after a paid API call lose the run; create output dirs first (C run_actors).
- [22:11] Security checks must be required args, not optional; fail closed when a binding is missing (D can_charge, verify_request).
- [22:20] Every SpacetimeDB reducer that moves money or judges bids must check the caller identity (B).
- [22:20] Validate numeric inputs (quantity > 0, finite) before ranking (B).
- [22:05] Reformatting a shared schema file causes needless conflicts; change only the lines you need.

## Log
- [22:24] C agent: amd.com blocks scripted fetches (timeouts); when only third-party numbers disagree, leave the spec value out so the checker says uncertain | a wrong table value becomes a false OK
- [22:30] C agent: maker infosheets go stale (NH-D15 165 vs 168 mm on the current spec page); read the current spec page, and a case's clearance can change with panel or radiator (NR200P 155 mesh vs 153 glass) | a 3 mm gap flips a fit verdict

## Seller model (LOCKED Fri 22:36)
One seller agent per SELLER OF RECORD: whoever takes the money and ships. Amazon selling directly is one agent; each third-party merchant on Amazon is its own agent; Newegg, a local shop, a brand's own store are each one agent. One agent may bid several condition lines (new, open-box, refurbished, bundle) for the same SKU inside one sealed bid. Every listing normalizes to one canonical SKU (MPN or UPC) in SpecCard. The advocate ranks on quality-adjusted landed price (condition, warranty, returns, seller record); the buyer's goal sets which conditions are allowed. Manufacturers bid only when they sell direct.

## Your work queue is GitHub Issues (from Fri 22:45)
Every coding agent: at the start of each session and after each finished task, run
`gh issue list --assignee @me --state open` (or `--assignee <your GitHub login>`), then work the highest priority first (label p0 before p1).
- One issue = one task with a done-check. Branch from main, open a PR whose body says `Closes #<issue>`.
- Review results that need fixes come back as new issues labelled `fix` assigned to you. Do those first.
- Blocked? Comment on the issue with what you need; do not wait silently.
- GitHub logins: Abhinav = Abh-129 (lane-a), Vedant = vedantshirvi (lane-b), Anoop = AnoopIbrampur (lane-c), Vidyut = vs-githjk (lane-d).
- [23:28] lane-d hyphenate: a lowest-price MIRROR reference was fooled by data/mirror ebay_sold snapshots ($640 for a $1,250 card, sold history not asking price); use the median of retail listings and skip *sold* files | any price check built on snapshots must exclude sold-history
- [10:45] lane-d builder: the mandate hash now binds buyer_id (#186, docs/changes/1041-D-mandate-hash-buyer-id.md); always hash through pay.mandate.mandate_hash, never by hand | a hand-rolled hash of the old 7 fields gives hash_mismatch
- [14:30] lane-c readiness Actor: seller_report's fit.length_unknown and fit.power_unknown fire when OUR maker tables lack a model, even when the title names it exactly (MSI Shadow 3X) | never show a seller a finding that is our data gap; check what the page owner controls (mpn, gtin, sku)
- [14:52] lane-c #317: a regex like <script[^>]+X[^>]*>(.*?)</script> is cubic on '<script x X' * N (58 KB took 25 s); scan scripts with str.find from where the last match ended (data.claim_check.script_blocks), and validate JSON-LD values by type (price [1] read as 1.0, '1.749,99' as 1.749) | an attacker page can hang a run or read as ready
- [15:38] lane-c readiness Actor: apify push skips every .gitignored file, so a bundle kept out of git (src/data/) never reached the build (ModuleNotFoundError); add an .actorignore with !src/data/**/*.py lines (apify-cli force-includes them) | a green local test says nothing about what push uploaded
- [16:24] lane-c #353: http.client's getresponse() calls conn.close() for every will_close response (Connection: close, HTTP/1.0, no length); a custom makefile() that reads the raw socket then hits Errno 9 | hold a socket reference (sock._io_refs, as socket.makefile does) and test with a real local http.server, not a hand-written byte stream
- [15:36] lane-c advocate: a brand only the seller names (no brand in the SKU spec, listing URL not in our rows) is unconfirmed; the recall card gets an advocate.recall_unverified note, never "No problems found" (#330) | never let a seller field be the sole input to a safety lookup
- [16:20] lane-c #355: the advocate baseline lapses 24 h after the newest retail ask (and earlier if an owner drops under 2 prices); run `python3 -m data.baselines.refresh --dry-run` to see when, `--yes-spend` to re-scrape (Apify credits) | a lapsed baseline turns every card into 'Some checks could not run'
- [13:54] lane-a web: `npm test --prefix web` needs Node 22.18+ (CI uses 24) because it runs .ts directly; Node 20 fails with "Cannot use import statement". The public `round` row carries `need_id` only and the `need` table (with goal_id) is not exposed, so the client cannot join a goal to its round exactly | the buyer app must not show the latest public round as "this search's offers" until a buyer-scoped projection with goal_id exists
- [13:54] lane-a web: `npm install` on Node 20 rewrites web/package-lock.json (drops the "libc" fields); `git checkout -- web/package-lock.json` before committing, and run lint/build under Node 24. Lint already reports pre-existing react/no-unescaped-entities errors in buyer.tsx, market.tsx, screens.tsx and setState-in-effect in floor/page.tsx | a red lint on main is not from your change; do not mix those fixes into an unrelated PR
- [13:54] lane-a web: the real /v1/memory producer (demo/memory.py) writes seller lessons with an empty buyer_id and an empty what_to_change, and purchases/goals with the buyer id (market vetoes from from_market also have an empty buyer_id); the feed is not buyer scoped on the server. web/src/lib/memory.ts shows a lesson or veto with no buyer id to any paired buyer (buyer_id === "" means "not tied to a buyer") and hides every other row with no buyer id | do not filter the whole feed by buyer_id or Decisions loses every lesson
- [14:06] lane-a web: the agent feed stamps `at` only on the newest agent's last line, so most /v1/agents rows have at null and carry no avatar field; the Fetch tile picks "latest" by the newest valid ISO time (latestActivity), never by array position, and shows a placeholder initial for a missing avatar. Status words describe the launcher run log ("Mailbox running"), not verified online liveness | do not label an address or a published Agentverse profile as online
- [14:17] lane-a web: the web app has NO confirmed command that starts the buyer agent: market post_goal is called only by demo/bridge.py and the stage runner (nothing wakes the buyer on it), and agents/buyer/web_chat.py is an unauthenticated loopback chat proxy that returns reply text, not a goal id. lib/goalRequest.ts keeps GOAL_COMMAND and SPEECH_TRANSPORT null (BLOCKED) and the composer sends the buyer's exact words to ASI:One instead | wire GOAL_COMMAND only to an authenticated command that answers with a persisted goal id; never treat a market goal row as a started hunt
- [14:17] lane-a web: node --test runs lib/*.ts with type stripping only: no constructor parameter properties (`constructor(readonly x)`), enums or namespaces in any lib file a test imports | the suite fails to load, not just one test
- [15:36] lane-c recall: in a recall checker only a model, a plain 4+ digit line or a product word may earn "none"; sizes, years and spec words (3-in-1, 2-pack, USB3.0, Qi2) must stay weak, and every UPC field (input too) is split per code | a capacity or a spec word once flipped a real lead to none (#331)
- [16:00] C agent: Shield with classifier=None still flags (quarantine, shield.classifier.unavailable) a seller sentence that names a secret with a state/tell/give verb, e.g. "BIOS password removed, comes with the PIN sticker" | a rules-only packaging of Shield must explain that flag, it is fail closed, not a finding
- [14:58] C agent: Shield's shield.encoded.payload quarantines a bid that carries a mixed-case URL path (e.g. msi.com/Graphics-Card/GeForce-RTX-...); keep maker source URLs out of bid attrs and screen any new bid shape with shield.core.screen in a test | a real bid otherwise never reaches the round
- [15:45] C agent: a MIRROR bid for a real store that never joined (data/mirror/not_partners.py) must be refused on every money path, not just vetoed: advocate veto, hunt.pick_best, eligible_for_order, conclude and on_requote, before any address lookup | a KeyError from common.address is not a guard, it is luck (#333)
- [18:20] lane-d build: demo/build_sim.py is the in-memory market for the build dry run and its tests (it also has #363 knockout stages); the default demo catalog traps the cheapest SIM board (LGA1700), so a build on it has seven needs and a re-plan, and a test that wants six passes trap=False | never count needs on default_catalog without deciding about the trap
