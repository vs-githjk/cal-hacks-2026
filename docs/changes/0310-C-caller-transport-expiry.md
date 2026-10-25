# 0310 C Buyer seed guard and expiring delegated call (#449 PL-22, RT-24)
`caller_agent.py` now exits at start unless `BUYER_AGENT_SEED` is a private seed (16+ characters, not `*-dev`): the Caller obeys only that address (`relay.buyer_seed_problem`).
The buyer's delegated voice call is sent as `common.ExpiringVoiceTransportRequest` (from #458) with `expires_at` = now + `DELEGATE_TIMEOUT_S` (240 s), so a request still queued after the buyer fell back to its own direct call is refused as stale. `VoiceTransportRequest` is unchanged, so its pinned schema digest holds.
