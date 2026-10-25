/** Pure state for the video-call frame: which pane is big, which corner the tile sits in, and the unread count on the chat tile. */

export type Corner = "tr" | "tl" | "br" | "bl";
export interface CallState { swapped: boolean; corner: Corner; unread: number; lastSeenId: string | null }
export type CallAction =
  | { type: "toggle" }
  | { type: "setCorner"; x: number; y: number; w: number; h: number }
  | { type: "newLines"; ids: string[] };

/** swapped = the chat is the big pane and the floor is the tile. */
export const initialCall: CallState = { swapped: false, corner: "tr", unread: 0, lastSeenId: null };

/** The corner nearest to a point inside a w x h frame. */
export function cornerFromPoint(x: number, y: number, w: number, h: number): Corner {
  const right = x >= w / 2;
  const bottom = y >= h / 2;
  return bottom ? (right ? "br" : "bl") : right ? "tr" : "tl";
}

export function callReducer(s: CallState, a: CallAction): CallState {
  switch (a.type) {
    case "toggle":
      // The chat is the big pane when swapped; opening it clears the unread count.
      return { ...s, swapped: !s.swapped, unread: s.swapped ? s.unread : 0 };
    case "setCorner":
      return { ...s, corner: cornerFromPoint(a.x, a.y, a.w, a.h) };
    case "newLines": {
      if (a.ids.length === 0) return s;
      const last = a.ids[a.ids.length - 1]!;
      if (s.swapped) return { ...s, unread: 0, lastSeenId: last };
      const at = s.lastSeenId === null ? -1 : a.ids.lastIndexOf(s.lastSeenId);
      // The first batch is the baseline (nothing unread); later batches count the ids after the last one seen.
      const fresh = s.lastSeenId === null ? 0 : at === -1 ? a.ids.length : a.ids.length - 1 - at;
      return { ...s, unread: s.unread + fresh, lastSeenId: last };
    }
  }
}

/** A w x h camera window centred on (cx, cy), clamped inside a stage of size sw x sh (stage origin 0,0). */
export function followBox(cx: number, cy: number, sw: number, sh: number, w = 320, h = 200): [number, number, number, number] {
  const x = Math.min(Math.max(cx - w / 2, 0), Math.max(0, sw - w));
  const y = Math.min(Math.max(cy - h / 2, 0), Math.max(0, sh - h));
  return [x, y, w, h];
}
