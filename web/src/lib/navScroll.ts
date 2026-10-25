// The top nav scrolls sideways on a phone (#449 RT-33/PL-29). Two pure helpers keep the component small and testable.

export interface ScrollBox { scrollLeft: number; clientWidth: number; scrollWidth: number }

/** Which edges hide more links: a fade is drawn there, so a clipped link reads as "more this way", not as cut off. */
export function navEdges(b: ScrollBox): { left: boolean; right: boolean } {
  return { left: b.scrollLeft > 1, right: b.scrollLeft + b.clientWidth < b.scrollWidth - 1 };
}

const ROOM = 8;

/** The scrollLeft that brings a link fully into view with a little room, or the current one when it is already visible. */
export function scrollToShow(view: { scrollLeft: number; clientWidth: number }, link: { offsetLeft: number; offsetWidth: number }): number {
  if (link.offsetLeft < view.scrollLeft) return Math.max(0, link.offsetLeft - ROOM);
  if (link.offsetLeft + link.offsetWidth > view.scrollLeft + view.clientWidth) return link.offsetLeft + link.offsetWidth - view.clientWidth + ROOM;
  return view.scrollLeft;
}
