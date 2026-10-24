# PC Build Compatibility Checker: will these parts fit?

**Check a PC build before you buy it.** Fill in the parts (CPU, motherboard, RAM, graphics card, power supply, case, cooler). The Actor runs up to **12 compatibility rules** and returns **pass**, **fail** or **uncertain** for each one, with the numbers it compared and the **maker spec pages** behind them.

It never guesses. A spec nobody knows makes that rule **uncertain**, not a pass. A build with parts missing never gets a plain PASS: the summary says which rules could run and which parts were not given, for example `PASS for the 1 rule(s) that could run; not given: memory, gpu, psu, case, cooler`. A part we cannot read, an unknown key or a bad number makes the build **uncertain** and names it.

Built for **AI shopping agents**. Our own, [Tech Bazaar](https://github.com/vs-githjk/cal-hacks-2026), uses it to veto a part that will not fit before any money moves. It is just as useful to PC builders, resellers and anyone quoting a build.

## What it checks

| Rule | Compares | Fails when |
|---|---|---|
| `fit.cpu_socket` | CPU socket vs board socket (and LGA1151 chipset generation) | sockets differ |
| `fit.ram_type` | RAM generation vs board | DDR4 kit on a DDR5 board, or the reverse |
| `fit.ram_form` | DIMM vs SO-DIMM | laptop memory on a desktop board |
| `fit.ram_slots` | modules vs slots | 4 sticks, 2 slots |
| `fit.psu_wattage` | estimated load + 25% headroom, and the GPU maker's recommended PSU | the PSU is too small |
| `fit.gpu_connectors` | GPU power cables vs PSU (16-pin 12V-2x6 or 8-pin) | not enough cables |
| `fit.gpu_length` | card length vs case GPU clearance | card is longer than the case allows |
| `fit.cooler_height` | air cooler height vs case clearance (or AIO radiator vs mounts) | cooler too tall |
| `fit.cooler_socket` | cooler's supported sockets vs CPU | socket not listed |
| `fit.form_factor` | board size vs case | an ATX board in a mini-ITX case |
| `fit.psu_form_factor` | PSU size vs case | an ATX PSU in an SFX-only case |
| `fit.storage` | NVMe needs an M.2 slot, SATA needs a port | no slot or port (runs once per drive you list) |

A rule runs when both of its parts are in the build, so a build with no drives runs 11.

## Real example (the default input)

Open the Actor and press **Start**: the form is filled with a Ryzen 7 9700X build with an MSI RTX 5070 Ti Gaming Trio OC, a Thermalright Peerless Assassin 120 SE and a Fractal Design North case. It returns:

**`FAIL: cooler height 155 mm exceeds case clearance 145 mm (11 checks: 10 pass, 1 fail, 0 uncertain)`**

The cooler height comes from thermalright.com and the case clearance from fractal-design.com. The card's 338 mm length (msi.com) fits the North's 355 mm, and the 750 W PSU meets MSI's 750 W recommendation. The build has no drive listed, so the 12th rule (storage) does not run.

## How to use it

1. **Your parts:** type each part's name. For parts we hold maker data on (below), the name alone fills in the specs.
2. **Specs you know:** pick or type what you know (socket, RAM generation, PSU wattage, case clearance). Leave a field empty when you are not sure; that rule then says uncertain instead of guessing.
3. Press **Start**. Each rule is one row in the results table, and the run's status line gives the verdict.

To check many builds in one run, or to give specs the form does not have (drives, AIO radiators, chipset), use **Advanced**: a JSON build or a batch of builds.

## Input

From the API, send the form's fields:

```json
{
  "cpu": "AMD Ryzen 7 9700X", "cpuSocket": "AM5", "cpuVendor": "AMD", "cpuTdpW": 65,
  "motherboard": "Asus PRIME B650-PLUS WIFI", "boardSocket": "AM5", "boardFormFactor": "ATX", "boardMemorySlots": 4,
  "memory": "32GB (2x16GB) DDR5-6000", "memoryType": "DDR5", "memoryForm": "DIMM", "memoryModules": 2,
  "gpu": "MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC",
  "psu": "Corsair RM750e", "psuWattage": 750, "psuFormFactor": "ATX", "psu16pin": 1, "psu8pin": 3,
  "case": "Fractal Design North", "caseMaxGpuLengthMm": 355, "caseBoardSizes": ["ATX", "Micro ATX", "Mini ITX"], "casePsuSizes": ["ATX"],
  "cooler": "Thermalright Peerless Assassin 120 SE"
}
```

Or give the same build as JSON parts in `parts` (it overrides the form for any part it names), or many builds in `builds` as a list of `{id, parts}`:

```json
{"parts": {"gpu": {"name": "MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC"}, "case": {"name": "NZXT H5 Flow", "max_gpu_length_mm": 365}}}
```

**JSON spec fields by part:**
- **cpu:** `socket`, `vendor` (AMD or Intel), `tdp_w` or `max_power_w`, `microarchitecture`
- **motherboard:** `socket`, `form_factor`, `memory_type`, `memory_form`, `memory_slots`, `memory_max_speed_mhz`, `chipset_series`, `m2_slots`, `sata_ports`
- **memory:** `type` (DDR4, DDR5), `form` (DIMM, SO-DIMM), `modules`, `speed_mhz`
- **gpu:** `chipset` (read from the name if left out), `length_mm`, `board_power_w`, `rec_psu_w`
- **psu:** `wattage`, `form_factor`, `pcie_16pin`, `pcie_8pin`
- **case:** `max_gpu_length_mm`, `max_cooler_height_mm`, `motherboard_form_factors`, `psu_form_factors`, `radiator_mounts_mm`, `type`
- **cooler:** `height_mm`, `sockets`, or `type: "aio"` with `radiator_mm`
- **storage** (a list): `interface` (for example "M.2 PCIe 4.0 X4" or "SATA 6.0 Gb/s")

Your own numbers always win over our maker data. Sockets and memory types are read in any case (`am5` is `AM5`), numbers may be strings (`"300"`), and a size of 0 counts as unknown.

## Output

One dataset row per rule:

```json
{"build_id": "build-1", "build_verdict": "fail", "rule_id": "fit.cooler_height", "verdict": "fail",
 "reason": "cooler height 155 mm exceeds case clearance 145 mm",
 "parts": ["Thermalright Peerless Assassin 120 SE", "Fractal Design North"],
 "sources": ["fractal-design.com: GPU 355 (300 with 360 front radiator), cooler 145, ATX PSU", "thermalright.com: 155 mm; AM4, AM5, 115X, 1200, 1700, 1851"],
 "origin": "MIRROR (dated maker data, Oct 24 2026)"}
```

`origin` says whether a row's numbers came from our dated maker data or only from your input. A figure for a sibling model is cited with that caveat, and GPU board power and cable needs taken from NVIDIA or AMD chipset reference figures are cited as estimates. The key-value store's `OUTPUT` record holds every build with its verdict, `complete`, `rules_run`, `missing_parts`, the specs we filled in and their sources.

## Maker data we hold (dated Oct 24 2026)

- **Graphics cards:** RTX 5070 Ti models from MSI (Gaming Trio, Ventus 3X, Vanguard), Gigabyte (Gaming OC, Windforce), ASUS (Prime, ProArt, TUF) and PNY, with length and recommended PSU. The brand must be in the name (a Zotac "Prime" is not an ASUS Prime). Chipset power tables cover 30 cards: GeForce RTX 30, 40 and 50 series, and Radeon RX 7000 and RX 9070.
- **Coolers:** Thermalright Peerless Assassin 120 SE, Noctua NH-D15, NH-U12S, NH-L12S, DeepCool AK400, be quiet! Dark Rock Pro 5.
- **Cases:** Fractal Design North, Cooler Master MasterBox NR200P (we use its 153 mm glass-panel cooler clearance, the lower of its two figures), NZXT H5 Flow.
- **Boards:** Asus PRIME B650-PLUS WIFI, PRIME Z270-A, MSI B550 GAMING GEN3, PRO Z790-A WIFI, PRO Z890-A WIFI, PRO B760M-A DDR4 II.

For any other part, give its specs; the rules work the same.

## Pricing

**$0.005 per build checked** (pay per event), and Apify platform usage is included.

| You check | You pay |
|---|---|
| 1 build | $0.005 |
| 100 builds | $0.50 |
| 1,000 builds | $5.00 |
| A build with nothing to compare (no pair of parts) | free |

Each run also has Apify's run start event of $0.00005. A build is charged only when at least one rule ran, and it is charged before its results are delivered. When your spending limit is reached the run stops and the summary says how many builds were not run. A restarted run never charges a build twice.

## Agents can pay per call (experimental)

An AI agent with a stablecoin wallet and **no Apify account** can pay for this Actor itself, through [Apify's Agent General Interface](https://agi.apify.com/AGENTS.md):

1. The agent asks for a prepaid token: `GET https://agi.apify.com/protocols/x402/prepaid-tokens?amount=1&currency=usd` answers **HTTP 402** with a payment challenge. x402 takes USDC on Base, or USDC or USDT on Solana. MPP (`/protocols/mpp/...`) takes USDC.e or pathUSD on Tempo, or USDC or USDT on Solana.
2. The agent's wallet pays it (for example `npx awal x402 pay ...`, `mppx ...` or `pay.sh`), and Apify returns a token with a hard spend cap: at least $1, it expires after 14 days, and unused balance is not refunded.
3. The agent runs this Actor with `Authorization: Bearer <token>`, and each build is metered against that balance. This works because the Actor uses limited permissions.

**What we have verified (Oct 24 2026):** our probe, [`scripts/apify_agent_pay_probe.py`](https://github.com/vs-githjk/cal-hacks-2026/blob/main/scripts/apify_agent_pay_probe.py), reaches the 402 pay wall for a prepaid token and for a proxied run of this Actor. That is *reached, not paid*. This section will say LIVE only after a real paid run.

## Use it from an AI agent or your code

**AI agents (MCP):** `https://mcp.apify.com?tools=anoopibrampur/pc-build-compatibility-checker` adds it as a tool in any MCP client.

**API (one call, results in the response):**

```bash
curl -X POST "https://api.apify.com/v2/acts/anoopibrampur~pc-build-compatibility-checker/run-sync-get-dataset-items" \
  -H "Authorization: Bearer YOUR_APIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"gpu": "MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC", "case": "NZXT H5 Flow", "caseMaxGpuLengthMm": 365}'
```

## Our other Actor

- [**Listing Claim Checker: Price, Stock, Condition**](https://apify.com/anoopibrampur/tech-bazaar-claim-check) checks what a seller says (price, stock, condition, warranty, returns) against the live product page, before you buy the parts this Actor said will fit.

## FAQ

**Why "uncertain" instead of a best guess?** A wrong "fits" costs a return. If a spec is missing, we say so and name it in the reason, so you know exactly what to look up.

**Does it browse store pages?** No. It works from your specs and our dated maker data, so it is fast and never blocked.

**What does "est. load" mean in the PSU rule?** CPU power plus GPU board power plus 75 W for the rest of the system, then 25% headroom, rounded up to 10 W. The GPU maker's recommendation is used when it is higher.

## Source

[github.com/vs-githjk/cal-hacks-2026](https://github.com/vs-githjk/cal-hacks-2026), `data/fit_checker/`. Labels: maker data is MIRROR (a dated read of maker pages). The Actor is built from this folder after `./bundle.sh` copies the fit checker into `src/data/`.
