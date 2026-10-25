// web/src/components/BrandMark.tsx
// The Fish Market mark: the buyer's agent as a fish with a chomping mouth (it eats the worst offer each round, like the floor's Pac-Man).
// Solid shapes only, no strokes, so it holds at 16 px. The same geometry is in public/icons/mark.svg for the favicon and PWA icons.
import { BRAND } from "@/lib/brand";

/** The fish on its own, in currentColor, with the koi eye. viewBox 0 0 24 24. */
export function FishGlyph({ size = 24, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className={`shrink-0 ${className}`}>
      <path fill="currentColor" d={FISH_PATH} />
      <circle cx="16.3" cy="8.6" r="1.35" fill="var(--koi)" />
    </svg>
  );
}

/** Body plus tail, with a Pac-Man wedge cut for the mouth on the right. */
export const FISH_PATH =
  "M21.2 9.3 15.4 12l5.8 2.7A7.3 7.3 0 0 1 8.9 16.6L3 20.2l1.4-8.2L3 3.8l5.9 3.6a7.3 7.3 0 0 1 12.3 1.9Z";

/** The app mark: an ink tile with the fish cut in the canvas colour. 22 px in the nav, per design system v2. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className="shrink-0">
      <rect width="24" height="24" rx="6.5" fill="var(--ink)" />
      <g transform="translate(1.7 1.7) scale(0.86)">
        <path fill="var(--canvas)" d={FISH_PATH} />
        <circle cx="16.3" cy="8.6" r="1.5" fill="var(--koi)" />
      </g>
    </svg>
  );
}

/** Mark plus wordmark. The name comes from BRAND only. */
export function Wordmark({ size = 22, showName = true }: { size?: number; showName?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <BrandMark size={size} />
      {showName && <span data-wordmark={BRAND} className="text-[16px] font-medium tracking-[-0.02em] text-ink">{BRAND}</span>}
    </span>
  );
}
