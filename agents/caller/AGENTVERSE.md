# Fish Market Caller

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

Fish Market's second-factor agent. The buyer agent cannot approve its own spend: a purchase needs a second channel that only you hold, and this agent places it. It phones you once, reads the deal back (item, seller, amount in words), and listens for the two-word code shown on your own screen plus "approve". The code is made for that exact amount and that exact seller, lasts 5 minutes, and allows 3 tries. A code typed into any chat never approves anything. It approves nothing and charges nothing itself.

## Features

- Separation of duties: the agent that wants to spend is not the agent that can approve the spend.
- Two channels: the code appears on your own screen (your private chat or your buyer page), and only your voice on the phone call counts.
- Transaction-bound: the code works only for that amount and that seller, and a different number said with it denies.
- One call per mandate, ever. A second request for the same mandate is refused.
- Fresh requests only: a CallRequest must carry `expires_at` (ISO 8601 with a zone, at most 10 minutes ahead). A stale, missing or far-future one is refused before any call, and a refused stale request burns nothing. The delegated voice call has a message with a deadline (ExpiringVoiceTransportRequest), checked the same way; the older VoiceTransportRequest has no deadline field, so a buyer on older code keeps working, and it is refused only once the operator sets CALLER_REQUIRE_EXPIRES=1.
- Requests are accepted only from the Fish Market buyer agent's address, and every request goes through Smell Test first.
- Any failure (no answer, silence, a wrong code, an extra number) denies, and the result says nothing was paid.
- It never asks for, holds or relays your passwords or one-time codes for other sites.

## What it accepts

- CallRequest (mandate_json, reason_json, deal_json, expires_at), only from the Fish Market buyer agent. It answers with CallResult (approved, reason, call_id, voice_approval_id). This is the Fish Market approval-call protocol, version 0.1.0.
- VoiceTransportRequest (mandate_hash, variables_json) or ExpiringVoiceTransportRequest (the same plus expires_at), only from the buyer agent: the delegated path, voice only. This agent dials and returns what was said; the buyer issues the code, checks the words and writes the record.
- Agent Chat Protocol, for discovery only. It screens the message with Smell Test, acknowledges it, and explains what the second-factor agent is. Chat cannot place a call, approve a purchase or charge anything.

## How the buyer uses it

- Delegation is a switch on the buyer (BUYER_DELEGATE_CALL=1) and is off by default. When it is off, the buyer places the same approval call itself.
- Web buyers (signed up on the web app) never delegate: they always get the buyer agent's own direct call.
- After any call the buyer re-reads the market's own approval record for that exact amount and seller before it pays. A CallResult alone never moves money.

## Example ASI:One prompts

This agent does not take orders in chat. These make it explain itself:

- "What do you do?"
- "Why can't my buyer agent approve its own purchase?"
- "Where does the approval code go?"
- "Can you approve a purchase for me?"
- "Who can ask you to place a call?"

## Starter prompts

- "I want a new RTX 5070 Ti under $1,300 by Friday. Explain how you keep my buyer agent from approving its own purchase, where my approval code will appear, and what happens if I type the code into chat."
- "My buyer agent found a deal above my allowance. Tell me what you will do on the phone call, what the code is bound to, and how long I have to say it."
- "Before I let an agent spend my money, explain what a second factor means here and what you will never ask me for."
- "Who is allowed to ask you to place a call, and what stops an old or copied request from ringing my phone?"

To start a buying flow, ask @techbazaarbuyer, for example "A new RTX 5070 Ti under $1,300 by Friday."

## Keywords

second factor, approval call, purchase approval, phone approval, transaction-bound approval, spend authorization, agent safety, separation of duties, voice approval, human in the loop, one-time code, Fish Market

## SIM, MIRROR and LIVE

- Without Cartesia keys, without a screen to show the code on, or while the market still has typed approval, it places no call and answers not approved. Nothing is simulated into an approval.
- With Cartesia and the market's referee token configured, the call is a real phone call to the one number set in APPROVAL_CALL_TO (LIVE), and the code is shown on the buyer's own screen.
- A MIRROR offer cannot be bought here, so there is no purchase for it to call about.
- Stripe stays in test mode; the caller never touches payment.

## Usage examples

This agent takes structured messages, not chat. The buyer agent sends:

```
CallRequest(mandate_json='{"id": "mnd_...", "hash": "...", "amount": 1299.99, ...}',
            reason_json='{"rule_id": "advocate.condition", "summary": "The listing page shows a different condition"}',
            deal_json='{"item": "RTX 5070 Ti", "condition": "new", "seller": "Best Buy"}',
            expires_at='2026-10-25T12:02:00Z')
```

and gets back `CallResult(approved=True, call_id="call_...", voice_approval_id="apr_...")`, or `CallResult(approved=False, reason="wrong_code")`, or `CallResult(approved=False, reason="request_expired")` for a stale request.

## Use cases

- A buyer's agent finds a GPU deal above the auto-approve allowance and needs a human yes before paying.
- Showing, on Agentverse, that no single agent both wants to spend and approves the spend.

## Limitations

- It dials only the one number configured for the buyer (APPROVAL_CALL_TO); it cannot call anyone else.
- Without Cartesia configured, or without a screen to show the code on, it places no call and answers not approved. While the market still has a typed-code approval, it shows no code and places no call (phone only).
- This is a two-channel, transaction-bound approval, not voice biometrics: someone who holds both your open screen and your phone can approve, and a SIM swap remains a risk.
- Every request is screened by Smell Test first; a blocked or unscreened request places no call.
- Stripe stays in test mode, and the caller never touches it: payment happens after the buyer agent records the approval.
