"""Hand tables the dataset lacks. Hand-entered from AMD, Intel and NVIDIA spec pages; rows marked
`# verify` still need a second person to check them against the maker's page (see data/README.md).
A value we do not know is left out, so the checker answers "uncertain" instead of guessing."""

# CPU microarchitecture -> socket (desktop parts only). Threadripper, EPYC, Xeon and Intel X-series
# share microarchitecture names with desktop parts on other sockets, so normalize.py leaves them unknown.
MICROARCH_SOCKET = {
    "Zen 5": "AM5", "Zen 4": "AM5",
    "Zen 3": "AM4", "Zen 2": "AM4", "Zen+": "AM4", "Zen": "AM4",
    "Arrow Lake": "LGA1851",
    "Raptor Lake Refresh": "LGA1700", "Raptor Lake": "LGA1700", "Alder Lake": "LGA1700",
    "Rocket Lake": "LGA1200", "Comet Lake": "LGA1200",
    "Coffee Lake Refresh": "LGA1151", "Coffee Lake": "LGA1151", "Kaby Lake": "LGA1151", "Skylake": "LGA1151",
    "Broadwell": "LGA1150", "Haswell Refresh": "LGA1150", "Haswell": "LGA1150",
    "Ivy Bridge": "LGA1155", "Sandy Bridge": "LGA1155",
}

# LGA1151 is two incompatible generations behind one name: chipset series allowed per microarchitecture.
LGA1151_CHIPSET_SERIES = {"Skylake": {1, 2}, "Kaby Lake": {1, 2}, "Coffee Lake": {3}, "Coffee Lake Refresh": {3}}

# (socket, chipset series digit, microarchitecture) -> (verdict, note). Missing = no note.
BIOS_RULES = {
    ("AM4", 3, "Zen 3"): ("uncertain", "Ryzen 5000 on a 300-series board depends on that board's BIOS; check its CPU support list"),
    ("AM4", 4, "Zen 3"): ("pass", "needs a BIOS with Ryzen 5000 support (AGESA 1.2.0.0 or later); update before swapping the CPU"),
    ("AM4", 5, "Zen 3"): ("pass", "early 500-series boards may need a BIOS update for Ryzen 5000"),
    ("AM4", 5, "Zen"): ("uncertain", "AMD does not list Ryzen 1000 support on most 500-series boards"),
    ("AM4", 5, "Zen+"): ("uncertain", "AMD does not list Ryzen 2000 support on most 500-series boards"),
    ("AM5", 6, "Zen 5"): ("pass", "600-series boards need a BIOS with Ryzen 9000 support (AGESA 1.2.0.0 or later)"),
    ("LGA1700", 6, "Raptor Lake"): ("pass", "600-series boards need a BIOS update for 13th gen Core"),
    ("LGA1700", 6, "Raptor Lake Refresh"): ("pass", "600-series boards need a BIOS update for 14th gen Core"),
    ("LGA1700", 7, "Raptor Lake Refresh"): ("pass", "early 700-series boards may need a BIOS update for 14th gen Core"),
}

# Board memory type by socket when the board name does not say. LGA1700 and LGA1151 boards come in two types.
SOCKET_MEMORY = {"AM5": "DDR5", "LGA1851": "DDR5", "AM4": "DDR4", "LGA1200": "DDR4", "LGA1150": "DDR3", "LGA1155": "DDR3"}

# Every board we know of on these sockets has at least one M.2 NVMe slot.
SOCKETS_WITH_M2 = {"AM5", "LGA1851", "LGA1700"}

# Case type (dataset wording) -> board form factors it takes. EATX in a mid tower varies by case, so it is absent.
CASE_TYPE_BOARDS = {
    "ATX Full Tower": {"EATX", "ATX", "Micro ATX", "Mini ITX"},
    "ATX Mid Tower": {"ATX", "Micro ATX", "Mini ITX"},
    "ATX Mini Tower": {"ATX", "Micro ATX", "Mini ITX"},
    "ATX Desktop": {"ATX", "Micro ATX", "Mini ITX"},
    "ATX Test Bench": {"ATX", "Micro ATX", "Mini ITX"},
    "MicroATX Mid Tower": {"Micro ATX", "Mini ITX"},
    "MicroATX Mini Tower": {"Micro ATX", "Mini ITX"},
    "MicroATX Desktop": {"Micro ATX", "Mini ITX"},
    "MicroATX Slim": {"Micro ATX", "Mini ITX"},
    "Mini ITX Tower": {"Mini ITX"},
    "Mini ITX Desktop": {"Mini ITX"},
    "Mini ITX Test Bench": {"Mini ITX"},
}

# Case type -> PSU form factors for towers (they take ATX; SFX needs a bracket). Small cases vary, so they are absent.
CASE_TYPE_PSU = {t: {"ATX"} for t in CASE_TYPE_BOARDS if "ITX" not in t}

# GPU chipset -> board power (W), maker's recommended PSU (W), and reference power connector.
# connector: ("16pin", min 8-pin cables for the included adapter) or ("8pin", count). None = varies by card.
GPU_POWER = {
    "RTX 5090": {"board_power_w": 575, "rec_psu_w": 1000, "connector": ("16pin", 4)},
    "RTX 5080": {"board_power_w": 360, "rec_psu_w": 850, "connector": ("16pin", 3)},
    "RTX 5070 Ti": {"board_power_w": 300, "rec_psu_w": 750, "connector": ("16pin", 3)},  # verify adapter count
    "RTX 5070": {"board_power_w": 250, "rec_psu_w": 650, "connector": ("16pin", 2)},
    "RTX 5060 Ti": {"board_power_w": 180, "rec_psu_w": 600, "connector": None},
    "RTX 5060": {"board_power_w": 145, "rec_psu_w": 550, "connector": None},
    "RTX 4090": {"board_power_w": 450, "rec_psu_w": 850, "connector": ("16pin", 3)},
    "RTX 4080 SUPER": {"board_power_w": 320, "rec_psu_w": 750, "connector": ("16pin", 3)},
    "RTX 4080": {"board_power_w": 320, "rec_psu_w": 750, "connector": ("16pin", 3)},
    "RTX 4070 Ti SUPER": {"board_power_w": 285, "rec_psu_w": 700, "connector": ("16pin", 2)},
    "RTX 4070 Ti": {"board_power_w": 285, "rec_psu_w": 700, "connector": ("16pin", 2)},
    "RTX 4070 SUPER": {"board_power_w": 220, "rec_psu_w": 650, "connector": None},
    "RTX 4070": {"board_power_w": 200, "rec_psu_w": 650, "connector": None},
    "RTX 4060 Ti": {"board_power_w": 165, "rec_psu_w": 550, "connector": None},
    "RTX 4060": {"board_power_w": 115, "rec_psu_w": 550, "connector": None},
    "RTX 3090 Ti": {"board_power_w": 450, "rec_psu_w": 850, "connector": None},
    "RTX 3090": {"board_power_w": 350, "rec_psu_w": 750, "connector": None},
    "RTX 3080 Ti": {"board_power_w": 350, "rec_psu_w": 750, "connector": None},
    "RTX 3080": {"board_power_w": 320, "rec_psu_w": 750, "connector": None},
    "RTX 3070 Ti": {"board_power_w": 290, "rec_psu_w": 750, "connector": None},
    "RTX 3070": {"board_power_w": 220, "rec_psu_w": 650, "connector": None},
    "RTX 3060 Ti": {"board_power_w": 200, "rec_psu_w": 600, "connector": None},
    "RTX 3060": {"board_power_w": 170, "rec_psu_w": 550, "connector": None},
    "RX 9070 XT": {"board_power_w": 304, "rec_psu_w": None, "connector": None},  # verify
    "RX 9070": {"board_power_w": 220, "rec_psu_w": None, "connector": None},  # verify
    "RX 7900 XTX": {"board_power_w": 355, "rec_psu_w": 800, "connector": None},
    "RX 7900 XT": {"board_power_w": 315, "rec_psu_w": 750, "connector": None},
    "RX 7800 XT": {"board_power_w": 263, "rec_psu_w": 700, "connector": None},
    "RX 7700 XT": {"board_power_w": 245, "rec_psu_w": 700, "connector": None},
    "RX 7600": {"board_power_w": 165, "rec_psu_w": 550, "connector": None},
}

# Power budget. AMD socket power (PPT) is 1.35x TDP. Intel 125 W desktop parts are budgeted at 253 W
# (Intel's highest PL2 for them), other Intel parts at 2x TDP. Conservative on purpose.
AMD_PPT_FACTOR = 1.35
INTEL_125W_BUDGET_W = 253
REST_OF_SYSTEM_W = 75
PSU_HEADROOM = 1.25
