# AGENTS.md: shared memory for every coding agent on Tech Bazaar (teammates' Claude sessions included)
Read this first. Append what you learn at the bottom (one line, `[HH:MM] agent: fact | why it matters`). Never delete others' lines.

## Ground truth (read, do not re-derive)
- Product: Tech Bazaar, "the refereed arena for agent commerce". Security API: Bazaar Shield. Scope: all computer gear. Five beats: goal set; sellers bid + advocate vetoes a trap with source; Shield blocks an injected listing live; two-way call approves above allowance; losing seller gets loss report and learns.
- Decisions: (conductor file) (LOCKED wins; SUPERSEDED lines at the end override older ones). Idea: (conductor file) (rulings at top). Lane plans: repo docs/kickoff/*.md.
- Repo: github.com/vs-githjk/cal-hacks-2026. Main clone (local path) (watcher uses it; do not leave it dirty). Lane D worktree (local path) (branch lane-d-pay-trust).
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
