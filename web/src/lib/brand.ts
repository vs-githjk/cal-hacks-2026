// web/src/lib/brand.ts
// The product name lives here and only here (#430). Change BRAND and every screen, title and the PWA name follow.
// Live identifiers never follow it: the SpacetimeDB db name, table and reducer names, env vars, the repo, agent addresses.

export const BRAND = "Fish Market";
/** Home screen label when installed; short enough for an iPhone icon caption. */
export const BRAND_SHORT = "Fish Market";
export const TAGLINE = "The agentic marketplace where buyers and sellers thrive.";
/** The security screen every listing and seller message passes before the buyer's agent reads it. */
export const SHIELD = "Smell Test";
export const SHIELD_LINE = "Nothing fishy gets through.";
export const DESCRIPTION = `${BRAND}: seller agents bid in sealed rounds for the buyer's PC parts. ${SHIELD} screens every listing, and nothing above the allowance is paid until the buyer approves by phone.`;
export const DOMAIN = "fishmarket.dev";
/** The one brand accent on top of design system v2 (koi). Used for the mark's eye and brand moments only, never for a state. */
export const KOI = "#ff7a45";
