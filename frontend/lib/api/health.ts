// Public service status (backend/app/main.py: GET /health). No session required.

import { apiFetch } from "@/lib/api/client";
import type { Health } from "@/lib/server-notice";

export type { Health, SchemaState } from "@/lib/server-notice";
export { serverNotice } from "@/lib/server-notice";

export function health(signal?: AbortSignal): Promise<Health> {
  return apiFetch<Health>("/health", { signal, allowAnonymous: true });
}
