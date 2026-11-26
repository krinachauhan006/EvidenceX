"use client";

/**
 * Phase 1 kept a self-declared reviewer name in the browser. Since Phase 2 every
 * review action is attributed by the API to the signed-in account, so no name is
 * sent from the client any more. The hook keeps its shape so existing review
 * components continue to work; it always returns an empty name.
 */
export function useReviewer(): [string, (name: string) => void] {
  return ["", () => undefined];
}
