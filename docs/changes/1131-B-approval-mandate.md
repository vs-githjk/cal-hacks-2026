# #191: approval and mandate contract (Lane B)

For Lane D (demo/bridge.py and the approval relay):

- `record_approval(mandateHash, method, approvedBy, voiceApprovalId)`: referee only. `method` is `voice_code` or `allowance`. `voice_code` needs the VoiceApproval id from the call; it is kept on the approval row. `allowance` only for a mandate inside the allowance.
- `approve_typed` is removed (LOCKED 08:40: approval by phone call only). `issue_approval_code` and `my_pending_approvals` stay, to show the code on /buyer.
- `create_mandate`: referee only. `dealId` must name the rank 1 bid of a closed round; `payee` = that bid's seller id; `amount` = its round_result landed; `expiryMinutes` 1 to 10.
- Close: an advocate card `caution` (latest card per bid) holds the bid back. It still ranks, below every bid not held back, with reason `held back: advocate caution (<rule>: <text>)` on its round_result row.
- Floor event `mandate_created` label is always `Deal ready for approval`.
- New buyer-only views: `my_bid_checks` (checks on bids in the buyer's rounds) and `my_deals` (mandate plus approval and payment).
- The module is not published from this branch; publish and bridge changes wait for the owner of the local database.
