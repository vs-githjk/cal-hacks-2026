# Lane A launcher draft: Shield client and explicit local mode

Status: isolated draft based on accepted Lane A integration commit `080bcd5`. D reconciliation and owner review are required before publication or runtime use.

The launcher draft adds the existing Shield client entrypoint as `shield-client` on its registered port 8004, in the existing `agents` group with TCP health. Agent child environments explicitly set `AGENTS_MAILBOX` and the relevant role flag to `1` for mailbox mode or an empty string for local mode. Empty strings are deliberate: `common.agent_args` treats any nonempty value as mailbox mode, and the `.env` loader uses `setdefault`. Existing seed checks remain unchanged.

The focused tests exercise the real `common.agent_args` function using synthetic dotenv content and fake seeds, including refusal of the public Shield development seed. No private environment files or values are read. No services were started or restarted. The launcher still needs a child-environment readiness check for the owner-reported `cryptography` dependency; this draft adds no install, dependency, preflight, or doctor behavior.
