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
