// The build panel's view of agents/buyer/planner.py: plan() then resolve() over one round per part.
// SAMPLE_BUILD is that planner's own SIM run (python -m agents.buyer.build_plan_demo, 2026-10-24), not live data.

export type StepKind = "plan" | "knockout" | "clash" | "swap" | "reallocate" | "pick" | "locked" | "blocked";
export interface BuildStep { kind: StepKind; line: string; part?: string; with?: string[]; rule_id?: string }
/** origin: the listing's label (MIRROR or SIM) when the build came from the market feed. */
export interface BuildPick { seller: string; priceCents: number; name: string; origin?: "LIVE" | "MIRROR" | "SIM" }
export interface BuildResult {
  owned: Record<string, string>;
  status: "locked" | "blocked" | "open";
  totalCents: number;
  capCents: number;
  sellers: string[];
  picks: Record<string, BuildPick>;
  budgets: Record<string, number>;
  steps: BuildStep[];
  /** The build's own label from the feed; absent on SAMPLE_BUILD, which is SIM. */
  origin?: "LIVE" | "MIRROR" | "SIM";
}

export const PARTS = ["gpu", "cpu", "motherboard", "memory", "storage", "cooler"] as const;
export const PART_NAMES: Record<string, string> = {
  gpu: "GPU", cpu: "CPU", motherboard: "Board", memory: "RAM", storage: "SSD", cooler: "Cooler", psu: "Power supply", case: "Case",
};

export interface PartRow { part: string; label: string; state: "locked" | "swapped" | "open"; name: string; seller: string; price: number | null; budget: number; overBy: number; origin?: BuildPick["origin"] }

/** One row per part in plan order: what won, from whom, against its budget; a part that clashed and was swapped says so. */
export function partRows(b: BuildResult): PartRow[] {
  const swapped = new Set(b.steps.filter((s) => s.kind === "swap").map((s) => s.part));
  return PARTS.filter((p) => p in b.budgets).map((part) => {
    const pick = b.picks[part];
    const budget = Math.round(b.budgets[part] / 100); // whole dollars, like the plan line
    const price = pick ? pick.priceCents / 100 : null;
    return {
      part, label: PART_NAMES[part], budget, price,
      state: !pick ? "open" : swapped.has(part) ? "swapped" : "locked",
      name: pick?.name ?? "Round open", seller: pick?.seller ?? "", origin: pick?.origin,
      overBy: price !== null && price > budget ? Math.round((price - budget) * 100) / 100 : 0,
    };
  });
}

/** Steps shown up to `upTo` (the replay position); the plan line is always first. */
export function stepsUpTo(b: BuildResult, upTo: number): BuildStep[] {
  return b.steps.slice(0, Math.max(1, Math.min(upTo, b.steps.length)));
}

export const SAMPLE_BUILD: BuildResult = {
  "owned": {
    "psu": "750 W PSU",
    "case": "Owned case"
  },
  "status": "locked",
  "totalCents": 198800,
  "capCents": 200000,
  "sellers": [
    "Amazon",
    "B&H",
    "Best Buy",
    "Central Computers"
  ],
  "picks": {
    "gpu": {
      "seller": "Central Computers",
      "priceCents": 124900,
      "name": "RTX 5070 Ti"
    },
    "cpu": {
      "seller": "Best Buy",
      "priceCents": 27900,
      "name": "Ryzen 7 7700X"
    },
    "motherboard": {
      "seller": "B&H",
      "priceCents": 18900,
      "name": "B650 board"
    },
    "memory": {
      "seller": "Amazon",
      "priceCents": 9900,
      "name": "32 GB DDR5"
    },
    "storage": {
      "seller": "Best Buy",
      "priceCents": 11900,
      "name": "2 TB NVMe"
    },
    "cooler": {
      "seller": "Central Computers",
      "priceCents": 5300,
      "name": "Low cooler"
    }
  },
  "budgets": {
    "gpu": 126585,
    "cpu": 29006,
    "motherboard": 18033,
    "memory": 10291,
    "storage": 12618,
    "cooler": 6500
  },
  "steps": [
    {
      "kind": "plan",
      "line": "Plan: GPU ~$1,266, CPU ~$284, board ~$172, RAM ~$101, SSD ~$122, cooler ~$56. Your power supply and case stay."
    },
    {
      "kind": "knockout",
      "part": "gpu",
      "rule_id": "fit.gpu_length",
      "line": "GPU: Best Buy out, GPU length 336 mm exceeds case clearance 305 mm."
    },
    {
      "kind": "pick",
      "part": "gpu",
      "line": "GPU: RTX 5070 Ti from Central Computers, $1,249."
    },
    {
      "kind": "pick",
      "part": "cpu",
      "line": "CPU: Ryzen 7 7700X from Best Buy, $279."
    },
    {
      "kind": "clash",
      "part": "motherboard",
      "with": [
        "cpu"
      ],
      "rule_id": "fit.cpu_socket",
      "line": "Clash: B760 board vs your CPU: CPU socket AM5 does not match board socket LGA1700."
    },
    {
      "kind": "swap",
      "part": "motherboard",
      "line": "Swapped the board to B650 board from B&H, $189."
    },
    {
      "kind": "reallocate",
      "part": "motherboard",
      "line": "board is $8.67 over its $180.33 budget; moved $8.67 from the parts still open."
    },
    {
      "kind": "pick",
      "part": "memory",
      "line": "RAM: 32 GB DDR5 from Amazon, $99."
    },
    {
      "kind": "pick",
      "part": "storage",
      "line": "SSD: 2 TB NVMe from Best Buy, $119."
    },
    {
      "kind": "knockout",
      "part": "cooler",
      "rule_id": "fit.cooler_height",
      "line": "cooler: Amazon out, cooler height 165 mm exceeds case clearance 160 mm."
    },
    {
      "kind": "pick",
      "part": "cooler",
      "line": "cooler: Low cooler from Central Computers, $53."
    },
    {
      "kind": "locked",
      "line": "Build locked: 6 parts, 4 sellers, $1,988."
    }
  ]
};

/** The build as it stood after `upTo` steps: only parts already picked or swapped, the total so far, open until locked. */
export function buildAt(b: BuildResult, upTo: number): BuildResult {
  const shown = stepsUpTo(b, upTo);
  const done = new Set(shown.filter((s) => s.kind === "pick" || s.kind === "swap").map((s) => s.part!));
  const picks = Object.fromEntries(Object.entries(b.picks).filter(([k]) => done.has(k)));
  const finished = shown.length === b.steps.length;
  return {
    ...b, picks, steps: shown,
    status: finished ? b.status : "open",
    totalCents: Object.values(picks).reduce((n, p) => n + p.priceCents, 0),
    sellers: [...new Set(Object.values(picks).map((p) => p.seller))].sort(),
  };
}

/** The Fetch tile's lines: the plan and every re-plan (clash, swap, budget moved), then how it ended. Picks and plain knockouts stay on the board. */
export const PLAN_KINDS: readonly StepKind[] = ["plan", "clash", "swap", "reallocate", "locked", "blocked"];
export function planLines(b: BuildResult): BuildStep[] {
  return b.steps.filter((s) => PLAN_KINDS.includes(s.kind));
}
