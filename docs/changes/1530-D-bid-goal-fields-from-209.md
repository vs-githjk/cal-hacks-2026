# Lane D: Bid and Goal contract fields that landed with #209 (Lane A part D)

Recorded after the fact. #209 changed `contracts/Bid.schema.json` and `contracts/Goal.schema.json` with no note here. All additions are optional, except the tightened numbers below.

## Bid (per line)
- Tighter rules: `unit_price`, `quantity` and `qty_available` must be greater than 0. A bid with a zero or negative price or quantity now fails validation.
- A line must not carry `floor`: the private floor is never sent.
- New optional fields:
  - `shipping` (flat, at least 0, added once per line);
  - `listing_id`;
  - `line_index` (the original line index, set by the market);
  - `origin` (LIVE, MIRROR or SIM);
  - `source`, `seller_of_record`, `model_number`, `snapshot_id` and `snapshot_date`;
  - `floor_evidence` (only the provenance of the floor: origin, source, observed_at);
  - `shipping_evidence` (SIM policy, or MIRROR with source and observed_at).
- New optional top-level `seller_of_record`: the merchant named by a MIRROR listing, which is not the payee.

## Goal
- New optional fields:
  - `items[].allowed_conditions` (new, open-box, refurbished, used);
  - `parent_goal_id` and `parent_part`, for the child goals of a build. These are private and local, and omitted on parent goals.

## Who is affected
- Lane B and Lane C: no change required. Every new field is optional, so a reader that ignores unknown fields keeps working. A producer that sends a zero price or quantity now fails `common.validate("Bid")`.

The seller admission envelope note is `0414-A-seller-admission-envelope.md` (Lane A's, carried from its branch).
