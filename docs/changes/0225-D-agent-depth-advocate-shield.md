# Agent depth: the Advocate and Smell Test (Lane D, Sun Oct 25)

No contract file changed. Additive only; nothing a reader of the old shapes needs to change.

**AdvocateCard** (contracts/AdvocateCard.schema.json allows extra keys): each card now also carries `explanation` (one sentence) and
`explanation_source_url`, `tco` ({rank, landed, all_in, tco, components, missing, thin_record}; `rank` is null for a vetoed bid; `all_in` is landed plus expected risk costs and never below landed, `tco` is the effective cost after warranty and returns value and is the figure bids rank on), `worth_it_note`,
and, only when a seller was asked a question, `clarification` ({status, question, condition, answer_excerpt, answered_at, seller}).
New warning kinds: `seller_confirmed` (a caution) and `unverified_veto` (a veto, rule id `advocate.unverified`, whose spoken summary is the
existing "Some checks could not run"). `checks.advise` gained two optional arguments, `clarifications` and `track`; with neither, its output
is the old output plus the new fields. The recommendation order and `best_bid` are unchanged: total cost is advisory.

**Chat protocol**: the Advocate sends a seller one `ChatMessage` question only when a listing page leaves the condition open, and reads that
seller's next chat message as the answer (screened by Smell Test first). A seller that only replies with its profile text is silent.

**common.py**: `include_profile_chat` takes two optional hooks, `answer` and `intercept`, and `screen()` now passes every Shield result
through the shared quarantine list (`agents/smell_memory.py`). The list is a local file (`SMELL_QUARANTINE_FILE`, default
`~/.bazaar-shield/quarantine.json`, mode 600, 6 hours, 200 entries), not a market table, so there is no schema change. A hit only adds a
quarantine to an allow (rule id `shield.quarantine.seen`); the buyer's own side is exempt; any disk error leaves Shield's verdict as is.

**Model use**: `agents/phrasing.py` (claude-haiku-5-5, 3 s hard deadline, `PHRASING_LLM=0` turns it off) may reword one explanation or reason
sentence. It must keep every number and decision word and add no link; otherwise the code's own sentence is used. It never sees seller text
and decides nothing.
