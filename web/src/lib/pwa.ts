// What the installed app does with the home screen icon. Pure, so a bad count never paints a wrong badge.

export type BadgeAction = { kind: "set"; count: number } | { kind: "clear" };

/** A badge for a waiting-approval count that is a positive whole number; anything else clears it. */
export function badgeAction(pending: number): BadgeAction {
  return Number.isInteger(pending) && pending > 0 ? { kind: "set", count: pending } : { kind: "clear" };
}
