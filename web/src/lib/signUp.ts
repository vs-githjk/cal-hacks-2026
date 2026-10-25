// Pure sign-up helpers: the routing decision for the buyer gate, input cleanup and error wording.
import { buyerSession } from "./screens.ts";

export type GateRoute = "connecting" | "buyer" | "signup" | "pair";

/** Where a screen goes: connecting, the buyer view, sign-up (no role at all), or the pairing view (a code was asked for, or a non-buyer role exists). */
export function gateRoute(
  connected: boolean,
  rolesReady: boolean,
  roles: readonly { role: string; subjectId: string }[],
  wantsPair: boolean,
): GateRoute {
  const s = buyerSession(connected, rolesReady, roles);
  if (s.status === "connecting") return "connecting";
  if (s.status === "buyer") return "buyer";
  if (wantsPair) return "pair";
  return roles.length === 0 ? "signup" : "pair";
}

// #449 PL-15: the phone is required (every purchase is approved by a call to it).
const PHONE_REQUIRED = "Enter the phone we call to approve a purchase.";
const PHONE_COUNTRY_CODE = "Add your country code, like +44 20 7946 0958.";

export function signUpErrorText(message: string): string {
  const m = message.trim();
  if (!m) return "Sign-up failed. Try again.";
  if (/no such reducer|reducer.*not found/i.test(m)) return "Sign-up is not live on this market yet.";
  if (/display name required/i.test(m)) return "Enter a name.";
  if (/phone number is required/i.test(m)) return PHONE_REQUIRED;
  if (/phone must/i.test(m)) return PHONE_COUNTRY_CODE;
  if (/busy|throttl|too many|rate/i.test(m)) return "Lots of people are signing up right now. Wait a few minutes and try again.";
  if (/already/i.test(m)) return "This browser already has an account. Use Continue below, or open a private window to start fresh.";
  return m;
}

export function cleanSignUp(name: string, phone: string): { displayName: string; phone: string } | { error: string } {
  const displayName = name.trim();
  if (!displayName) return { error: "Enter a name." };
  if (displayName.length > 40) return { error: "Keep the name under 40 characters." };
  const raw = phone.trim();
  if (!raw) return { error: PHONE_REQUIRED };
  const cleaned = raw.replace(/[\s\-.()]/g, "");
  const ask = { error: PHONE_COUNTRY_CODE };
  if (cleaned.startsWith("+")) return /^\+[1-9][0-9]{6,14}$/.test(cleaned) ? { displayName, phone: cleaned } : ask;
  if (/^[0-9]{10}$/.test(cleaned)) return { displayName, phone: `+1${cleaned}` };
  if (/^1[0-9]{10}$/.test(cleaned)) return { displayName, phone: `+${cleaned}` };
  return ask;
}

/** The pairing code to send, or null when the market would see nothing (it keeps only 0-9 and A-Z, so an empty try must not count as a failure). */
export function pairCodeToSend(raw: string): string | null {
  const code = raw.trim().toUpperCase().replace(/\s+/g, "");
  return code.toUpperCase().replace(/[^0-9A-Z]/g, "") ? code : null;
}

/** True only when the market explicitly refused the stored token (the SDK's token exchange got 401 or 403), never for flaky data. */
export function isTokenRejected(err: unknown): boolean {
  const e = err as { name?: string; status?: number } | null;
  return e?.name === "WebSocketTokenError" && (e.status === 401 || e.status === 403);
}
