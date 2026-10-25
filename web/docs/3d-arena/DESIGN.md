# 3D arena: design spec

The /floor scene tells one sealed round as a short piece of theater: a request, anonymous sealed envelopes, the close, the checks, the referee's ranking, and the winner. Every motion comes from a market row. The data contract is `web/src/lib/arenaScene.ts`.

## Art direction v2: toy diorama (supersedes the look below; geometry layout, beats, copy and lifecycle still apply)

Chosen by Abhinav on Sat afternoon. The arena is a bright miniature world, like Monument Valley: a lit diorama box set into the dark app. Warm daylight, soft shadows, and chunky toy characters. Color is personality, never meaning: origin is still written as text (LIVE, MIRROR or SIM).

- **Container:** CSS background `linear-gradient(180deg, #F8EBDD 0%, #EEDCEB 100%)`. The renderer uses alpha with no scene.background. Fog is `#F1E3E4`, near 14, far 30. The container is `rounded-[20px]`.
- **Camera:** an `OrthographicCamera` in an isometric-ish diorama view at elevation about 35 degrees and azimuth 0, sized so the T0 disc plus the seats fill about 85 percent of the width. The crown push-in is a zoom from 1.0 to 1.12. On phones, zoom out so the horseshoe fits.
- **Island stage:** each tier is a cylinder with a thick visible side, like a cake layer.
  - T0 top: sage `#A9C9A4`. T1: clay `#E4A587`. T2: cream `#F5EBDC`. All the sides are `#E8D6C0`.
  - Add a thin darker lip (`#8FB08A` for T0) by stacking a slightly larger, very thin disc under each top.
  - Under T0 sits a short inverted cone of earth (`#C9A98A`) so the island floats.
  - Roughness 0.85.
  - Drop the hairline LineLoops.
- **Light:**
  - Sun: `DirectionalLight(#FFE9CC, 2.6)` from the upper left `(-6, 10, 6)`, casting shadows with map 2048, radius 4, and a shadow camera fit to the island.
  - Ambient: `HemisphereLight(#FFF6EA, #CDB8DC, 1.0)`.
  - No dark theater. Focus is shown by a **focus ring**, not darkness: a soft white disc (`CircleGeometry`, opacity 0.55) under the focused actor that glides between actors over 350 ms, plus a 6 percent scale bounce on the actor when focus lands.
  - At the crown: a warm `SpotLight(#FFD98A)` on the winner and buyer, and every other figure desaturates.
- **Toy characters:** chunky and cute.
  - Body `CapsuleGeometry(0.34, 0.46, 8, 20)`, head `SphereGeometry(0.3, 32, 20)` sitting on the body, two eye spheres (r 0.035, `#2B2A33`) on the front of the head, and a tiny flat foot disc.
  - Roughness 0.6, clay-like.
  - **Seller color:** picked deterministically by hashing sellerId into `#F28482` coral, `#F6BD60` mustard, `#7FB7BE` teal, `#B79CED` lilac, `#90BE6D` leaf, `#F7A072` apricot, `#6D9DC5` cornflower. Two sellers on stage never share a color.
  - **Seller hat:** also by hash: a cone party hat, a cap (a disc brim plus a half sphere), a top box, or a beanie (a half sphere with a pom).
  - **Buyer:** cream `#FFF8EE` with a navy `#2F3E66` beret.
  - **Advocate:** navy body with a cream clipboard.
  - **Shield:** steel blue `#5B7FA6` with the hex shield in cream with a navy rim.
- **Envelopes:** cream `#FFF4E2` with a red wax seal `#C8553D`. When opened, they become small price cards standing upright.
- **Knocked:** the figure desaturates to `#BDB3A9` (tween the color), sits down (scale y to 0.82), steps back, and its card falls flat.
- **Winner:** a gold `#E9B949` trophy plinth (a short cylinder plus a ring) rises out of T2 under the winner. Then comes **one confetti burst**: 60 small paper quads in the seller palette with simple gravity and spin over 1.6 s, then they are removed. This is the one orchestrated moment. Under reduced motion there's no confetti; the plinth is simply present.
- **Nameplates:** compact pills.
  - White `#FFFFFF` with 94 percent opacity, text `#2B2A33`, 12px semibold, rounded-full, `shadow-[0_2px_8px_rgba(60,40,30,0.15)]`.
  - Line 1 is the name with the origin text chip; line 2 (offers only) is the price or the outcome word.
  - Each pill keeps a 44px hit area through transparent padding while staying visually small.
  - The advocate, Shield and referee plates appear only while they are in focus or selected.
  - Plates never overlap: resolve collisions each frame by nudging lower-priority plates down. Priority runs winner, then focus, then the rest.
- **HUD** (on the light backdrop, dark text): the caption block is a white card (`rounded-2xl`, 92 percent white, a soft shadow, padding 16), with the hero in `font-display` `#2B2A33`. The controls are white pill buttons with dark text. The side Offers card stays in the app's dark style, so the diorama reads as a lit window into the market.

## Concept (v1, superseded look): the sealed room

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

## Palette v3: golden hour terrace (Sat night)

Value structure: darker warm rim, brightest at the center stage. Colors flat in one cream band were the problem.

- Plaza: fog 0xf2dcc6, floor 0xdcc8aa, t1 0xefe2cc, t2 0xfbf5ec, side 0xc8b08d, wall 0xd79a76 (terracotta), wallTop 0xedcdb0, stone 0xe8dccb, table 0xe9d9c1.
- Accents: gold 0xd4a548 (roughness 0.3, metalness 0.55, trim tubes 0.05, floor ring 0.04), charcoal 0x2b2a33, banner 0x2f3e66 (navy), wax 0xc8553d (red seal), paper 0xfff4e2, pot 0xc4734f, arch 0xf0e4d2, crate 0xc99a63, paving joints 0xc7b291 at 0.5 opacity.
- Foliage: leaf1 0x4f8a4a, leaf2 0x6fae5f, leaf3 0x3c6e3a.
- Figures: buyer 0x2f6f6a (deep teal), advocate 0xf3ebdf, knocked 0xbdb3a9, anon 0x9b958e. Sellers now use their SELLER_COLORS hue as the body color (no more CLAY tones); legs stay shade(color, 0.72). Confetti uses SELLER_COLORS plus gold 0xd4a548 and cream 0xfff4e2.
- Lights: HemisphereLight(0xfff4e6, 0xb9b0d6, 1.05) for a warm sky and cool lavender ground, sun 0xffe4c2 at SUN = 2.6, spot 0xffd98a, toneMappingExposure 1.0.
- Container background: radial-gradient(120% 95% at 50% 30%, #FFF6EA 0%, #F6E2CC 55%, #E6C6A8 100%). The white corner wash overlay is removed.
- Nameplates: solid white, 13px semibold, selected ring #2F6F6A, winner on #FFF6DD with a 2px #D4A548 ring.
- Light app (lands with the light cream redesign, lane-a-redesign; not #372, which is the dark theme): the controls bar is light `#FFFDF8` with a `#E8DCCB` top border, navy `#2F3E66` step dots, connectors and focus rings, a navy primary button (Play, Pause, Replay) and white secondary buttons. The frame is `ring-1 #E2D3BE` with a warm shadow `0 18px 48px rgba(110,70,30,0.16)`.
