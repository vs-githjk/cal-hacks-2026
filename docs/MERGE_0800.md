# Morning merge kit (08:00 Sat Oct 24)

Who merges: the main session and Vidyut (builders never merge or push). What this page gives you: the order, a dry run of that order
with its time, and the fix rule for each conflict. Squash-merge on reviewer PASS as usual.

## The dry run

Taken Sat Oct 24 04:16 PDT with `scripts/merge_dryrun.sh` (git 2.39.3, `git merge-tree --write-tree`). It never moves a ref,
HEAD, the index or the working tree; the ref list was byte-identical before and after. Base `origin/main` at 1ae78d4.
Each step merges one branch onto the RUNNING result of the steps above it.

| Step | Branch (PR) | Tip | Alone on main | Conflicts onto the running result |
|---|---|---|---|---|
| 1 | origin/lane-c-118-snapshot-refresh (#122) | 5b053fa | clean | clean |
| 2 | origin/lane-c-125-power-fit (#130) | cb7b158 | clean | docs/board/C.md |
| 3 | origin/lane-c-127-recalls (#133) | 2b3ccc0 | clean | docs/board/C.md |
| 4 | origin/lane-c-c14-three-way-match (#137) | b299651 | clean | data/scoreboard.json |
| 5 | origin/lane-c-136-history-source (#147) | 1c3b227 | clean | data/scoreboard.json, docs/board/C.md |
| 6 | origin/lane-c-141-price-position (#148) | 7684a69 | clean | data/scoreboard.json, docs/board/C.md |
| 7 | origin/lane-c-140-real-catch (#149, stacked on #147) | 0b70ecd | clean | data/scoreboard.json, docs/board/C.md |
| 8 | origin/lane-c-c15-timeseries (#153) | 967a8ab | clean | data/scoreboard.json, docs/board/C.md |
| 9 | origin/lane-c-scoreboard-stale-voice (#152) | 95bcb03 | clean | data/scoreboard.json, data/tests/test_scoreboard.py, docs/board/C.md |
| 10 | origin/claude/94-status-line (#111) | 2ef95b9 | clean | clean |
| 11 | origin/lane-b-market-floor (#71) | 5487b6d | clean | clean |
| 12 | lane-d-night (run 1, still building) | 51aee81 | clean | market/spacetimedb/src/{index.ts,market.test.ts,schema.ts}, web/src/module_bindings/{index.ts,types.ts,types/reducers.ts} |
| 13 | lane-d-night2 (this run) | 32c7f0b | clean | clean |

Summary: 9 of 13 steps conflict. Every branch is clean alone on main, so none of these is a bug in a branch; they are overlaps
between branches. Step 12 stays the same with only #71 before it (1 of 3 steps conflict), so the cause is #71 against lane-d-night.
lane-d-night then lane-d-night2 directly on main is 0 of 2.

lane-d-night is ahead of main by 29 commits and run 1 keeps committing until about 07:00, so its tip will have moved. Re-run
before you merge (it takes seconds, read only, from any checkout of the repo):

```
git fetch origin
bash scripts/merge_dryrun.sh origin/main origin/lane-c-118-snapshot-refresh origin/lane-c-125-power-fit origin/lane-c-127-recalls origin/lane-c-c14-three-way-match origin/lane-c-136-history-source origin/lane-c-141-price-position origin/lane-c-140-real-catch origin/lane-c-c15-timeseries origin/lane-c-scoreboard-stale-voice origin/claude/94-status-line origin/lane-b-market-floor lane-d-night lane-d-night2
```

The PR list above is the open set at 04:16 (`gh pr list`). Anything opened later (PRs #102, #104, #105, #107 and the Abhinav #15
branch from the plan are not open or not pushed now) goes on the end of the command, or earlier if it is Lane C data.
A conflicted step keeps its conflict markers in the running result, so a later step on the same file reports it again; read each
path's first row as the real overlap.

## Recommended order

Demo path first: Lane C data PRs, then Lane A's status parser, then #71, then lane-d-night, then lane-d-night2.

1. Lane C data PRs in the order of rows 1 to 9. Merge the stacked pair #147 then #149 in that order. The reviewer rule from the
   board (22:26): stacked PRs conflict after a squash, so rebase each on main first, or merge with a merge commit.
2. #111 (Lane A parse_line), then #71 (Lane B). Both merged clean at 04:16.
3. lane-d-night, resolving step 12 below.
4. lane-d-night2 (clean on top of lane-d-night in the dry run).

## Fix rules for the conflicts

- docs/board/C.md (step 2 onward): every Lane C PR appends one line. Keep both sides, in PR order. Never drop a line.
- data/scoreboard.json (steps 4 to 9): a generated file, `python3 -m data.scoreboard` rewrites it from its sources. After each
  merge regenerate it and commit the result instead of hand-merging JSON. Not run tonight (it writes the tracked file), so check
  that the run is offline and that the tiles still match the numbers the PRs quote.
- data/tests/test_scoreboard.py (step 9, #152): read both sides; the stale-voice text change and the earlier tile tests must both stay.
- market/spacetimedb/src/{schema.ts,index.ts,market.test.ts} (step 12): lane-d-night adds tables and reducers (stock_hold,
  set_allowance, deny_approval) and #71 adds its own (agent_event, buyer profile, loss reports, approvals). Keep both
  sides' additions, edit no line you do not have to (22:05 board rule: reformatting a shared schema file only makes conflicts), then run
  `npm test --prefix market`.
- Regenerate the bindings, never hand-merge them (web/src/module_bindings/**): after the schema and reducers compile, run
  `spacetime generate --lang typescript --out-dir ../web/src/module_bindings --module-path ./spacetimedb` from `market/`
  (the command in market/README.md). The generator works offline. Take the whole generated folder, then `npm run typecheck --prefix market`
  and the web tsc line of the test command in `.night/plan.md`. Every state change a reducer makes writes a floor event, so a new reducer
  can move the pinned event-order test: read that failure before editing the test.

## One window, not two (LOCKED 02:08)

AgentsTile (#71, SpacetimeDB `agent_event`) and the Lane D AgentPip (:8790 feed) both exist and share no file. Rule: mount ONE window.
AgentPip stays the shell and is fed by `agent_event`; remove the AgentsTile per-page mounts at merge. The :8790 feed stays as a labelled
fallback source. Not built yet, so it comes after the merges (morning task M2 in `.night/plan.md`, test first).

## After the merges, the morning tasks that need the merged code

M1 agent_feed uses `agents.status.parse_line` (needs #111 and lane-d-night), M2 the one window above (needs #71), M3 Seller Kit calls the
CRS check, M4 the bridge reads beat 4's `recheck` key, M5 `demo/sellers.py load_offers()` keeps the newest snapshot per retailer
prefix so the #122 refresh reaches the demo (board 02:47). Specs for M1 to M4 are in `.night/plan.md` under "Morning tasks".

## Re-run the skeleton after each merge

After EVERY merge step (not only the last one) run, from the bidding-royale checkout that runs the stack:

```
python3 demo/rehearse.py --runs 1
```

Details and the full 08:00 command are in `docs/REHEARSAL.md`. A run resets the demo tables, so do not run it while someone is
watching /buyer or /market. If a run fails after a merge, that merge is the cause: revert it before merging the next one.
