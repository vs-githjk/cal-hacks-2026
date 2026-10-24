# C: Scoreboard gains two tile ids (#98)

`contracts/Scoreboard.schema.json`: tile `id` enum adds `voice_attacks` and `hyphenate_blind`. Additive only; the four
existing tiles and every field are unchanged. Both new tiles are SIM, `status: measured`, and headline the first run
(voice 9 of 10 denied; Hyphenate 26 of 27 planted caught, 2 of 7 clean falsely flagged). The after-fix runs are in
`detail` only. A consumer that renders tiles by id should skip ids it does not know.
