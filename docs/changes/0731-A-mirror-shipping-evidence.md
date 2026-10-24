# MIRROR shipping evidence contract

MIRROR seller bids may carry observed shipping provenance as a closed object containing only `origin: "MIRROR"`, the source URL, and an aware observation timestamp. The numeric shipping amount remains on the Bid line and is not copied into the provenance object. The existing closed SIM branch for unobserved zero shipping remains unchanged.

The seller policy validates the supplied term before creating a MIRROR bid. It requires a finite nonnegative amount, a safe absolute HTTP(S) URL without user information or controls and with a valid nonzero port when specified, and a timezone-aware observation time. It emits only the three public provenance fields. Invalid or absent terms continue to make the listing ineligible. Snapshot filenames containing `sold` are excluded from seller listings.

No source URL is fetched and no missing amount or timestamp is inferred. The public `agents/sellers/sellers.json` currently contains no `mirror_inputs`, so this change does not establish a live MIRROR seller path; it defines and tests the producer/contract boundary only.
