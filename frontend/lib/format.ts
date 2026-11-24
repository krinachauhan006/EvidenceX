// Shared display formatting helpers.

/**
 * Parse a timestamp from the API.
 *
 * The backend stores and sends UTC. SQLite does not keep a UTC offset, so values
 * can arrive like "2026-11-14T22:18:14.877000" with no "Z". JavaScript would read
 * that as local time and show the wrong hour, so a missing offset is treated as UTC.
 */
export function parseApiDate(iso: string): Date {
  const t = iso.indexOf("T");
  const tail = t >= 0 ? iso.slice(t) : "";
  const hasOffset = /(Z|[+-]\d{2}(:?\d{2})?)$/i.test(tail);
  return new Date(t >= 0 && !hasOffset ? `${iso}Z` : iso);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = parseApiDate(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

export function formatDurationMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
