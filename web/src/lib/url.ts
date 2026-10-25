// A source URL from a market row is seller input: "https://" alone makes new URL() throw during render and blanks the screen.

/** The URL if it is a real http(s) link with a host, else null (render it as plain text). Never throws. */
export function safeUrl(s: string): string | null {
  if (!/^https?:\/\/\S+$/i.test(s.trim())) return null;
  try {
    const u = new URL(s.trim());
    return (u.protocol === "http:" || u.protocol === "https:") && u.hostname ? s.trim() : null;
  } catch {
    return null;
  }
}

const LOOPBACK = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\])$/;

/** The API base to call from a page on `pageHost`, or null to skip it: empty, unparseable, or a loopback API seen from a page that is not
 * itself on loopback (a visitor's browser would hit its own machine and fail CORS). Null means "runs locally", never "offline". Never throws. */
export function reachableFrom(api: string, pageHost: string): string | null {
  try {
    const u = new URL(api);
    if (!u.hostname || (LOOPBACK.test(u.hostname) && !LOOPBACK.test(pageHost))) return null;
    return api.replace(/\/+$/, "");
  } catch {
    return null;
  }
}
