# Tech Bazaar: rules for every coding agent in this repo

Read first: docs/kickoff/00-shared.md (product, invariants, contracts, red-team amendments), then your lane prompt in docs/kickoff/ (A-agents, B-market-floor, C-data-truth, D-pay-trust).

- Work only in your lane's folders and your lane branch; touch other folders only through contracts/ (note any contract change in a new file in docs/changes/ (`<HHMM>-<lane>-<topic>.md`)).
- Never add a Co-Authored-By line or any Claude or AI attribution to commits or PRs.
- Never commit secrets. Env var names go in .env.example; values stay in your local .env (gitignored).
- Test first for logic: auction rules, Shield, ledger, claim checks, the fit checker.
- Small commits, PR into main, main always runs. Post progress and asks as one line in docs/board/<your lane>.md.
- Sandbox and test identities only. Label anything simulated (LIVE, MIRROR, SIM).
- No em dashes or en dashes in user-facing text.
- Every coding agent: read docs/AGENTS.md first (shared conventions and gotchas from reviews); append what you learn at the bottom.

## Your work queue is GitHub Issues (from Fri 22:45)
Every coding agent: at the start of each session and after each finished task, run
`gh issue list --assignee @me --state open` (or `--assignee <your GitHub login>`), then work the highest priority first (label p0 before p1).
- One issue = one task with a done-check. Branch from main, open a PR whose body says `Closes #<issue>`.
- Review results that need fixes come back as new issues labelled `fix` assigned to you. Do those first.
- Blocked? Comment on the issue with what you need; do not wait silently.
- GitHub logins: Abhinav = Abh-129 (lane-a), Vedant = vedantshirvi (lane-b), Anoop = AnoopIbrampur (lane-c), Vidyut = vs-githjk (lane-d).
