# Agent avatars (#259)

One theme for every Tech Bazaar agent: a navy tile, the agent's colour ring and its initials. The caller (the agent
that places the approval phone call) is the one pink tile. Made by `python3 -m scripts.make_avatars` (stdlib only).

| File | Agent |
|---|---|
| buyer.png | Tech Bazaar Buyer (@techbazaarbuyer) |
| advocate.png | Bazaar Advocate (@techbazaaradvocate) |
| shield.png | Bazaar Shield (@techbazaarshield) |
| caller.png | Bazaar Caller (@techbazaarcaller) |
| seller_1.png ... seller_5.png | the five seller agents (@techbazaarseller1 ... 5) |

Each agent publishes its own avatar. `common.agent_args` sets `avatar_url` to this folder's PNG on the public repo
(`https://raw.githubusercontent.com/vs-githjk/cal-hacks-2026/main/agents/avatars/<role>.png`), and uAgents sends it to
Agentverse with the name and README when the agent connects (`publish_agent_details=True`). A restart of a mailbox
agent is enough; the address does not change, because it comes from the agent's seed. Set `AGENT_AVATAR_BASE` to serve
the images from another host.

If an avatar does not show after a restart, upload it by hand: sign in at agentverse.ai, open **Agents**, open the
agent (match the address in agents/README.md), choose **Edit profile**, then **Upload image**, and pick the PNG here.
