# Agent avatars (#259)

One theme for every Tech Bazaar agent: a navy tile, the agent's colour ring and its initials. The caller (the agent
that places the approval phone call) is the one pink tile. Made by `python3 -m scripts.make_avatars` (stdlib only).

| File | Agent |
|---|---|
| buyer.png | Tech Bazaar Buyer (@techbazaarbuyer) |
| advocate.png | Tech Bazaar Quality Advocate (@techbazaaradvocate) |
| shield.png | Tech Bazaar Shield Client (@techbazaarshield) |
| caller.png | Bazaar Caller (@techbazaarcaller) |
| seller_1.png ... seller_5.png | the five seller agents (@techbazaarseller1 ... 5) |

Agentverse has no upload API for avatars, so Vidyut uploads them by hand:
1. Sign in at agentverse.ai and open **Agents**.
2. Open the agent (match the address in agents/README.md).
3. Click the avatar or **Edit profile**, choose **Upload image**, and pick the PNG from this folder.
4. Save. Repeat for each agent. The address does not change: it comes from the agent's seed, not its name or picture.
