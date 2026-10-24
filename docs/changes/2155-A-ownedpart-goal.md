Lane A (Abhinav): added `contracts/OwnedPart.schema.json` and `contracts/Goal.schema.json`, as written in docs/kickoff/00-shared.md.
Additions: OwnedPart.condition adds `unknown` (the buyer did not say); Goal.items[] carries `skipped_owned_part_id` so the card can cite the owned entry it skipped. OwnedPart.attrs use SpecCard attr names (e.g. psu `wattage`, case `max_gpu_length_mm`).
Affects: B (Goal reducer, please confirm), C (fit checker reads OwnedPart attrs as SpecCards).
Until B's rename (PR #5) lands, Lane A's Need items carry both `condition`/`variant` and the old `grade`/`pack_size`.
