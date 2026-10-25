"""What the Fish Market Caller says about itself in chat. One fixed text: any message it receives gets this answer, the asker's
words are never repeated, and nothing in chat can place a call or approve a purchase.

The limits quoted here are pay/approval.py's (VOICE_CODE_TTL_SECONDS = 300, MAX_ATTEMPTS = 3); a test pins them together.
"""

SECOND_FACTOR_TEXT = (
    "I am the Fish Market Caller, the second-factor agent. When the buyer agent wants to spend your money, the buyer agent "
    "cannot approve its own spend: approval needs a second channel that only you hold, and I am that channel. I place one "
    "phone call to the number on file. A two-word code appears on your own screen (your private chat or your buyer page) and "
    "you say it back on the call, with the word approve. The code is made for that exact amount and that exact seller, it "
    "lasts 5 minutes, and you get 3 tries. A code typed into a chat never approves anything, and this chat never approves "
    "or charges anything either. I do not ask for, hold or relay your passwords or one-time codes for other sites. I take "
    "call requests only from the Fish Market buyer agent, and only fresh ones. To start a purchase, send a goal to "
    "@techbazaarbuyer."
)
