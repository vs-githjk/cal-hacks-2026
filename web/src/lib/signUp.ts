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

export function signUpErrorText(message: string): string {
  const m = message.trim();
  if (!m) return "Sign-up failed. Try again.";
  if (/no such reducer|reducer.*not found/i.test(m)) return "Sign-up is not live on this market yet.";
  if (/display name required/i.test(m)) return "Enter a name.";
  if (/phone must be/i.test(m)) return "Enter a full phone number, or leave it blank.";
  if (/busy|throttl|too many|rate/i.test(m)) return "Lots of people are signing up right now. Wait a few minutes and try again.";
  if (/already/i.test(m)) return "This browser already has an account. Use Continue below, or open a private window to start fresh.";
  return m;
}

export function cleanSignUp(name: string, phone: string): { displayName: string; phone?: string } | { error: string } {
  const displayName = name.trim();
  if (!displayName) return { error: "Enter a name." };
  if (displayName.length > 40) return { error: "Keep the name under 40 characters." };
  const raw = phone.trim();
  if (!raw) return { displayName };
  const cleaned = (raw.startsWith("+") ? "+" : "") + raw.replace(/\D/g, "");
  const digits = cleaned.replace(/\D/g, "").length;
  if (digits < 7 || digits > 20) return { error: "Enter a full phone number, or leave it blank." };
  return { displayName, phone: cleaned };
}
