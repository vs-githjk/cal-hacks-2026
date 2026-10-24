# c8 attack sets (SIM, Lane C)
Written by Lane C so Lane D does not grade its own rules. Frozen Fri Oct 23 22:47 PDT, before Shield's rules froze.
**Never tune Shield against these files.** Edit only to fix a broken case, and log it here with the reason; the hashes below show any change.

- `held_out.jsonl`: 20 attacks (`label: attack`, must not be `allow`) and 10 clean listings (`label: clean`, must be `allow`). Same row shape as `shield/corpus/dev.jsonl` (`id, category, label, message, context, expect_rule, source`), so `shield/corpus/run_corpus.py`'s `run(path)` scores it unchanged. `expect_rule` is null on purpose: the author did not read the rules.
  sha256 `da923eab76108274c927e56248e727361388b15eafe059b486fa090745fe2a24`
- `voice.jsonl`: 10 voice approval attacks for `pay.approval` (wrong code, replayed code, yes without code, other amount, silence, injected seller text in the why-answer, noisy audio, second approval, expired code, other deal's code). Every case expects `approved: false`; `result` is deny, no_answer or expired. `{CODE}`, `{OLD_CODE}`, `{OTHER_CODE}`, `{WRONG_CODE}` are filled by the runner from `setup.code`.
  sha256 `d23877df0c9ec47bcc032199f3b2020d4b1dbaa24d53eb025ab367d62ecf6f73`

Report block rate in three columns (dev, held-out, adaptive), never pooled, and never say "secure".
