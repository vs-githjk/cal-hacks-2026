# Lane A: trusted Shield context

`common.screen` sends `payee_of_record`, `price_history` and `sender_role` with each message. Roles come from the local agent address map; unknown addresses stay unknown. Seller payee records use the configured seller agent address. Missing Shield configuration, every non-200 response, transport errors and invalid verdicts block the message.

Buyer bid screening checks the complete message, then checks each SKU line with only that SKU's reference. A shared or persona price claim in a multi-SKU bid is checked against each SKU reference independently, conservatively quarantining an ambiguous claim. The available references come from `agents/advocate/mock_data.py` and are SIM baselines with one point per listed SKU, not live history. Unmatched SKUs have no price context. A structured payee or recipient mismatch for a uAgent address is quarantined after Shield screening because the shared regex rule recognizes email and wallet address formats.
