// FROZEN 2026-10-24 23:50 PDT. Changes need the floor lead.
//
// SVG art contract shared by west/placeholder.tsx (now) and west/art.tsx (later).
// Every art export is a pure component returning an SVG <g> drawn at the origin in user units,
// with the figure's feet at (0,0), about 120 tall and 70 wide. Ink stroke "#1A1A1A", width 4,
// round caps and joins. The scene (ArenaWest.tsx) positions each piece with a transform and owns
// all motion, text and aria.
import type { ReactElement } from "react";

/** Hat silhouette worn by a cowboy. */
export type HatKind = "wide" | "bowler" | "sombrero" | "cap";
/** Body pose of a cowboy figure. */
export type CowboyPose = "idle" | "toss" | "fold" | "tip" | "ghost";
/** Gavel position for the auctioneer. */
export type GavelState = "up" | "down";
/** Where a speech bubble's tail points from the body. */
export type BubbleTail = "down" | "left" | "right";

export interface CowboyProps {
  hat: HatKind;
  pose: CowboyPose;
  /** Stroke color override; defaults to "#1A1A1A". */
  ink?: string;
}
export interface AuctioneerProps {
  gavel: GavelState;
}
/** 360 wide, 170 tall, base at (0,0); sign board rect 220 x 60 centered at (0,-150), empty for the scene's text. */
// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface PlatformProps {}
/** Board centered at (0, -h/2 - 16) on legs down to (0,0); board left empty for text. */
export interface SignProps {
  w: number;
  h: number;
}
/** Centered at (0,0). Sealed shows the back with a wax dot; open is blank for text. */
export interface PriceCardProps {
  w: number;
  h: number;
  sealed: boolean;
}
/** Tail tip at (0,0). */
export interface BubbleProps {
  w: number;
  h: number;
  tail: BubbleTail;
}
/** Fills w x h from (0,0); the lower 40 percent is left empty. */
export interface BackdropProps {
  w: number;
  h: number;
}
export interface FenceProps {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

export interface WestArt {
  Cowboy: (p: CowboyProps) => ReactElement;
  Auctioneer: (p: AuctioneerProps) => ReactElement;
  Sheriff: () => ReactElement;
  Appraiser: () => ReactElement;
  Referee: () => ReactElement;
  Platform: () => ReactElement;
  Sign: (p: SignProps) => ReactElement;
  PriceCard: (p: PriceCardProps) => ReactElement;
  Bubble: (p: BubbleProps) => ReactElement;
  DustPuff: () => ReactElement;
  Spotlight: () => ReactElement;
  Backdrop: (p: BackdropProps) => ReactElement;
  Fence: (p: FenceProps) => ReactElement;
}
