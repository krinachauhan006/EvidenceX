// Pure classification of a failed request, so views can show the right state.
// No React and no imports, so Node can test it.

export type ErrorKind = "not_found" | "retryable" | "client";

/**
 * - not_found: the resource does not exist or is not in this case (404). Retrying the
 *   same request cannot help, so no retry action is offered.
 * - retryable: network failure (status 0 / unknown) or a server error (5xx, 408, 429).
 * - client: any other 4xx; the request itself is wrong, retrying will not help.
 */
export function errorKind(status: number | null | undefined): ErrorKind {
  if (status === 404) return "not_found";
  if (status === null || status === undefined || status === 0) return "retryable";
  if (status >= 500 || status === 408 || status === 429) return "retryable";
  return "client";
}

export function canRetry(status: number | null | undefined): boolean {
  return errorKind(status) === "retryable";
}
