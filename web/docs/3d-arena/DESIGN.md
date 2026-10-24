# 3D arena: design spec

The /floor scene tells one sealed round as a short piece of theater: a request, anonymous sealed envelopes, the close, the checks, the referee's ranking, and the winner. Every motion comes from a market row. The data contract is `web/src/lib/arenaScene.ts`.

## Concept: the sealed room

A black-box theater. A stepped circular dais in matte graphite, matte porcelain figures, and **one moving key light that tells the story**. Light is the only narrator: whoever the current beat is about is lit, and everyone else sits in soft shadow. The app is strictly black and white, and meaning never rides on hue, so this scene is about light, form, and shadow, not color.

The one memorable moment is the crown. Every light falls away except a narrow spot on the winner and the buyer, the camera eases in 8 percent, and the winner hops once. Everything before it stays quiet.

Banned: neon, glow, bloom, gradients, free orbit, idle bobbing, particle effects, motion that no row caused.

## Palette (three.js colors, all neutral)

| Role | Hex | Notes |
|---|---|---|
| Void / fog | `#000000` | scene fog near 11, far 24; the container background is `bg-canvas` (black) so the fog has no seam |
| Tier 0 (floor) | `#0d0d0d` | roughness 0.95 |
| Tier 1 | `#131313` | roughness 0.95 |
| Tier 2 (top) | `#1a1a1a` | roughness 0.9 |
| Tier edge hairlines | `#2c2c2c` | `LineLoop` on each tier's top edge: the drawn bracket paths |
| Porcelain (lit figures, envelopes) | `#eeeeee` | `MeshStandardMaterial` roughness 0.45, metalness 0 |
| Porcelain, SIM finish | `#c4c4c4` | slightly greyer; the text chip still says SIM |
| Dimmed (knocked, not in focus at crown) | `#3a3a3a` | tween the color, never use transparency |
| Seal on envelopes, props | `#1c1c1c` | |

Origin is always written as text (LIVE / MIRROR / SIM) in the nameplate. The figure's base marker is a second cue only: LIVE has a solid disc base, MIRROR a thin ring base, and SIM no base plus the greyer porcelain.

## Lighting and renderer

- `WebGLRenderer({ antialias: true, alpha: true })`, `toneMapping = ACESFilmicToneMapping`, `outputColorSpace = SRGBColorSpace`, `shadowMap.enabled = true`, `shadowMap.type = PCFSoftShadowMap`, pixel ratio capped at 2.
- Ambient: `HemisphereLight(0xffffff, 0x000000, 0.35)`.
- Key: `SpotLight(0xffffff, intensity tuned so lit porcelain reads near white, distance 0, angle 0.42, penumbra 0.6, decay 2)` at `(0, 9, 4)`, casts shadows (map 1024). Its **target** moves to the current focus actor over 350 ms (ease in out cubic). At the crown, the angle narrows from 0.42 to 0.22 and the ambient drops to 0.12.
- Rim: `DirectionalLight(0xffffff, 0.6)` from `(0, 4, -8)` so figures in the back arc keep a silhouette edge.
- Figures and envelopes cast shadows; tiers receive them.

## Stage geometry (world units, y up, camera on +z)

Three stacked cylinders. Tier tops: T0 at y 0, T1 at y 0.22, T2 at y 0.44.

| Tier | Radius | Spans |
|---|---|---|
| T0 floor | 5.6 | y -0.10 to 0 |
| T1 | 3.4 | y 0 to 0.22 |
| T2 | 1.5 | y 0.22 to 0.44 |

- **Ledger table** (the referee's pick target, key `referee`): box 1.0 x 0.12 x 0.6 on T2, centered at `(0, 0.50, 0.35)`, color `#202020`. Sealed envelopes stack here.
- **Buyer**: on T2 at `(0, 0.44, -0.35)`, facing +z (toward the camera), scale 1.1.
- **Advocate**: on T1 at `(-2.5, 0.22, 1.5)`, facing the center. Holds a tablet: box 0.34 x 0.24 x 0.03 in front of the chest, tilted 30 degrees.
- **Bazaar Shield**: on T1 at `(2.5, 0.22, 1.5)`, facing the center. Holds a hex plate: `CylinderGeometry(0.26, 0.26, 0.04, 6)` turned upright in front of the chest.
- **Offers (sellers)**: seats on T0 in a horseshoe behind the buyer, radius 4.6, angles spread evenly from 125 to 235 degrees (0 degrees is +z toward the camera), facing the center. Above 7 offers, use a second staggered row at radius 5.2. Seat order is the scene's offer order, which keeps it stable between frames.
- **Advanced seats**: survivors of a knockout stage move to T1 at radius 2.6 in the back half (angles 140 to 220 degrees). The winner moves onto T2 at `(0.8, 0.44, -0.2)`, beside the buyer.

### Figures

All primitives, no downloads, geometry shared across figures:
- Body `CapsuleGeometry(0.26, 0.62, 6, 16)` with its center at y 0.57 above the figure's feet.
- Head `SphereGeometry(0.2, 24, 16)` at y 1.12.
- A pose is the group's yaw plus a small pitch: lean forward 8 degrees when acting, head down 12 degrees when knocked.

### Envelopes

`BoxGeometry(0.36, 0.012, 0.24)` porcelain with a seal disc `CylinderGeometry(0.04, 0.04, 0.014, 16)` in `#1c1c1c` at its center. One envelope per sealed bid (`sealedCount`), stacked on the ledger table and fanned by a deterministic yaw jitter of `(i * 37) % 11 - 5` degrees. Above 12 envelopes, draw 12 and let the HTML caption state the real count.

## Camera

`PerspectiveCamera(fov 38)` at `(0, 6.4, 9.6)` looking at `(0, 0.6, -0.8)`. Fixed: no orbit, no user rotation. When the container aspect is below 0.9 (phones), use fov 48 and move the camera to 1.2x its distance so the horseshoe fits. The crown push-in moves the camera 8 percent toward the winner and buyer midpoint over 1200 ms, ease in out cubic.

## Motion: what each phase and beat does

`beat` counts the beats applied. When `beat` goes up by exactly 1, animate that beat over its `ms`. Any other change (replay reset, skip, a new round, a reconnect) snaps without tweening. With reduced motion, everything snaps.

| State | Scene |
|---|---|
| `waiting` | The empty dais, the buyer alone in a soft light, everyone else unlit. No envelopes. |
| `open` | The key light is on the buyer and table. Envelopes on the table equal `sealedCount`. When `sealedCount` goes up live, each new envelope drops from 1.2 above onto the stack over 450 ms. No sellers are visible, because nobody's bid is public before close. |
| `closing` | The same as open, with the light dimming to 70 percent. |
| beat 0 of a closed round | The open state's final frame: the full envelope stack, no sellers. |
| `arrive` | Each offer's figure walks in from radius 6.4 (out of the fog) to its seat. In the same beat, its envelope arcs from the table (arc height 0.6) to stand upright at chest height in front of its seller, facing the camera: the envelope opens. Stagger figures by 80 ms. |
| `gate` | The light visits Shield (if any knock is a `shield_block`) or the table (other refusals), then each knocked offer. Shield's plate turns 15 degrees toward the knocked seller and rises 0.1. Each knocked seller's envelope falls flat onto the floor, and the seller steps back to radius 5.8, dims, and lowers its head. |
| `advocate` | The same as gate, with the advocate tilting its tablet up toward the knocked seller. |
| `knockout` | Each advancing offer hops up to the next tier (a parabolic arc, height 0.5, 500 ms) to its advanced seat. Outranked offers dim in place; they stay on their tier because they are valid offers that ranked lower. |
| `crown` | The winner hops onto T2 beside the buyer. All other figures dim. The spot narrows on the winner and buyer, and the camera pushes in. The winner's card lifts to float above the ledger table. |
| `inconsistent` | No sellers and no crown. The light stays on the table. The HTML says why. |

Rendering runs on demand: frames only while a tween is running, then one final frame. The existing on-demand loop is the model.

## Nameplates (HTML over the canvas)

The labels are HTML buttons projected from each actor's head anchor (y 1.55 times the actor's scale) every rendered frame, with positions written straight to `style.transform` through refs (no React state per frame). Each plate:
- **Line 1:** the name, truncated with an ellipsis at a 10rem max width, plus an origin chip with the text LIVE, MIRROR or SIM.
- **Line 2 (offers only, after `arrive`):** the landed price, `$1,299.99`, in tabular numbers. Knocked offers show the name struck through plus a single word: `Vetoed`, `Blocked`, or `Refused`. Winners show `Winner`.
- **Selection:** the selected actor's plate gets a 1px ink ring.
- Plates are at least 44px tall and keyboard focusable. Enter or Space picks the actor, the same as a click.
- Plates for knocked offers sit at 60 percent opacity.

## HTML layer on and beside the canvas (page)

```
+------------------------------------------------------------+  +-------------------------+
| Live round  [SIM]                         Closes in 0:08   |  | Offers                  |
| RTX 5070 Ti                (Instrument Serif, 30px)        |  | 1  Fair Price PC  SIM   |
| 3 sealed offers on the table. Prices stay hidden until     |  |    $1,299.99  Winner    |
| the round closes.                                          |  | 2  Gadget Grove   SIM   |
|                                                            |  |    $1,247.02            |
|                    [ 3D sealed room ]                      |  | -  Bargain Bin    SIM   |
|                                                            |  |    Vetoed: fit.gpu_...  |
|                                                            |  |    source link          |
| [Pause] [Replay] [Skip to result]          Final  4 of 5   |  | Selected: row details   |
+------------------------------------------------------------+  +-------------------------+
```

- **Top left:** a status line in Geist 13px muted ("Live round", "Recorded replay", or "Sample run" plus the SIM chip). Below it, in the open phase, the request label is the hero in Instrument Serif (`font-display`, 30px desktop, 24px phone). It is the one hero per screen until the crown, when the hero becomes the winning price. Below that, the beat caption in Geist 16px ink, max 52ch.
- **During knockout beats**, a quiet line reads: "How the referee ranked the sealed bids. These were not live head-to-head bids."
- **Top right:** a countdown while open ("Closes in 0:08"), from `deadline`.
- **Bottom left:** the playback controls (Pause or Play, Replay, Skip to result), visible only when there are beats. Each is a 44px-tall button: Geist 14px, `bg-glass`, `border-line`, rounded. **Bottom right:** the beat name and position ("Final, 4 of 5").
- **Side card ("Offers"):** before close, it says "N sealed offers. Prices stay sealed until the round closes." After close, it shows rows in the scene's offer order: rank, name, origin chip, price "before sales tax", outcome. Knocked rows are struck through with the reason and a `SourceLink` when there is one. The winner row gets the existing winner fill (`bg-mint-soft`). Below the rows sit the selected actor's details: row refs (`round_result/<id>` and linked `floor_event/<id>` rows).
- The overlay never blocks canvas picking except on its own controls (`pointer-events-none` on the wrapper, `pointer-events-auto` on buttons).

## Copy (sentence case, plain, no em or en dashes)

| State | Caption |
|---|---|
| waiting | No round yet. When a buyer posts a request, it appears here. |
| open, 0 sealed | Sealed round open. Sellers can bid until {time}. |
| open, n sealed | {n} sealed offers on the table. Prices stay hidden until the round closes. |
| closing | Round closed. Waiting for the referee's result. |
| arrive | The round closed. {n} sealed offers are opened. |
| gate | The referee refused {n} offers before ranking. |
| advocate | The advocate vetoed {n} offers, each with a cited source. |
| knockout | {Stage}: the referee ranked {A} ahead of {B}. |
| crown | {Winner} wins at {price} before sales tax. |
| closed, no winner | No offer passed the checks, so nobody won this round. |
| inconsistent | The result rows disagree, so no winner is shown. |

The budget, the ceiling band, and the approval code never appear anywhere in this scene.

## Fallback and lifecycle

- No WebGL, a failed `three` import, a renderer constructor throw, or `webglcontextlost`: call `onUnavailable()`. The page then shows the HTML layer and the offers card plus `ActorList`, so the whole story stays readable without the canvas.
- Reduced motion: the 3D scene still renders, statically at the target state, and the playback reducer skips to the final frame.
- Teardown disposes every geometry, material, and the renderer, removes listeners, disconnects the `ResizeObserver`, cancels the frame, and removes the canvas.
- Sizing: a `ResizeObserver` on the container (not window resize). Zero width or height skips rendering until the size is real.
- Frozen (market disconnected): no tweens start and no frames run. The last frame stays on screen. When it unfreezes, snap to the current target.
