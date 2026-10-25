// The floor's look, in one place so a later palette (or a 3D renderer) swaps here. Values are the dark floor set of
// docs/design-system/tokens.css (v2): a clean ink stage, the product's semantic colors, Geist and Geist Mono only. Not neon.
export const FLOOR = {
  stage: "#0b1b2b", // floor-bg
  ground: "#112437", // floor-ground
  line: "#eef3f8", // floor-line
  rope: "#5b6b7c", // floor-rope
  pac: "#eef3f8", // the buyer
  tagBg: "#eef3f8",
  tagInk: "#0b1b2b",
  muted: "#8fa0b2",
  ink: "#eef3f8",
  referee: "#c7d4ff",
  refereeSoft: "#1e4ed838",
  live: "#22d3ee", // shield and the live pulse
  shieldSoft: "#22d3ee40",
  pulse: "#8fb0ff",
  surface: "#112437",
  surface2: "#16304a",
  // seller tints, by outcome: slate control, coral injected, amber uncertain, mint winner
  slate: "#8fa0b2", coral: "#e5484d", amber: "#fcd34d", mint: "#0f9d76", sky: "#8fb0ff",
  paper: "#f7f3e8", paperEdge: "#d9d2bd", ice: "#1a3a52",
  eaten: "#334155",
  // text on the dark stage
  mintText: "#6ee7b7", coralText: "#fca5a5", amberText: "#fcd34d",
  pipBg: "#112437f0", pipLine: "#eef3f81f", pipBubble: "#16304a",
  ledgerBg: "#112437e6", ledgerLine: "#eef3f824", dealBg: "#112437f5",
  shadowGlass: "inset 0 0.5px 0 #ffffff1f, 0 0 0 0.5px #eef3f81f, 0 4px 40px 8px #00000066, 0 34px 70px -34px #00000099",
  shadowCard: "0 1px 2px #00000066, 0 8px 24px #00000059",
  fontSans: "var(--font-geist), ui-sans-serif, system-ui, sans-serif",
  fontMono: "var(--font-geist-mono), ui-monospace, Menlo, Consolas, monospace",
} as const;
export type Tint = "slate" | "coral" | "amber" | "mint" | "sky";

/** Timings in ms (docs/design-system tokens: f-dash, f-block, ...). */
export const T = { dash: 600, chomp: 1000, block: 500, grow: 800, reveal: 320 } as const;
