# Morning merge kit (08:00 Sat Oct 24)

Who merges: the main session and Vidyut (builders never merge or push). What this page gives you: the order, a dry run of that order
with its time, and the fix rule for each conflict. Squash-merge on reviewer PASS as usual.

## The dry run

Taken Sat Oct 24 04:22 PDT with `scripts/merge_dryrun.sh` (git 2.39.3, `git merge-tree --write-tree`). It never moves a ref,
HEAD, the index or the working tree. Base `origin/main` at 7695b77 (it moved at 04:16:55, when #153 and #152 were squash-merged,
so the first 04:16 table on base 1ae78d4 is replaced by this one). Each step merges one branch onto the RUNNING result of the
steps above it. lane-d-night2 is step 1 because `demo/rehearse.py` (T3) lives on it and the per-merge rehearsal below needs it.

| Step | Branch (PR) | Tip | Alone on main | Conflicts onto the running result |
|---|---|---|---|---|
| 1 | lane-d-night2 (this run) | tip at merge time | clean | clean |
| 2 | origin/lane-c-118-snapshot-refresh (#122) | f113d29 | clean | clean |
| 3 | origin/lane-c-125-power-fit (#130) | cb7b158 | clean | docs/board/C.md |
| 4 | origin/lane-c-127-recalls (#133) | 2b3ccc0 | clean | docs/board/C.md |
| 5 | origin/lane-c-c14-three-way-match (#137) | 9f52ac5 | clean | data/scoreboard.json |
| 6 | origin/lane-c-136-history-source (#147) | 8f5d1ec | clean | data/scoreboard.json, docs/board/C.md |
| 7 | origin/lane-c-141-price-position (#148) | c4b3f4d | clean | data/scoreboard.json, docs/board/C.md |
| 8 | origin/lane-c-140-real-catch (#149, stacked on #147) | 1d9c41d | clean | data/scoreboard.json, docs/board/C.md |
| 9 | origin/claude/94-status-line (#111) | 2ef95b9 | clean | clean |
| 10 | origin/lane-b-market-floor (#71) | 5487b6d | clean | clean |
| 11 | lane-d-night (run 1, still building) | 3cea366 | clean | market/spacetimedb/src/{index.ts,market.test.ts,schema.ts}, web/src/module_bindings/{index.ts,types.ts,types/reducers.ts} |

What "clean" means: no text conflict, nothing more. A clean merge can still be a red test, because two branches can each pass alone
and fail together. Check that at every real merge: run the plan's Python test command on the dry-run tree before you merge. Get the tree
with `git archive <tree>` into a temp dir (`git merge-tree --write-tree <running-result> <branch>` prints the tree id):

```
T=$(git merge-tree --write-tree origin/main lane-d-night2)
D=$(mktemp -d) && git archive $T | tar -x -C $D && (cd $D && python3 -m pytest pay demo shield sim hyphenate data scripts -q)
```

Known red, fixed by step 1 itself: on the 04:22 tree, `demo/tests/test_demo_winner.py::test_b_a_too_long_listing_that_does_bid_is_vetoed_citing_the_maker_spec`
failed (885 passed, 1 failed) because main #121 (35ee929) closed the advocate warning text to a rule template and the test still wanted
`342 mm exceeds case clearance 305 mm` inside it. lane-d-night2 now carries the fix (commit 8ad798c: the test reads the numbers from the card's
fit checks and the warning text only from the template). Re-run on the same tree after that fix: 886 passed, 0 failed. If a later main
change moves that text again, the same command will show it before you merge.

Summary: 7 of 11 steps conflict. Every branch is clean alone on main, so none of these is a bug in a branch; they are overlaps
between branches. The Lane C PRs overlap on docs/board/C.md and data/scoreboard.json. Step 11 is the one real code overlap:
lane-d-night against #71 (the same 6 files with only #71 before it).

lane-d-night keeps committing until about 07:00, so its tip will have moved. Re-run before you merge (it takes seconds, read
only, from any checkout of the repo):

```
git fetch origin
bash scripts/merge_dryrun.sh origin/main lane-d-night2 origin/lane-c-118-snapshot-refresh origin/lane-c-125-power-fit origin/lane-c-127-recalls origin/lane-c-c14-three-way-match origin/lane-c-136-history-source origin/lane-c-141-price-position origin/lane-c-140-real-catch origin/claude/94-status-line origin/lane-b-market-floor lane-d-night
```

Build the branch list from `gh pr list --state open` at re-run time, not from this page. A squash-merged branch (#152 and #153
were) is not an ancestor of main, so the script cannot see it as already contained: it shows up as a false CONFLICT row, and it
also makes later steps conflict that would be clean. Drop any branch whose PR is closed. Anything opened after 04:22 (PRs #102,
#104, #105, #107 and the Abhinav #15 branch from the plan are not open or not pushed now) goes on the end of the command, or
earlier if it is Lane C data. A conflicted step keeps its conflict markers in the running result, so a later step on the same
file reports it again; read each path's first row as the real overlap.

## Recommended order

Demo path first: lane-d-night2 (it carries the rehearsal tool), then Lane C data PRs, then Lane A's status parser, then #71,
then lane-d-night.

1. lane-d-night2. It has no text conflict onto main or under any later step, its Python tests pass on the merged tree (886 passed, see
   above), and after it `demo/rehearse.py` exists on main.
2. Lane C data PRs in the order of rows 2 to 8. Merge the stacked pair #147 then #149 in that order. The reviewer rule from the
   board (22:26): stacked PRs conflict after a squash, so rebase each on main first, or merge with a merge commit.
3. #111 (Lane A parse_line), then #71 (Lane B). Both merged clean at 04:22.
4. lane-d-night, resolving step 11 below.

## Fix rules for the conflicts

- docs/board/C.md (step 3 onward): every Lane C PR appends one line. Keep both sides, in PR order. Never drop a line.
- data/scoreboard.json (steps 5 to 8): a generated file, `python3 -m data.scoreboard` rewrites it from its sources. After each
  merge regenerate it and commit the result instead of hand-merging JSON. Not run tonight (it writes the tracked file), so check
  that the run is offline and that the tiles still match the numbers the PRs quote.
- market/spacetimedb/src/{schema.ts,index.ts,market.test.ts} (step 11): lane-d-night adds tables and reducers (stock_hold,
  set_allowance, deny_approval) and #71 adds its own (agent_event, buyer profile, loss reports, approvals). Keep both
  sides' additions, edit no line you do not have to (22:05 board rule: reformatting a shared schema file only makes conflicts), then run
  `npm test --prefix market`.
- Regenerate the bindings, never hand-merge them (web/src/module_bindings/**): after the schema and reducers compile, run
  `spacetime generate --lang typescript --out-dir ../web/src/module_bindings --module-path ./spacetimedb` from `market/`
  (the command in market/README.md). The generator works offline. Take the whole generated folder, then `npm run typecheck --prefix market`
  and the web tsc line of the test command in `.night/plan.md`. Every state change a reducer makes writes a floor event, so a new reducer
  can move the pinned event-order test: read that failure before editing the test.

- web/public/lot.json (any step that changes `sim/wind_tunnel.py` ARCHETYPES, and again after the last merge): a generated file the lot
  tests pin to its generator (`sim/tests/test_lot_wall.py::test_committed_lot_json_matches_the_generator`). Main's 400cd51 added two
  archetypes, so a branch whose lot.json was built before it passes alone and turns main red after the merge (1 failed, 1061 passed
  in the reviewer's scratch merge). After the merge run `python3 -m sim.lot_wall` from the repo root (it rewrites `web/public/lot.json`
  offline, seed 7), then `python3 -m pytest sim/tests/test_lot_wall.py -q` (8 passed) and commit the new file. lane-d-night already
  carries the regenerated file as of its whole-branch fix round (9938995), so this step matters when main moves again.

## One window, not two (LOCKED 02:08)

AgentsTile (#71, SpacetimeDB `agent_event`) and the Lane D AgentPip (:8790 feed) both exist and share no file. Rule: mount ONE window.
AgentPip stays the shell and is fed by `agent_event`; remove the AgentsTile per-page mounts at merge. The :8790 feed stays as a labelled
fallback source. Not built yet, so it comes after the merges (morning task M2 in `.night/plan.md`, test first).

## After the merges, the morning tasks that need the merged code

M1 agent_feed uses `agents.status.parse_line` (needs #111 and lane-d-night), M2 the one window above (needs #71), M3 Seller Kit calls the
CRS check, M4 the bridge reads beat 4's `recheck` key, M5 `demo/sellers.py load_offers()` keeps the newest snapshot per retailer
prefix so the #122 refresh reaches the demo (board 02:47). Specs for M1 to M4 are in `.night/plan.md` under "Morning tasks".

## Re-run the skeleton after each merge

`demo/rehearse.py` arrives with lane-d-night2, step 1. Merge that first, pull main into the bidding-royale checkout that runs the
stack, then after EVERY later merge step (not only the last one) run from that checkout:

```
python3 demo/rehearse.py --runs 1
```

Details and the full 08:00 command are in `docs/REHEARSAL.md`. A run resets the demo tables, so do not run it while someone is
watching /buyer or /market. After a merge that touches `market/spacetimedb/**` (#71, in step 3 of the order above, and lane-d-night, step 4) the running
stack still has the module published at `launch up`, so republish it and re-load the roles BEFORE `rehearse.py`:

```
cd market && spacetime publish -s http://127.0.0.1:3000 -p ./spacetimedb --yes=all tech-bazaar && cd .. && python3 market/scripts/setup_roles.py
```

(or restart the launcher's market service, which does both). A stale module is the usual red after lane-d-night: the bridge calls the
referee reducer `set_allowance`, the old module does not have it (0 matches on origin/main), `market/scripts/stdb.py` raises on the
non-200 reply and `bridge.py` returns 1. A `<reducer> failed (4xx/5xx)` error that names a reducer the merge added means the module is
stale, not that the merge is bad, so it is not a reason to revert: republish and run again. If a stage still fails after a republish,
that merge is the likely cause: revert it before merging the next one. A missing script (`No such file` for `demo/rehearse.py`) is not a stage failure and never a reason to revert: it means
lane-d-night2 is not merged yet. Until it is, use the interim check, which is what rehearse runs underneath:

```
python3 demo/bridge.py --reset --rounds 2 --step-delay 1
```
