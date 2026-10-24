# Build Story: developer handoff spec (Lane C for Lane B #343, Lane A #344, Lane D #345)

Owner: Anoop (Lane C, data and truth). For: Vedant (Lane B, #343, visuals), Abhinav (Lane A, #344, planner), Vidyut (Lane D, #345, rounds, call, receipts).
Status: v1, Sat Oct 24 16:40 PDT. Recording due 19:30: a 6-part build at 1440 px and 390 px.

How to read the tags in this file:

| Tag | Meaning |
|---|---|
| **per #344** | Field is in Abhinav's posted planner shape (comment on #344, code in PR #358). Use as named. |
| **per #344 (ask)** | Not in the posted shape yet. Asked for in section 13. Build the fallback until it lands. |
| **per #345** | Lane D has not posted the build shape yet. Name is a placeholder; do not hard code it, read it through one adapter. |
| **per #363** | Knockout round contract (docs/changes/1633-B-knockout-rounds.md). Final. |
| **main** | On main today (`data/fit_checker`, `agents/advocate/checks.py`). |
| **per #287 (open)**, **per #324 (open)** | Lane C PRs still open. Names are final unless review changes them. |

Money is always integer cents in data. The UI formats with `money()` from `web/src/components/ui.tsx`. Part ids are `gpu`, `cpu`, `motherboard`, `memory`, `storage`, `cooler`, plus owned-only `psu` and `case`. "RAM" and "SSD" are display labels only, never ids.

---

## 1. Overview

A judge watches one sentence become a whole PC in under two minutes. Every part is fought for in its own sealed knockout arena. Every trap is caught on screen with its source. Every compatibility line is visibly checked, and one red line is fixed by the agents themselves. One human call approves the whole build. Every winning price is re-checked live, and each part gets a receipt.

The screen is a truth display before it is a show. Most of what it shows is Lane C data (fit checks, real listings, recalls, price baselines, labels). The design goal is: **nothing on screen is a claim without a source link and a LIVE, MIRROR or SIM label**, and anything unknown looks unknown.

### 1.1 Story beats and target timing (recording)

| # | Beat | Driven by | Target time |
|---|---|---|---|
| 1 | Sentence in; planner splits it into 6 parts with budgets; PSU and case appear as owned | `plan()` output, step `plan` (per #344) | 0:00 to 0:10 |
| 2 | Exploded PC: 8 slots around the chassis, 6 open, 2 owned and dimmed | `plan().parts`, `plan().owned` | 0:10 to 0:15 |
| 3 | Six arenas run (sealed stages, vetoes, Shield blocks, champions lock) | `round`, `round_result` (per #363), advocate cards | 0:15 to 0:55 |
| 4 | Lines check: grey to green, amber where unknown. Today the checks come from `resolve()`, after all rounds, so every line checks at once; one by one only if 13.2.1 adds a check per pick | fit checks (per #344 (ask)) | 0:55 |
| 5 | Re-plan: a line goes red, the planner swaps the part, moves budget, the line goes green | steps `clash`, `swap`, `reallocate` (per #344) | 0:55 to 1:15 |
| 6 | Budget bar settles under the cap; step `locked` | `resolve().total_cents`, step `locked` | 1:15 to 1:20 |
| 7 | Zoom into the one approval call; total, number of sellers, the "why"; flips to approved | per #345 | 1:20 to 1:45 |
| 8 | Receipts per part, "checked live Ns ago", one mandate per seller under one build id | per #345 | 1:45 to 2:00 |

The 2D board is the primary view. The 3D floor (`Floor3D.tsx`) is not used for this demo. "2D fallback" in #343 means: if the exploded layout misbehaves, the same components render as a plain vertical list (section 2.4). Build the list view first; it is also the 390 px layout.

---

## 2. Layout and grid

### 2.1 Desktop, 1440 x 900 (recording size)

12-column grid, 72 px outer margin, 24 px gutter, content width 1296 px. Blueprint grid background from `globals.css` stays.

```
+--------------------------------------------------------------------------------------------+
| TopBar: goal sentence (serif)                       build id  run-mode chips  cap $2,000   |  72 px
+--------------------------------------------------------------------------------------------+
| BudgetBar (full width, 12 cols)                                                            |  64 px
+------------------------------------------------------------+-------------------------------+
| BuildStage (8 cols, 856 x 620)                              | Rail (4 cols, 416 px)         |
|                                                            |  StepLog (planner lines)      |
|   [Cooler]       [CPU]        [GPU]                        |  ---------------------------- |
|                                                            |  ArenaPanel for focused slot  |
|   [Memory]   [Motherboard]   [Storage]                     |   stage dots, bid rows,       |
|                                                            |   advocate card, comparison   |
|   [PSU owned]   [ CASE owned, chassis frame label ]        |   card                        |
|   SVG CompatLine layer behind the slots                    |                               |
+------------------------------------------------------------+-------------------------------+
| ReplanBanner (overlays the bottom of BuildStage when active, 8 cols)                       |
+--------------------------------------------------------------------------------------------+
```

- **BuildStage** is a 3 x 3 CSS grid, each cell 264 x 180 px, 32 px gaps. The chassis is a rounded frame (`--radius-lg`) that encloses rows 1 and 2 and the PSU cell, drawn as the case. The case's own label sits in row 3, columns 2 and 3, as a wide owned slot.
- Slot cells (fixed, so lines never re-route): row 1 `cooler`, `cpu`, `gpu`; row 2 `memory`, `motherboard`, `storage`; row 3 `psu`, `case` (spans 2).
- The motherboard sits in the center because most rules touch it.
- **CompatLine layer**: one absolutely positioned SVG under the slots, same size as BuildStage, `pointer-events: none` except on line hit areas (12 px wide invisible stroke).
- **Rail**: StepLog is at most 220 px tall, scrolls, newest at the bottom. The ArenaPanel fills the rest. Focus follows the most recent event unless the user has clicked a slot, then it stays on that slot until Escape or the user clicks another.
- After approval the Rail swaps to **ReceiptList** (section 5.12) and the BuildStage stays, all slots locked.
- **CallZoom** (section 5.11) is a modal layer over the whole page: a 720 x 520 card centered, with the page dimmed to 40 percent behind it.

### 2.2 Phone, 390 x 844

Single column, 16 px side gutter, content width 358 px. No horizontal scroll at any point.

```
+--------------------------------+
| TopBar (sentence wraps, 2 lines max, then "more")
| BudgetBar (compact, 40 px)     |
| ReplanBanner (sticky under the budget bar when active)
| SlotRow gpu      [champion] (v)|
| SlotRow cpu      [stage 2/3]   |
|   CompatLine stub: cpu + board |
| SlotRow motherboard ...        |
| ... memory, storage, cooler    |
| SlotRow psu (owned, dimmed)    |
| SlotRow case (owned, dimmed)   |
| StepLog (collapsed, "6 steps") |
+--------------------------------+
```

- The exploded stage is replaced by a list of **SlotRow**s in a fixed order: `gpu`, `cpu`, `motherboard`, `memory`, `storage`, `cooler`, `psu`, `case`.
- Lines become **CompatList** rows: under each SlotRow, one row per rule that involves this part and a part above it in the list, so every rule appears exactly once. Each row has an icon, the plain words and the compared numbers (same content as the desktop line label).
- Tapping a SlotRow expands it in place (accordion, one open at a time) to show its ArenaPanel. The advocate card details open in a **bottom sheet** (section 5.7).
- CallZoom is full screen.
- ReceiptList replaces the slot list after approval, with a "Show build" toggle.

### 2.3 Between 390 and 1440

- 1024 px and up: desktop layout, Rail narrows to 360 px, slot cells scale to fit (min 220 x 160).
- Below 1024 px: phone layout, content width up to 640 px, centered.
- Nothing is specified in between beyond this; the recording uses only 1440 and 390.

### 2.4 2D fallback ("list view")

The phone layout at any width is the fallback. A `?view=list` query parameter (Lane B owns the name) forces it on desktop, for when the exploded stage or SVG lines fail during the recording. All data, states and wording are identical; only the geometry changes.

---

## 3. Design tokens

The app is deliberately black and white (`web/src/app/globals.css`: "meaning never rides on hue"). In that file `--mint` and `--coral` are both `#ffffff` and `--amber` already means SIM. **Do not reuse those for fit verdicts.** The Build Story adds a small, scoped status palette used only on compatibility lines, verdict chips and the budget overflow. Every coloured state also has an icon, a stroke style and a word, so colour is never the only signal.

### 3.1 Colour (new tokens, add to `:root` in globals.css)

| Token | Value | Use | Pair with |
|---|---|---|---|
| `--fit-pass` | `#3ddc84` | Line and chip: check passed | Check icon, solid stroke, word "Fits" |
| `--fit-fail` | `#ff5a52` | Line and chip: check failed; over cap | Cross icon, solid stroke 3 px, word "Clash" |
| `--fit-uncertain` | `#f5b83d` | Line and chip: spec unknown | Question icon in a circle, dotted stroke, word "Uncertain" |
| `--fit-unchecked` | `#4a4a4a` | Line: not checked yet | Hollow dot, dashed stroke, words "Not checked yet" |
| `--fit-recheck` | `#8c8c8c` | Line while re-checking after a swap | Small spinner or 3 dots, dashed stroke, "Re-checking" |
| `--fit-pass-soft`, `--fit-fail-soft`, `--fit-uncertain-soft` | the three above at 14 percent alpha | Chip and banner fills | |

Contrast against `--canvas` (#000): pass 11.8:1, fail 6.8:1, uncertain 11.8:1, unchecked 2.4:1 (decorative line only; its label text uses `--muted` #8c8c8c at 6.2:1). All text on soft fills uses `--ink`.

Existing tokens used as they are: `--canvas`, `--panel`, `--soft`, `--ink`, `--ink-2`, `--muted`, `--line`, `--line-2`, `--accent`, `--sky` (MIRROR and source links), `--amber` (SIM chip only, never a verdict).

### 3.2 Type (Geist, Geist Mono, Instrument Serif from `fonts.ts`)

| Token | Desktop | Phone | Use |
|---|---|---|---|
| `type-hero` | Instrument Serif 48/52 | 32/36 | The goal sentence; the total on CallZoom |
| `type-title` | Geist 600 20/26 | 18/24 | Slot part name, panel titles |
| `type-body` | Geist 400 15/22 | 15/22 | Default |
| `type-small` | Geist 400 13/18 | 13/18 | Reasons, line labels, notes |
| `type-micro` | Geist 500 11/14, +0.04em, upper case | same | Chips (LIVE, MIRROR, SIM, OWNED), stage labels |
| `type-num` | Geist Mono 500 15/20, tabular | same | Prices, mm, watts, timers, ids |

Minimum text size on phone is 13 px except chips (11 px, upper case, 500 weight).

### 3.3 Spacing, radius, elevation

| Token | Value |
|---|---|
| `space-1` to `space-8` | 4, 8, 12, 16, 24, 32, 48, 64 px |
| `radius-sm` | 8 px (chips, bid rows) |
| `radius` | 16 px (existing `--radius`: cards, slots) |
| `radius-lg` | 24 px (chassis frame, CallZoom) |
| `shadow` | existing `--shadow`, CallZoom only |
| Slot padding | `space-4` desktop, `space-3` phone |
| Line stroke | 2 px default, 3 px on fail, 12 px invisible hit area |

### 3.4 Motion

| Token | Value | Use |
|---|---|---|
| `dur-fast` | 150 ms | Hover, focus, chip swaps |
| `dur-med` | 300 ms | Line colour change, row enter and exit |
| `dur-slow` | 600 ms | Slot lock, budget segment resize, CallZoom open |
| `ease-out` | `cubic-bezier(0.2, 0.8, 0.2, 1)` | Everything entering |
| `ease-in-out` | `cubic-bezier(0.4, 0, 0.2, 1)` | Resizes |
| `dwell-clash` | 1600 ms | Minimum time a red line stays red before the swap plays |
| `dwell-swap` | 900 ms | Minimum time between swap start and the re-check |
| `dwell-step` | 500 ms | Minimum gap between any two StepLog lines |

Use `motion` (already in `web/package.json`). `globals.css` already disables all animation under `prefers-reduced-motion: reduce`; see section 6.4 for what replaces it.

---

## 4. Data the screen reads

Lane B should build against one view model per component (in `web/src/lib/screens.ts` style) and fill it from one adapter per source. Section 4 is the field map. Never read raw seller text into any verdict, reason, banner or call line.

### 4.1 Planner, before rounds: `plan(cap_cents, owned)` (per #344)

| Field | Type | Drives |
|---|---|---|
| `cap_cents` | int | BudgetBar cap marker; TopBar "cap" |
| `owned.psu` `{name, watts}` | object | Owned PSU slot: name, "750 W" |
| `owned.case` `{name, gpu_max_mm}` | object | Owned case slot: name, "GPU up to 305 mm" (see 13.2) |
| `parts[]` `{part, budget_cents}` | list | One open slot per entry; BudgetBar segment widths before any lock |
| `rules[]` | list of rule_id | Which CompatLines to draw at all. A rule not in this list draws no line. |
| `steps[]` `{kind, line}` | list | StepLog; `plan` line is the first log line |

### 4.2 Planner, after rounds: `resolve(plan, offers)` (per #344)

| Field | Type | Drives |
|---|---|---|
| `status` | `locked` or `blocked` | `locked`: CallZoom may open. `blocked`: BlockedState (5.13), no call |
| `picks.{part}` `{seller, price_cents, spec, source}` | object | Slot champion name, price, source link |
| `knockouts[]` `{part, seller, rule_id, reason, sources}` | list | Bid row knocked out by the planner (fit or `budget.over`) |
| `budgets.{part}` | int | BudgetBar segment for open parts after reallocation |
| `total_cents` | int | BudgetBar total; CallZoom total |
| `sellers[]` | list | CallZoom "N sellers"; ReceiptList grouping |
| `steps[]` | list | StepLog and the re-plan choreography (6.2) |

Step kinds and extra keys (per #344): `plan`; `pick` {part}; `knockout` {part, rule_id}; `clash` {part, with[], rule_id}; `swap` {part}; `reallocate` {part}; `locked`; `blocked` {part}. `step.line` is a short, dash-free sentence safe to show as is.

### 4.3 Fit checks (main: `data/fit_checker/build_check.py`; delivery per #344 (ask))

`check_build(parts)` returns:

| Field | Type | Drives |
|---|---|---|
| `verdict` | `pass`, `partial`, `fail`, `uncertain` | BuildVerdictChip (5.9) |
| `complete` | bool | `false` means some parts were not given |
| `summary` | string | BuildVerdictChip tooltip; e.g. `PASS for the 4 rule(s) that could run; not given: cooler, storage (4 checks: 4 pass, 0 fail, 0 uncertain)` |
| `rules_run` | int | "N rules checked" |
| `missing_parts` | list | Lines touching these stay `unchecked` |
| `problems` | list | Build-level uncertain reasons (a part we could not read) |
| `checks[]` `{rule_id, verdict, reason, parts, sources, origin}` | list | One CompatLine state each |
| `parts.{category}` `{name, attrs, maker_data: {attr: source}}` | object | SpecPopover: which spec came from our maker data, and its page |
| `notes` | list | SpecPopover notes (BIOS note, sibling model caveat) |

Important details:

- `check.verdict` is `pass`, `fail` or `uncertain`. A rule that could not run because a part is missing has **no check row**; its line is `unchecked`.
- `check.reason` is the technical comparison, written by our code from spec values, e.g. `cooler 155 mm exceeds case clearance 145 mm`, `CPU socket AM5 does not match board socket LGA1700`, `750 W PSU covers est. load 520 W, need 624 W (20% headroom, maker recommends 750 W)`. Show it as the line's **compared numbers** text. The headline is the plain words from the closed table (11.2), keyed by `rule_id`.
- `check.parts` holds part **names**, not ids. Map line endpoints from `rule_id` using table 5.4, never from `parts`.
- `check.sources` are maker page URLs. `check.origin` is the check's label (MIRROR for dated maker data, SIM for fixture specs). Show both.
- There is no `specs_used` field. The compared numbers live in `reason`; the per-spec provenance lives in `parts.{category}.maker_data`.

Ask to #344 (13.1): include `checks` (the full `check_build` result) in `resolve()` and once more after each `swap`, so lines can turn green. Until it lands, the fallback is: only lines named by a `clash` step turn red, every other line stays `unchecked`. A fit `knockout` is a bid that left the round (usually a clash with an owned part, like a card too long for the case); it shows on its BidRow, never on a line, because that bid is not in the build. **A line never turns green without a check row.**

### 4.4 Rounds (per #363)

| Field | Drives |
|---|---|
| `round.stage`, `round.maxStages` | StageDots "Stage 2 of 3" |
| `round.stageWindowS`, deadline | Stage countdown |
| `round_result` per seller per stage: `stage`, `status` (`knocked_out`, `advancing`, `champion`), `reason` | BidRow state |
| `floor_event` per knockout, e.g. `Seller knocked out (stage N)` | StepLog sub-line inside the ArenaPanel (not the main log) |
| Bid price, seller label, origin | BidRow (per #345 for the build-round projection) |

Sealed means: during a stage the UI shows that a bid arrived, not its price. Per #363 a seller never sees another seller's price. When the buyer screen may show prices (at stage close or at round close) is per #345; until then show prices at stage close.

### 4.5 Advocate card, one per bid (main: `agents/advocate/checks.py`; real-data parts per #287 (open), store rule per #324 (open))

| Field | Type | Drives |
|---|---|---|
| `recommendation` | `buy`, `caution`, `veto` | AdvocateChip on the BidRow |
| `rule_id` | string | Which closed-table line is the headline |
| `reason` | string, closed table | Card headline. Never seller text. |
| `source_url` | url | Headline source link |
| `warnings[]` `{kind, rule_id, text, source_url, dollar_impact}` | list | Up to 3 warnings (sorted by `dollar_impact`, vetoes first) plus any number of info notes |
| `call_reason` `{rule_id, summary, source_url}` | object | What the call may say about this bid (Lane D) |

Kinds (main): veto kinds `condition`, `fit`, `fit_unconfirmed`, `recall`, `same_seller`; info kind `note` (shown, never changes the recommendation). Others seen: `price`, `spec`, `record`, `floor`, `unsourced`, `fit_unknown`, `fit_ok` (internal, not shown).

Info note rule ids (per #287 (open)): `advocate.baseline_unverified` (price baseline unavailable), `advocate.recall_unverified` (recall check unavailable, or brand not given or not confirmed), `advocate.brand_mismatch`. Card-level headline when any lookup could not run: `advocate.unverified`, "Some checks could not run".

Recall (per #287 (open)): full model match vetoes with `advocate.recall`; a similar model is a caution with `advocate.recall_partial`, "A CPSC recall names a similar model, so check the exact model", with the recall link.

Price (per #287 (open)): warning text includes the baseline and its date, e.g. `above the price history baseline of $1259.99 (MIRROR baseline as of 2026-10-24, 7 retail asks, 2 sources)`. Show the text as is (it is our text, not the seller's).

Store that never joined (per #324 (open)): a Central Computers bid arrives as a **veto** with warning rule_id `advocate.mirror_not_orderable`, "This store is shown for comparison only and cannot be bought from here". The UI must render this as the **ComparisonCard** (5.8), not as a vetoed bid.

### 4.6 Labels

Every price, verdict and spec carries `origin`: `LIVE`, `MIRROR` or `SIM`. Use the existing `OriginChip` (unknown renders as SIM, keep that). Dated values add a date or age after the chip: `MIRROR Oct 24 21:12 UTC`, `LIVE 12s ago`.

### 4.7 Call, mandates, receipts, live re-check (per #345, all placeholders)

`build_id`; per part `checked_at` (Bright Data re-check time), `recheck_status` (ok, failed, price changed), `recheck_price_cents`, `recheck_source_url`; per seller `mandate_id`; per part `receipt` {id, status, link}; call `state`; call `why` lines. Read all of these through one `buildFromLaneD()` adapter so names can change in one place.

---

## 5. Components

Shared rule for every component: anything with a number has a source link and a label next to it. A source link is an external-link icon plus the domain (`maker page: fractal-design.com`), opens in a new tab, `rel="noopener noreferrer"`.

### 5.1 TopBar

- Reads: the buyer's sentence (Lane D goal text; per #345), `build_id` (per #345), `cap_cents`, RunModeFooter service chips (existing).
- Content: sentence in `type-hero` within quotes; right side: `Build B-xxxx` in `type-num`, `Cap $2,000`.
- States: **typing** (sentence types in at 40 chars per second; under reduced motion it appears whole), **planned** (sentence settles, StepLog shows the plan line), **approved** (a chip "Approved by call" appears right of the build id).
- Truncation: desktop never truncates (sentence max ~110 chars at 48 px over 1296 px fits 2 lines); phone clamps to 2 lines with a "more" button.

### 5.2 BudgetBar

- Reads: `cap_cents`, `parts[].budget_cents`, `resolve().budgets`, `picks.{part}.price_cents`, `total_cents`, `reallocate` steps.
- Anatomy: a 12 px bar (phone 8 px). One segment per part in slot order. A cap marker at 100 percent. Text above: `$1,987 of $2,000` (`type-num`), and `$13 left` or `$40 over`.
- Segment states:

| State | Look | Text (tooltip and aria) |
|---|---|---|
| open (budget only) | hatched `--line-2` diagonal, width = budget | `GPU budget about $1,266, round open` |
| locked (champion) | solid `--ink-2`, width = price | `GPU $1,249.99, locked` |
| moved (after reallocate) | 600 ms width change; a 2 px `--accent` outline for 1.5 s | the reallocate `step.line` |
| over cap | the part of the bar past the cap marker uses `--fit-fail` with a cross icon at the marker | `Over the cap by $40` |
| owned | not a segment; two chips under the bar: `PSU owned $0`, `Case owned $0` | |

- Edge: totals never round; show cents when the value has cents (`$1,249.99`), else whole dollars.
- The bar is a summary, not the source of truth: if `total_cents` from resolve disagrees with the sum of picks, show `total_cents` and log a console warning.

### 5.3 Slot (desktop) and SlotRow (phone)

- Reads: part id, `budget_cents`, round state, champion (`picks.{part}`), champion's advocate recommendation, labels.
- Anatomy: part label (`type-micro`: GPU, CPU, MOTHERBOARD, RAM, SSD, COOLER, PSU, CASE), item name (`type-title`, 2 lines max then ellipsis, full name in title attribute), price (`type-num`) + OriginChip, status line (`type-small`), AdvocateChip, warning count badge (`2 warnings, 1 note`).
- States:

| State | Trigger | Look | Status line |
|---|---|---|---|
| planned | after `plan()` | outline `--line`, budget shown | `Budget about $284` |
| waiting | round not open yet | same, muted | `Waiting for sellers` |
| live | round open | outline `--line-2`, StageDots, bid count | `Stage 1 of 3, 4 sealed bids` |
| stage closing | stage close | brief 300 ms flash of the bid rows | `Stage 1 closed, 2 knocked out` |
| round won | `round_result.status = champion` | border `--line-2`, trophy icon, price and seller | `Round won: Micro Center, $1,249.99` |
| locked | planner step `pick` for this part | solid border `--ink`, lock icon | `Locked: Micro Center, $1,249.99` |
| picked after re-plan | step `swap`; the new pick was not the round's champion | solid border `--ink`, lock icon, two-arrows icon | `Picked after re-plan: SellerY, $189` |
| swapped | step `swap` for this part | old name struck through for `dwell-swap`, then the new name | `Swapped: socket clash` |
| no deal | round ended with zero survivors | dashed `--fit-fail` border, cross icon | `No offer passed the checks` |
| blocked | `status = blocked` with this part | as no deal, plus BlockedState | the blocked `step.line` |
| owned | `plan().owned` | 50 percent opacity body, `OWNED` chip, no price, no arena | `Already installed: 750 W` |

- Owned slots keep full opacity on their CompatLine endpoints and labels, so lines into them stay readable.
- Click or Enter focuses the slot (desktop Rail switches; phone row expands).

### 5.4 CompatLine (desktop) and CompatRow (phone)

- Reads: `plan().rules`, `checks[]` (4.3), `clash` and `knockout` steps.
- One line per **part pair**; a pair can carry more than one rule. Endpoints by `rule_id` (never from `check.parts`):

| rule_id | From | To | Notes |
|---|---|---|---|
| `fit.cpu_socket` | cpu | motherboard | |
| `fit.ram_type` | memory | motherboard | shares the line with `fit.ram_slots` |
| `fit.ram_slots` | memory | motherboard | |
| `fit.gpu_length` | gpu | case | |
| `fit.psu_wattage` | psu | gpu and cpu | a "power" line from PSU that forks to GPU and CPU |
| `fit.gpu_connectors` | gpu | psu | shares the GPU branch of the power line |
| `fit.cooler_height` | cooler | case | |
| `fit.cooler_socket` | cooler | cpu | |
| `fit.form_factor` | motherboard | case | |
| `fit.psu_form_factor` | psu | case | |
| `fit.storage` | storage | motherboard | |

- Which rules can turn a line red. A `clash` (per #344) is only between two **picked** parts. A conflict with an **owned** part (PSU, case) knocks that bid out of its round instead, so its line never goes red for the build:

| Can clash between picks (red line, re-plan) | Owned part involved (per-bid knockout, BidRow only) |
|---|---|
| `fit.cpu_socket`, `fit.ram_type`, `fit.ram_slots`, `fit.cooler_socket`, `fit.storage`, `fit.psu_wattage` (CPU plus GPU load) | `fit.gpu_length`, `fit.cooler_height`, `fit.form_factor`, `fit.gpu_connectors`, `fit.psu_form_factor` (this one can run at `plan()` time) |

- Line state = worst of its rules: any `fail` -> fail; else any `uncertain` -> uncertain; else every rule has a `pass` row -> pass; else unchecked. A pair with one pass and one rule not run yet is **unchecked**, with label `1 of 2 checked`.
- Visual per state (colour + stroke + icon + word, always all four):

| State | Stroke | Midpoint badge | Label (desktop on hover or focus, and always for fail; phone always) |
|---|---|---|---|
| unchecked | 2 px dashed `--fit-unchecked`, 6/6 | hollow dot | `Not checked yet` |
| re-checking | 2 px dashed `--fit-recheck`, dash offset animates | 3 dots | `Re-checking` |
| pass | 2 px solid `--fit-pass` | check in a circle | `Fits: cooler 140 mm within case clearance 145 mm` |
| uncertain | 2 px dotted `--fit-uncertain`, 2/4 | question mark in a circle | `Uncertain: card length unknown, no maker data for this model` |
| fail | 3 px solid `--fit-fail` | cross in a circle, 24 px | `Clash: The cooler is taller than your case allows. cooler 155 mm exceeds case clearance 145 mm` |

- Label anatomy: plain words (closed table, by rule_id) on line 1; `check.reason` on line 2 in `type-num` small; then OriginChip + `maker page` source links (one per `check.sources` entry, max 2 shown, then `+N`).
- Fail labels are always visible on desktop (pinned to the line midpoint, nudged to avoid slots). Pass and uncertain labels show on hover, focus or when the slot at either end is focused.
- Phone: CompatRow is one row per rule under the lower SlotRow of the pair: icon, word, plain words, then reason on the next line, source links on the third. Sorted fail, uncertain, unchecked, pass.

### 5.5 ArenaPanel (Rail on desktop, expanded SlotRow on phone)

- Reads: round (4.4), bids, advocate cards (4.5), comparison bids, knockouts (4.2).
- Anatomy, top to bottom: part name and budget; StageDots (`Stage 2 of 3`, three dots, filled = done, ring = current) with countdown `0:07`; **Bids** list (BidRow, buyable only); **For comparison** list (ComparisonCard, if any); the champion's AdvocateCard expanded.
- Order of bids: champion first, then advancing by price, then knocked out by stage (most recent first). Knocked-out rows collapse to one line after their stage.
- Sealed stage: rows show seller label, origin chip and `Sealed` instead of a price until the stage closes.
- Empty: `No bids yet` with the stage countdown; after the window with zero bids, `No seller bid in this round`.

### 5.6 BidRow

- Reads: seller label, price (after close), origin, `round_result.status` and `reason` per stage, advocate `recommendation`, Shield result (per #345), planner knockout.
- Variants:

| Variant | Look | Text |
|---|---|---|
| sealed | price slot shows `Sealed` in `--muted` | `Bid in` |
| advancing | normal | `Advancing to stage 3` |
| champion | row fill `--soft`, lock icon, border `--ink` | `Champion` |
| knocked out, last place | strikethrough price, `--muted` | `Out at stage 2: highest price` |
| vetoed by advocate | strikethrough, AdvocateChip `Veto`, rule icon | headline = advocate `reason` (closed table) + source link |
| blocked by Shield | strikethrough, shield icon, `Blocked by Shield` | Shield rule id and its closed reason; the seller's text is **not rendered** |
| planner knockout | strikethrough, cross icon | `knockouts[].reason` (fit checker reason) or the `budget.over` plain words |
| picked after re-plan | was `knocked_out` or `advancing` in the round, now the planner's pick: row fill `--soft`, lock and two-arrows icons | `Picked after re-plan` (mandate and receipt per 13.2.6) |

- Never show seller-supplied listing text as a reason. The seller label is the seller's display name only.
- Tap or Enter opens the AdvocateCard for this bid (desktop: expands under the row; phone: bottom sheet).

### 5.7 AdvocateCard

- Reads: 4.5.
- Anatomy: AdvocateChip (`Buy`, `Caution`, `Veto` with icon: check, triangle, cross); headline = `reason`; source link for `source_url`; **Warnings** (max 3) each with kind icon, `text`, `$` impact when `dollar_impact > 0` (`$40 above baseline`), source link; **Notes** (info notes) in a separate, quieter list with an `i` icon.
- Unverified rule: if any note has rule_id `advocate.baseline_unverified` or `advocate.recall_unverified`, or the card headline is `advocate.unverified`, the card shows a banner line `Some checks could not run` above the warnings. The recommendation chip stays as computed; notes never change it.
- Condition unverified: if neither side states a concrete condition, the condition line reads `Condition: unverified`.
- Placement at 1440: the focused champion's card is open in the Rail. Other cards open on demand under their BidRow. Max height 320 px, scrolls inside.
- Placement at 390 (answers the brief's question 8.2): the SlotRow shows only the AdvocateChip and a count badge (`2 warnings, 1 note`). Tapping opens a **bottom sheet** (max 80 percent of the viewport height, drag handle, close button, focus trapped) with the full card. The arena list never grows because of warnings.

### 5.8 ComparisonCard (Central Computers and any store that never joined)

- Trigger: a bid with a warning rule_id `advocate.mirror_not_orderable` (per #324 (open)).
- It is **not** a BidRow. It sits in its own **For comparison** section below the bids, never in the ranking, never animated as knocked out (it was never in), never a champion, never in the budget, the call, the mandates or the receipts.
- Look (answers the brief's question 8.3): full-opacity card, 1 px **dashed** `--sky` border, `radius-sm`, no row fill; left icon: a storefront glyph; top line: `Real store, shown for comparison` (`type-micro`); store name and address `Central Computers, 837 Howard St, SF`; item name; price in `type-num` (not struck through; it is a real price); `MIRROR` chip with the capture time `Oct 24 21:12 UTC`; source link to the listing; footer in `type-small`: `Shown for comparison, cannot be bought here.` and `MIRROR: real Central Computers listing captured Oct 24 21:12 UTC via Apify. Central Computers is not a partner.`
- No Buy, Caution or Veto chip on this card. No hover lift. Not focusable as a button; the source link is the only interactive element.
- Phone: one compact row: storefront icon, `Central Computers`, price, `MIRROR`, then `Comparison only` and a chevron to a bottom sheet with the full text.

### 5.9 BuildVerdictChip

- Reads: `check_build().verdict`, `summary`, `rules_run`, `missing_parts`.
- Sits right of the BudgetBar text. Variants:

| verdict | Look | Text |
|---|---|---|
| `pass` and `complete` | `--fit-pass-soft` fill, check icon | `All 11 rules pass` (use `rules_run`) |
| `partial` | outline `--fit-pass`, half-filled check icon | `PASS for the 9 rule(s) that could run` |
| `uncertain` | `--fit-uncertain-soft`, question icon | `Uncertain: 2 rules could not be checked` |
| `fail` | `--fit-fail-soft`, cross icon | `Clash: 1 rule fails` |
| no checks yet | outline `--line-2` | `Not checked yet` |

- Never a plain `PASS` when `complete` is false.

### 5.10 StepLog and ReplanBanner

- StepLog reads `steps[]` from plan and resolve, in order. Each row: kind icon, `step.line` as is, time `16:52:07` in `type-num`. Kinds: plan (list icon), pick (lock), knockout (cross), clash (cross in red), swap (two arrows), reallocate (coins or arrows between bars), locked (check), blocked (stop).
- ReplanBanner: shown during a clash to swap to re-check sequence (6.2). Desktop: a 64 px bar across the bottom of the BuildStage, `--fit-fail-soft` fill with a cross icon, then `--fit-pass-soft` with a check when resolved. Phone: sticky under the BudgetBar.
- Banner text, three phases, each one line:
  1. `Clash: The processor socket does not match the board.` then `check.reason` in small mono below.
  2. `Swapping the board.` then the `swap` step.line, then the `reallocate` step.line if present.
  3. `Fixed: socket now matches.` (pass) or `Still a clash` (fail, the next clash is queued) or `Now uncertain` (amber; the build cannot lock as a pass; see 9).

### 5.11 CallZoom

- Opens when `resolve().status = locked` and the total is above the allowance (Lane D decides; per #345). Inside the allowance: no call; show a one-line toast `Within your allowance, no call needed` and go to receipts.
- Reads (per #345): call `state`, `total_cents`, `sellers.length`, number of parts, `why` lines, approval result.
- Anatomy: phone icon, `Calling Vidyut` (buyer name per #345; `BUYER_NAME` in screens.tsx), the total in `type-hero`, `6 parts from 4 sellers`, a live transcript area (agent lines only from code-owned text: totals, counts, closed-table reasons, `call_reason.summary`), the buyer's answers shown as `You: yes` (the recognised intent, not a raw transcript).
- States: ringing, connected, explaining, buyer asked "why" (shows the 1 to 3 `call_reason.summary` lines it read, each with its source link), approved (card flips: check icon, `Approved by call`, timestamp), declined (`You declined. Nothing was paid.`), no answer (`No answer. Nothing was paid.`), failed (`Call could not connect. Nothing was paid.`).
- Never show seller text, never say "secure", never a typed approval button (phone-only rule).
- Close: after approved, auto-dismiss in 2 s to ReceiptList; Escape also closes. Declined, no answer and failed stay until closed.

### 5.12 ReceiptList

- Reads (per #345): `build_id`, per part `checked_at`, `recheck_status`, `recheck_price_cents`, seller, `mandate_id`, `receipt`.
- Header: `Build B-xxxx: 6 parts, 4 sellers, 4 mandates`. Group rows by seller (one mandate per seller), parts inside.
- Per part row: part label, item, price + chip, **LiveAge** (5.14), seller, receipt status (`Receipt sent` with link, `Receipt pending`, `Receipt failed, retrying`).
- The paid Apify run (#347) is not part of this list. If a future row shows the agent paying Apify, it is LIVE only when that run paid and succeeded, and it shows the Base tx hash with a basescan link, never a token or key.

### 5.13 BlockedState

- Trigger: `resolve().status = blocked`. Lines stay as they are (the failing one red). The slot named by the `blocked` step shows `no deal`. A full-width notice replaces the ReplanBanner: stop icon, the `blocked` step.line (e.g. `No cooler offer fits and stays in budget. Nothing was paid.`), and `Parts locked so far are not bought.` No call, no mandates, no receipts.

### 5.14 LiveAge ("checked live Ns ago")

Answers the brief's question 8.4. Ticks once per second, from `checked_at` (per #345).

| Age | Text | Look |
|---|---|---|
| under 60 s | `checked live 12s ago` | `LIVE` chip solid |
| 60 s to under 5 min | `checked live 3 min ago` | `LIVE` chip outline |
| 5 min or more | `last checked live 14 min ago` | chip outline `--muted`, clock icon, text `--muted`. Before any payment Lane D re-checks again (#345). |
| re-check failed | `live re-check failed; showing the MIRROR price from Oct 24 21:12 UTC` (or SIM) | chip shows the fallback label, never LIVE |
| price changed on re-check | `checked live 8s ago: now $1,269.99 (was $1,249.99)` | the new price is the one shown everywhere |
| never re-checked (SIM sellers) | `not re-checked (SIM seller)` | SIM chip |

Screen readers get the age only on focus (no live region), so the per-second tick is never announced.

---

## 6. Interaction and animation

### 6.1 Global sequence

The UI is driven by events, not timers. Queue every incoming step and render it with at least `dwell-step` between StepLog lines, so six parallel rounds never blur. Rounds animate in parallel; steps in the log play in order.

| Element | Trigger | Animation | Duration | Easing |
|---|---|---|---|---|
| Slots | `plan()` arrives | fade and rise 8 px, staggered 60 ms in slot order | `dur-med` | ease-out |
| Owned slots | `plan()` | fade to 50 percent with the `OWNED` chip | `dur-slow` | ease-out |
| Bid row | bid arrives | slide in from the right 12 px | `dur-med` | ease-out |
| Stage close | stage closes | knocked-out rows strike through left to right, then collapse | `dur-med` | ease-in-out |
| Champion lock | `champion` / `pick` | lock icon scales 0.6 to 1 (existing `pop` keyframe), border to `--ink` | `dur-slow` | ease-out |
| Line check | check row arrives | stroke colour and style crossfade; badge pops | `dur-med` | ease-out |
| Budget segment | lock or reallocate | width change | `dur-slow` | ease-in-out |
| CallZoom | call starts | the BuildStage scales to 0.96 and dims; the card scales from 0.9 at the TopBar's build id to center | `dur-slow` | ease-out |
| Approved flip | approval | card rotates Y 180 degrees to the approved face | `dur-slow` | ease-in-out |

### 6.2 The re-plan moment (the most legible beat)

Sequence for one clash (steps per #344: `clash`, then `swap` or `blocked`, optionally `reallocate`, then a new check):

1. **Red.** On `clash`: every line between `step.part` and each part in `step.with` goes to `fail` at once (one `dur-med` transition). The fail label pins at the midpoint. ReplanBanner phase 1. The two endpoint slots get a 3 px `--fit-fail` outline. Everything else on the stage dims to 60 percent. Hold for at least `dwell-clash` (1600 ms) even if the swap is already queued.
2. **Swap.** On `swap`: the slot's champion name strikes through, slides out left; the new pick slides in from the right with its price and chip (`dwell-swap`). Banner phase 2. If `reallocate` follows, the BudgetBar segments animate and the moved segment gets its outline.
3. **Re-check.** The red line goes to `re-checking` (dashed, moving dash) until the new check row arrives. Never jump straight from red to green without a check row.
4. **Green.** On the pass check: line crossfades to `pass`, the badge pops, banner phase 3 `Fixed: socket now matches.` for 2 s, then the stage un-dims.

**Two lines red at once** (answers the brief's question 8.5):

- One `clash` step with several parts in `with`: all those lines go red together in step 1, the banner reads `Clash: 2 rules fail` with both plain-words lines stacked, and one `swap` resolves them. Each line then re-checks on its own and turns green (or stays red) independently.
- Two separate `clash` steps: play them one after the other in arrival order. While the first plays, the second line is already red (it is true), but it is not highlighted; the banner shows `1 more clash` on the right. After the first resolves, the second runs steps 1 to 4.
- If a swap leaves a line red, that is a new clash; it queues like any other.
- A fit `knockout` step does not play this sequence today (the bid just leaves; 4.3). If Lane A decides that a knockout of the tentative cheapest pick should play red, swap, green (13.2.8), use the same four steps with the owned part as the second endpoint.

### 6.3 Pointer and keyboard

- Hover a slot: border to `--line-2`, its lines show their labels. Hover a line: label shows, endpoint slots outline.
- Click a slot: focus it (desktop Rail, phone accordion). Click a line: pins its label until Escape or another click.
- Keyboard: Tab order TopBar, BudgetBar (one stop, reads the summary), slots in slot order, then each slot's lines (as buttons with the label as name), then the Rail. Arrow keys move between slots in the 3 x 3 grid. Enter opens. Escape closes the bottom sheet, CallZoom (except while ringing) or a pinned label.

### 6.4 Reduced motion

Under `prefers-reduced-motion: reduce` every transition is instant (globals.css already enforces this). The dwells stay, so the re-plan still reads in order: red holds 1600 ms, the swap appears, `Re-checking` text shows, then green. The banner text carries the story. The typing effect on the sentence is off.

---

## 7. Responsive behaviour summary

| Element | 1440 px | 390 px |
|---|---|---|
| BuildStage | 3 x 3 exploded grid with SVG lines | SlotRow list; CompatRows instead of lines |
| Rail | right column: StepLog + ArenaPanel | StepLog at the bottom (collapsed); ArenaPanel inside the expanded SlotRow |
| AdvocateCard | inline under its BidRow or in the Rail | bottom sheet |
| ComparisonCard | full card under the bids | compact row, details in a bottom sheet |
| ReplanBanner | bar across the bottom of the stage | sticky under the BudgetBar |
| BudgetBar | 12 px, labels above | 8 px, total only; tap for per-part breakdown |
| CallZoom | 720 x 520 centered card | full screen |
| ReceiptList | replaces the Rail | replaces the slot list, with "Show build" |
| Touch targets | n/a | at least 44 x 44 px |

---

## 8. Empty, loading, pending and error states

### 8.1 Loading and connection

| Case | Show |
|---|---|
| Connecting to the market | slot skeletons (part labels only, no budgets), TopBar text `Connecting to the market` |
| Planner not answered | sentence shown, slots hidden, `Planning the build` |
| Round open, no bids | `No bids yet`, countdown |
| Stage closing | `Closing stage 2` for up to 3 s |
| Check pending | line `unchecked` with `Not checked yet` |
| Lost connection | a top notice `Connection lost, reconnecting`, everything stays as last seen, LiveAge keeps counting (so it ages to stale honestly) |

### 8.2 Lane C data not ready yet (design these as normal states, not errors)

| Gap | What the UI shows |
|---|---|
| Real listings exist only for the GPU (RTX 5070 Ti, Apify snapshots plus Central Computers) | GPU bids show `MIRROR` (dated) or `LIVE` after re-check. CPU, board, RAM, SSD and cooler bids show `SIM` on every row. No "real" styling on SIM rows. |
| Price baselines exist only for the RTX 5070 Ti | Every other part's AdvocateCard shows the note `Price baseline unavailable (unverified)` and the banner `Some checks could not run`. |
| The GPU baseline goes stale at 02:38 PDT Oct 25 unless the refresh runs (Sat 22:00, Sun 06:00) | The UI does not decide staleness. When the advocate stops sending the baseline (`advocate.baseline_unverified` note), the card shows unverified. Never cache the last baseline price in the UI. |
| seller_6 (Central Computers live round) needs a private seed on Vidyut's Mac and has no Market identity | If no `advocate.mirror_not_orderable` bid arrives, the For comparison section is simply absent. Never fake it. |
| Paid Apify run (#347) not done | Nothing on screen shows an agent payment to Apify as LIVE. |
| Listing Injection Screen (PR #352) not on Apify | Shield blocks show Shield's rule ids only; no Actor link. |
| Fit `checks` not in `resolve()` yet | Fallback in 4.3: red from clash and knockout steps, every other line `Not checked yet`. |
| #345 shape not posted | ReceiptList, LiveAge and CallZoom read through the adapter with sample data marked `SampleOnly` (existing component). |

### 8.3 Errors

| Case | Show |
|---|---|
| Fit checker could not read a part | BuildVerdictChip `Uncertain`, its `problems[0]`; lines into that part `uncertain` |
| Advocate missing for a bid | AdvocateChip `Not checked`, text `Advocate check missing`; the bid cannot show as Buy |
| Round no deal | Slot `no deal`; the planner decides re-plan or blocked |
| `blocked` | BlockedState (5.13) |
| Call failed or declined | 5.11 states; nothing paid |
| Receipt failed | row `Receipt failed, retrying`; the mandate and payment rows still show |
| Unknown origin | `SIM` (OriginChip default) |

---

## 9. Edge cases

- **Line ends uncertain after a swap.** The build is not a pass. BuildVerdictChip shows `Uncertain`. Whether the planner may lock an uncertain build is Lane A's rule; the UI shows whatever `status` says, and an uncertain line stays amber on the call screen and in the receipts header.
- **Partial build.** While parts are still open, BuildVerdictChip says `PASS for the N rule(s) that could run`, never `PASS`.
- **Same seller wins several parts.** One mandate, several receipt rows under it. `sellers.length` counts distinct sellers.
- **Champion price changes on the live re-check.** Show the new price everywhere (BudgetBar, slot, call total). If the new total goes over the cap, the bar shows over cap and Lane D decides (per #345).
- **Sealed ties.** The UI shows the order from `round_result`; it never ranks on its own.
- **Long item names** (`MSI GeForce RTX 5070 Ti 16G VENTUS 3X PZ OC`): 2 lines in a slot, then ellipsis; full name in the ArenaPanel and on hover.
- **Long reasons.** `check.reason` can run 90 chars (`fit.psu_wattage`). Desktop line labels wrap at 280 px, max 3 lines; phone wraps freely.
- **Many sources.** Show 2 source links, then `+N` opening a popover with all.
- **Zero-dollar impact warnings.** Hide the `$` part.
- **More than 3 warnings.** The advocate already cuts to 3 (vetoes kept). The UI never adds more.
- **Owned part with unknown spec** (case with no GPU clearance). Lines into it are `uncertain`, label `case GPU clearance unknown`.
- **A real store's bid somehow ranks first.** It cannot (veto), but if a ComparisonCard bid ever appears as `champion`, render the slot as `no deal` and log an error. Never show a real store as a winner.
- **Real SF GPU data for the recording** (305 mm case): MSI Ventus 3X PZ OC $1,249.99 (303 mm) fits; ASUS Prime $1,299.99, Prime OC $1,349.99 and ProArt $1,389.99 fit; ASUS TUF (329 mm) is the real `fit.gpu_length` trap, shown as a vetoed or knocked-out BidRow in the GPU arena (not a red line, since the case is owned); ROG Strix has unknown length and never bids.

---

## 10. Accessibility

- **Colour never alone.** Every verdict has an icon, a stroke style and a word (5.4, 5.9). Check by viewing the screen in greyscale: every state must still be readable.
- **Focus visible.** Keep `:focus-visible` from globals.css (2 px `--accent`, 2 px offset). Lines get a focus ring on their midpoint badge.
- **Roles.** BuildStage `role="group"` `aria-label="Build: 8 parts"`. Each slot is a `button` with `aria-label="GPU: MSI Ventus 3X PZ OC, $1,249.99, MIRROR, locked"` (built from fields, not seller text). Each line is a `button` with `aria-label="CPU and motherboard: fits. socket AM5 matches. Source: maker page"`. BudgetBar is `role="img"` with an `aria-label` summary, plus a visually hidden table of segments.
- **Announcements.** One polite live region for the StepLog (new step lines only, at most one per `dwell-step`). One assertive announcement for a clash (`Clash: the processor socket does not match the board`) and one for approved or declined. Never announce bid arrivals or the LiveAge tick.
- **Bottom sheet and CallZoom.** `role="dialog"`, `aria-modal="true"`, labelled by their title, focus trapped, focus returns to the opener on close.
- **Motion.** 6.4.
- **Targets.** 44 x 44 px minimum on phone.
- **Contrast.** Text at least 4.5:1 (section 3.1 values pass on `--canvas` and `--panel`).

---

## 11. Wording rules

### 11.1 Never

- No em dashes or en dashes anywhere user-facing. Use a colon, a comma or a full stop. Ranges use "to" (`60 s to 5 min`).
- Never the word "secure", in any form.
- Never "No problems found" while any check could not run; use "Some checks could not run".
- Never a plain "PASS" for a partial build; use "PASS for the N rule(s) that could run".
- Never call a guess a pass. Unknown is "uncertain" (fit) or "unverified" (advocate checks, condition).
- Never seller-supplied text in a verdict, reason, banner, step or call line. Reasons come from the closed tables.
- Never imply a real store joined, was approved, was paid or was sent an order. Never "partner" except in the sentence "Central Computers is not a partner."
- Never show a price, verdict or spec without its source link and LIVE, MIRROR or SIM label. Dated numbers show their date.

### 11.2 Closed table: fit rule plain words (headline for lines, also used on the call)

| rule_id | Fail headline | Pass word | Uncertain word |
|---|---|---|---|
| `fit.cpu_socket` | The processor socket does not match the board | Socket matches | Socket could not be confirmed |
| `fit.ram_type` | The memory type does not match the board | Memory type matches | Memory type could not be confirmed |
| `fit.ram_slots` | The board does not have enough memory slots for this kit | Enough memory slots | Slot count could not be confirmed |
| `fit.psu_wattage` | Your power supply is below what this card needs | Power supply covers the load | Power need could not be confirmed |
| `fit.gpu_connectors` | Your power supply lacks the connectors this card needs | Power connectors match | Connectors could not be confirmed |
| `fit.gpu_length` | The card is longer than your case allows | Card fits the case | Card length could not be confirmed |
| `fit.cooler_height` | The cooler is taller than your case allows | Cooler fits the case | Cooler height could not be confirmed |
| `fit.cooler_socket` | The cooler does not support this processor socket | Cooler supports the socket | Cooler socket support could not be confirmed |
| `fit.form_factor` | The board does not fit your case | Board fits the case | Board size could not be confirmed |
| `fit.psu_form_factor` | The power supply does not fit your case | Power supply fits the case | Power supply size could not be confirmed |
| `fit.storage` | The drive type does not match what your board supports | Drive type matches | Drive support could not be confirmed |
| `budget.over` | This part is over its budget (plain words to confirm on #344) | n/a | n/a |

The fail headlines are the fit checker's closed set (main, `CALL_SUMMARIES`). The pass and uncertain words are new UI strings; Lane B owns them in one constants file next to `ui.tsx`, reviewed by Lane C.

### 11.3 Closed table: advocate headlines (main and per #287 (open))

`advocate.condition` The listing page shows a different condition than the seller claims. `advocate.recall` This product matches a CPSC recall entry. `advocate.recall_partial` A CPSC recall names a similar model, so check the exact model. `advocate.price` The price is more than 10 percent above its price history. `advocate.spec` This offer is not the condition you asked for. `advocate.record` This seller has a caution record. `advocate.floor` This bid did not pass the price floor check. `advocate.same_seller` Another bid in this round comes from the same seller. `advocate.unsourced` A claim on this bid could not be checked against its listing. `advocate.fit_unknown` Fit could not be confirmed from the listing details. `advocate.unverified` Some checks could not run. `advocate.mirror_not_orderable` This store is shown for comparison only and cannot be bought from here.

Render the `reason` and `text` fields the advocate sends. Do not rewrite them in the UI. This list is for the reviewer.

### 11.4 Fixed UI strings

`Not checked yet`, `Re-checking`, `Fits`, `Uncertain`, `Clash`, `Owned`, `Already installed`, `Sealed`, `Champion`, `Blocked by Shield`, `Some checks could not run`, `Shown for comparison, cannot be bought here.`, `Real store, shown for comparison`, `Nothing was paid.`, `Approved by call`, `Within your allowance, no call needed`, `checked live 12s ago`, `last checked live 14 min ago`, `not re-checked (SIM seller)`.

Before merge, grep the UI for U+2014, U+2013, `secure`, `No problems found` and a bare `"PASS"`.

---

## 12. Component checklist (Lane B)

- [ ] Tokens added to `globals.css` (3.1 to 3.4), no reuse of `--mint`, `--coral` or `--amber` for verdicts
- [ ] TopBar: typing, planned, approved
- [ ] BudgetBar: open, locked, moved, over cap, owned chips; phone compact
- [ ] Slot and SlotRow: planned, waiting, live, stage closing, round won, locked, picked after re-plan, swapped, no deal, blocked, owned
- [ ] CompatLine and CompatRow: unchecked, re-checking, pass, uncertain, fail; multi-rule pairs; power fork; labels and sources
- [ ] ArenaPanel: StageDots, countdown, sealed rows, empty, no bids
- [ ] BidRow: sealed, advancing, champion, out last place, advocate veto, Shield block, planner knockout
- [ ] AdvocateCard: buy, caution, veto; warnings with dollar impact; info notes; "Some checks could not run"; condition unverified; bottom sheet at 390
- [ ] ComparisonCard: desktop card, phone row and sheet; never ranked, never paid
- [ ] BuildVerdictChip: pass, partial, uncertain, fail, not checked
- [ ] StepLog: every step kind with icon
- [ ] ReplanBanner: three phases, multi-rule clash, queued clash count
- [ ] CallZoom: ringing, connected, why, approved, declined, no answer, failed; inside-allowance toast
- [ ] ReceiptList: grouped by seller, mandates, receipt statuses
- [ ] LiveAge: fresh, aging, stale, re-check failed, price changed, SIM
- [ ] BlockedState
- [ ] List view fallback (`?view=list`)
- [ ] Reduced motion pass, greyscale pass, keyboard-only pass, 390 px no horizontal scroll
- [ ] Recording: 6-part build at 1440 and 390 with one red to green re-plan

---

## 13. Open questions

### 13.1 Answered in this spec (from the brief)

1. Uncertain versus unchecked line: uncertain is amber, dotted, a question mark in a circle and the word "Uncertain" plus the reason; unchecked is grey, dashed, a hollow dot and "Not checked yet" (5.4).
2. Advocate warnings at 390 px: chip and count on the row; the full card in a bottom sheet (5.7).
3. MIRROR comparison card: its own "For comparison" section, dashed sky border, storefront icon, full-opacity real price, MIRROR chip with date, the not-a-partner line, no verdict chip (5.8).
4. "Checked live Ns ago" ageing: solid under 60 s, outline to 5 min, muted with a clock from 5 min (5.14). Lane D may tighten the thresholds.
5. Two red lines at once: one clash with several `with` parts goes red together and resolves with one swap; separate clashes queue in order with a "1 more clash" count (6.2).

### 13.2 Still open (owner in brackets)

1. **[Abhinav, #344] Fit checks in `resolve()`.** Please add the full `check_build()` result as `checks` in `resolve()` output, and a fresh one with each `swap` step (or a `recheck` step carrying `rule_id`, `verdict`, `reason`, `sources`, `origin`). Without it no line can turn green.
2. **[Abhinav, #344] Demo case size.** The #344 example uses `case.gpu_max_mm: 330`. Our real SF data assumes a 305 mm case. At 330 mm the 329 mm ASUS TUF passes and the "card too long" moment disappears. Use 305 mm for the recording (Fractal North clearance and the 155 mm cooler case are the other real example).
3. **[Abhinav, #344] `budget.over` plain words** for the closed table (11.2).
4. **[Abhinav, #344] Does an uncertain line block `locked`?** The UI shows whatever `status` says.
5. **[Vidyut, #345] Field names** for `build_id`, `checked_at`, re-check status, mandates, receipts, call state and the "why" lines (4.7).
6. **[Vidyut, #345] Bid projection for build rounds**: seller label, price after close, origin, Shield result per bid.
7. **[Vedant and Vidyut] Status colours.** The app is black and white on purpose. This spec adds a scoped green, red and amber set for fit lines only, always paired with icon, stroke and word. Confirm, or pick black and white strokes only (solid, dotted, dashed, heavy) and keep the icons.
8. **[Vidyut and Abhinav] Which red line the recording shows.** Under the #344 contract the red, swap, green beat needs a clash between two picks, so the candidate is `fit.cpu_socket` (CPU and board, SIM parts). The real ASUS TUF length trap is a per-bid knockout or advocate veto in the GPU arena. If you want the real GPU data to drive the red line, Lane A must make a fit knockout of the tentative cheapest pick emit the red, swap, green sequence (6.2, last bullet).
10. **[Vidyut and Vedant, #345 and #363] Mandate for a swapped pick.** `resolve()` tries offers cheapest first, so after a clash the new pick is a seller whose `round_result.status` is not `champion`. #363 says `create_mandate` reads only the `champion` row, so as written the swapped part cannot get a mandate or a receipt. Beat 5 breaks end to end unless the build path mandates the planner's `picks`, or the swap re-runs that part's round.
9. **[Anoop] Per-part real listings and baselines** for CPU, board, RAM, SSD and cooler: next Lane C job. Until then those slots are SIM (8.2).
