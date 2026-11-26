// Post-login redirect target. Pure (no imports), so Node can test it.

/** Only same-origin relative paths are accepted as a post-login destination. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) {
    return "/cases";
  }
  if (/^\/(login|register)(\/|\?|$)/.test(next)) return "/cases";
  return next;
}
