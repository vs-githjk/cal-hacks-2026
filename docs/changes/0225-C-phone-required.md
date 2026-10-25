# 0225 C A buyer's phone is required to sign up (#449 PL-15, RT-16)
`sign_up_buyer` now refuses an empty or blank phone with "a phone number is required: purchases are approved by a call" (the E.164 check is unchanged). The reducer signature is the same (`phone` stays an optional argument), so module_bindings do not change; any caller that omitted the phone now gets that refusal. The only caller is `/start`, which asks for the phone first (web/src/lib/signUp.ts `cleanSignUp`).
Affects: market/spacetimedb/src/market.ts (`signUpBuyer`), web/src/app/start/page.tsx, web/src/lib/signUp.ts.
