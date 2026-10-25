# Bazaar Caller

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

The agent that places Tech Bazaar's approval phone call. It is built to receive a CallRequest from the buyer agent for a deal over the buyer's allowance (not wired yet: today the buyer agent does not send it, and the live demo places the same call from the bridge). The caller phones the buyer once, reads the deal back (item, seller, amount in words), and listens for the two-word code shown on the buyer's own screen plus "approve". It answers with a CallResult. It approves nothing and charges nothing itself.

## Features

- One call per mandate, ever; a second request for the same mandate is refused.
- Requests are accepted only from the Tech Bazaar buyer agent's address.
- The mandate must verify (hash, amount, payee, expiry) before any call is placed.
- The code goes only to the buyer's own screen, never into the call script or a chat message.
- Any failure (no answer, silence, a wrong code, a number or another amount said with the code) denies, and the result says nothing was paid.

## Usage examples

This agent takes structured messages, not chat. The buyer agent sends:

```
CallRequest(mandate_json='{"id": "mnd_...", "hash": "...", "amount": 1299.99, ...}',
            reason_json='{"rule_id": "advocate.condition", "summary": "The listing page shows a different condition"}',
            deal_json='{"item": "RTX 5070 Ti", "condition": "new", "seller": "Best Buy"}')
```

and gets back `CallResult(approved=True, call_id="call_...", voice_approval_id="apr_...")` or `CallResult(approved=False, reason="wrong_code")`.

## Use cases

- A buyer's agent finds a GPU deal above the auto-approve allowance and needs a human yes before paying.
- Once the buyer agent sends CallRequests, the workflow shows on Agentverse as buyer, advocate, caller, then payment.

## Limitations

- It dials only the one number configured for the buyer (APPROVAL_CALL_TO); it cannot call anyone else.
- Without Cartesia configured, or without a screen to show the code on, it places no call and answers not approved. While the market still has a typed-code approval, it shows no code and places no call (phone only).
- Every request is screened by Bazaar Shield first; a blocked or unscreened request places no call.
- Stripe stays in test mode, and the caller never touches it: payment happens after the buyer agent records the approval.
