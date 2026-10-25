# Seller skill: set up a seller agent from one Claude conversation

The skill `tech-bazaar-seller` lets a PC shop owner talk to Claude, answer a few questions, and end up with a seller agent config written by the Seller Kit. Every shop made this way is SIM (simulated): the kit cannot verify a real shop, so it refuses origin LIVE.

## What it does

1. Interviews the owner: store, what they sell, cost or price, the lowest price (floor) per condition, returns policy.
2. Writes an answers file and runs `seller_kit_client.py` (standard library only), which builds a SellerConfig and posts it to the Seller Kit API on `http://127.0.0.1:8791`.
3. Prints the config path and the command that starts the agent. It does not start the agent.
4. Explains sealed rounds, the floor, loss reports and the proposed fee (3 percent on a verified, delivered sale, capped at $25; a proposal, not locked).

The model is not the guard. The Seller Kit API refuses a negative floor, a floor above the price, an unknown condition, a link that is not http or https, NaN and more, with one field error per problem, and writes nothing. The client passes every value through untouched so the refusal is what the owner sees.

## Install in Claude Code

The repository is also a plugin marketplace (`.claude-plugin/marketplace.json`).

```
/plugin marketplace add vs-githjk/fish-market-nothing-fishy
/plugin install tech-bazaar-seller@tech-bazaar
```

Then say "I want to sell on Tech Bazaar" or run `/tech-bazaar-seller:tech-bazaar-seller`. The Seller Kit must be running on the same machine (`python3 scripts/launch.py up` starts it as the `seller-kit` service). If it is not, the client says "The Seller Kit is not running at ... Nothing was saved" and exits with code 2.

Install from a local checkout instead: `/plugin marketplace add /path/to/fish-market-nothing-fishy`.

The plugin loads one skill only. `plugin.json` sets `"agents": []` because this repo's `agents/` folder holds Fetch agent code and notes, which Claude Code would otherwise register as subagents.

## Upload to claude.ai

Zip the `tech-bazaar-seller` folder so the folder itself is the root of the zip (`tech-bazaar-seller/SKILL.md` inside), then add it under Settings, Capabilities, Skills.

```
cd .claude/skills && zip -r tech-bazaar-seller.zip tech-bazaar-seller
```

Limit: claude.ai cannot reach `127.0.0.1` on the owner's machine, so there the skill can run the interview and `--dry-run` (it prints the SellerConfig), but cannot post it. Posting works from Claude Code on the machine that runs the kit. This upload path was not tested here.

## Check it yourself

- Client and packaging tests: `python3 -m pytest skills_tests -q` (fake transport, plus the real Seller Kit app in process).
- Manual: `python3 .claude/skills/tech-bazaar-seller/seller_kit_client.py answers.json --dry-run` prints the config; with the kit up, drop `--dry-run`.
- Manifest: `claude plugin validate .` (warnings only: the validator also scans this repo's markdown files).

## Not verified

- The plugin install was run against a local checkout in an isolated Claude config folder (enabled, 1 skill, 0 agents), not from GitHub, because nothing is pushed.
- Claude's own behavior in the interview (whether it asks every question) is not covered by a test; only the client and the kit's refusals are.
