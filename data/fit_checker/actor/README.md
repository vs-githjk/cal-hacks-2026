# PC Build Compatibility Checker: will these parts fit?

**Check a PC build before you buy it.** List the parts (CPU, motherboard, RAM, graphics card, power supply, case, cooler, drives). The Actor runs 12 compatibility rules and returns **pass**, **fail** or **uncertain** for each one, with the numbers it compared and the **maker spec pages** behind them.

It never guesses. A spec nobody knows makes that rule **uncertain**, not a pass, so an "all clear" means every rule was actually checked.

Built for **AI shopping agents**. Our own, [Tech Bazaar](https://github.com/vs-githjk/cal-hacks-2026), uses it to veto a part that will not fit before any money moves. It's also useful to PC builders, resellers and anyone quoting a build.

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
| `fit.storage` | NVMe needs an M.2 slot, SATA needs a port | no slot or port |

## Real example (the default input)

A Ryzen 7 9700X build with an MSI RTX 5070 Ti Gaming Trio OC, a Thermalright Peerless Assassin 120 SE and a Fractal Design North case:

**`FAIL: cooler height 155 mm exceeds case clearance 145 mm (11 checks: 10 pass, 1 fail, 0 uncertain)`**

The cooler height comes from thermalright.com and the case clearance from fractal-design.com. The card's 338 mm length (msi.com) fits the North's 355 mm, and the 750 W PSU meets MSI's 750 W recommendation.

## Input

Give each part a `name` plus any specs you know. Where you leave a spec out and we hold maker data for that **exact** part, we fill it in and cite the maker page. Your own numbers always win.

```json
{
  "parts": {
    "cpu": {"name": "AMD Ryzen 7 9700X", "vendor": "AMD", "socket": "AM5", "tdp_w": 65},
    "motherboard": {"name": "Asus PRIME B650-PLUS WIFI", "socket": "AM5", "form_factor": "ATX", "memory_slots": 4},
    "memory": {"name": "32GB DDR5-6000", "type": "DDR5", "form": "DIMM", "modules": 2},
    "gpu": {"name": "MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC"},
    "psu": {"name": "Corsair RM750e", "wattage": 750, "form_factor": "ATX", "pcie_16pin": 1, "pcie_8pin": 3},
    "case": {"name": "Fractal Design North", "max_gpu_length_mm": 355, "motherboard_form_factors": ["ATX", "Micro ATX", "Mini ITX"], "psu_form_factors": ["ATX"]},
    "cooler": {"name": "Thermalright Peerless Assassin 120 SE"}
  }
}
```

**Spec fields by part:**
- **cpu:** `socket`, `vendor` (AMD or Intel), `tdp_w` or `max_power_w`, `microarchitecture`
- **motherboard:** `socket`, `form_factor`, `memory_type`, `memory_form`, `memory_slots`, `memory_max_speed_mhz`, `chipset_series`, `m2_slots`, `sata_ports`
- **memory:** `type` (DDR4, DDR5), `form` (DIMM, SO-DIMM), `modules`, `speed_mhz`
- **gpu:** `chipset` (read from the name if left out), `length_mm`, `board_power_w`, `rec_psu_w`
- **psu:** `wattage`, `form_factor`, `pcie_16pin`, `pcie_8pin`
- **case:** `max_gpu_length_mm`, `max_cooler_height_mm`, `motherboard_form_factors`, `psu_form_factors`, `radiator_mounts_mm`, `type`
- **cooler:** `height_mm`, `sockets`, or `type: "aio"` with `radiator_mm`
- **storage** (a list): `interface` (for example "M.2 PCIe 4.0 X4" or "SATA 6.0 Gb/s")

To check many builds in one run, use **Batch**: a list of `{id, parts}`.

## Output

One dataset row per rule:

```json
{"build_id": "build-1", "build_verdict": "fail", "rule_id": "fit.cooler_height", "verdict": "fail",
 "reason": "cooler height 155 mm exceeds case clearance 145 mm",
 "parts": ["Thermalright Peerless Assassin 120 SE", "Fractal Design North"],
 "sources": ["fractal-design.com: GPU 355 (300 with 360 front radiator), cooler 145, ATX PSU", "thermalright.com: 155 mm; AM4, AM5, 115X, 1200, 1700, 1851"]}
```

The run's status line gives the verdict, and the key-value store's `OUTPUT` record holds every build with its parts, the specs we filled in and their sources.

## Maker data we hold (dated Oct 24 2026)

- **Graphics cards:** RTX 5070 Ti models from MSI (Gaming Trio, Ventus 3X, Vanguard), Gigabyte (Gaming OC, Windforce), ASUS (Prime, ProArt, TUF) and PNY, with length and recommended PSU. Chipset power tables cover 30 cards: GeForce RTX 30, 40 and 50 series, and Radeon RX 7000 and RX 9070.
- **Coolers:** Thermalright Peerless Assassin 120 SE, Noctua NH-D15, NH-U12S, NH-L12S, DeepCool AK400, be quiet! Dark Rock Pro 5.
- **Cases:** Fractal Design North, Cooler Master MasterBox NR200P, NZXT H5 Flow.
- **Boards:** Asus PRIME B650-PLUS WIFI, PRIME Z270-A, MSI B550 GAMING GEN3, PRO Z790-A WIFI, PRO Z890-A WIFI, PRO B760M-A DDR4 II.

For any other part, give its specs; the rules work the same.

## Use it from an AI agent or your code

**AI agents (MCP):** `https://mcp.apify.com/?actors=anoopibrampur/pc-build-compatibility-checker` adds it as a tool in any MCP client.

**API:**

```bash
curl -X POST "https://api.apify.com/v2/acts/anoopibrampur~pc-build-compatibility-checker/run-sync-get-dataset-items" \
  -H "Authorization: Bearer YOUR_APIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"parts": {"gpu": {"name": "MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC"}, "case": {"name": "NZXT H5 Flow", "max_gpu_length_mm": 365}}}'
```

## FAQ

**Why "uncertain" instead of a best guess?** A wrong "fits" costs a return. If a spec is missing, we say so and name it in the reason, so you know exactly what to look up.

**Does it browse store pages?** No. It works from your specs and our dated maker data, so it is fast and never blocked.

**What does "est. load" mean in the PSU rule?** CPU power plus GPU board power plus 75 W for the rest of the system, then 25% headroom, rounded up to 10 W. The GPU maker's recommendation is used when it is higher.

## Source

[github.com/vs-githjk/cal-hacks-2026](https://github.com/vs-githjk/cal-hacks-2026), `data/fit_checker/`. Labels: maker data is MIRROR (a dated read of maker pages).
