# Bidding Royale: rules for every coding agent in this repo

Read first: docs/kickoff/00-shared.md (product, invariants, contracts, red-team amendments), then your lane prompt in docs/kickoff/ (A-agents, B-market-floor, C-data-truth, D-pay-trust).

- Work only in your lane's folders and your lane branch; touch other folders only through contracts/ (note any contract change in docs/CHANGES.md).
- Never add a Co-Authored-By line or any Claude or AI attribution to commits or PRs.
- Never commit secrets. Env var names go in .env.example; values stay in your local .env (gitignored).
- Test first for logic: auction rules, Shield, ledger, claim checks, the usage forecast.
- Small commits, PR into main, main always runs. Post progress and asks as one line in docs/BOARD.md.
- Sandbox and test identities only. Label anything simulated (LIVE, MIRROR, SIM).
- No em dashes or en dashes in user-facing text.
