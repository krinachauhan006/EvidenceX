// Minimal typed API client. Components use these helpers rather than calling
// fetch directly, per the frontend coding standards.
//
// Authentication is a server-side session in an HttpOnly cookie set by the API, so
// every request is sent with credentials and no token is ever handled in script.

/**
 * Where the API lives when NEXT_PUBLIC_API_BASE_URL is not set: port 8000 on the SAME
 * loopback host name the page was opened with. The session cookie is SameSite=Lax, and
 * browsers treat localhost and 127.0.0.1 as different sites, so a page on one calling
 * an API on the other would never keep its session.
 */
export function defaultApiBase(hostname: string | undefined, protocol = "http:"): string {
  if (hostname === "127.0.0.1" || hostname === "localhost") return `${protocol}//${hostname}:8000`;
  // Server-side render (no window): only reached in local development.
  if (hostname === undefined) return "http://localhost:8000";
  // Any real host: same origin ("" = relative URLs). In production a reverse proxy
  // routes /api/* and /health to the API, so no localhost URL ever reaches a browser.
  return "";
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  defaultApiBase(
    typeof window === "undefined" ? undefined : window.location.hostname,
    typeof window === "undefined" ? undefined : window.location.protocol,
  );

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

/** True when a request was cancelled with an AbortController (not a real failure). */
export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/** Pages that must not bounce to the sign-in page when a request returns 401. */
const PUBLIC_PATHS = ["/", "/login", "/register"];

/**
 * Send the browser to the sign-in page after the session expired, remembering where
 * the user was. Only same-site relative paths are ever used as the return target.
 */
export function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  const here = window.location.pathname;
  if (PUBLIC_PATHS.includes(here)) return;
  const next = encodeURIComponent(here + window.location.search);
  window.location.assign(`/login?next=${next}`);
}

async function parseBody(res: Response): Promise<unknown> {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function detailOf(body: unknown): unknown {
  return body && typeof body === "object" && "detail" in body
    ? (body as { detail: unknown }).detail
    : body;
}

export interface FetchOptions extends RequestInit {
  /** Do not redirect to /login on 401 (used by the session check itself). */
  allowAnonymous?: boolean;
}

export async function apiFetch<T>(path: string, init?: FetchOptions): Promise<T> {
  const { allowAnonymous, ...rest } = init ?? {};
  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(rest.headers ?? {}),
    },
    credentials: "include",
    cache: "no-store",
  });

  const body = await parseBody(res);
  if (!res.ok) {
    if (res.status === 401 && !allowAnonymous) redirectToLogin();
    throw new ApiError(res.status, detailOf(body));
  }
  return body as T;
}

/** A binary response (PDF, image, export) as a Blob, sent with the session cookie. */
export async function apiBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    if (res.status === 401) redirectToLogin();
    throw new ApiError(res.status, detailOf(await parseBody(res)) ?? `Request failed (${res.status})`);
  }
  return res.blob();
}

/** Save a Blob under a file name via a temporary object URL. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const UPLOAD_TOO_LARGE =
  "This file is larger than this server accepts for a single upload. Try a smaller file.";

/**
 * Upload a file via XMLHttpRequest so the caller can observe progress. The
 * browser sets the multipart Content-Type (with boundary) itself — we must NOT
 * force application/json here.
 */
export function apiUpload<T>(
  path: string,
  formData: FormData,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    xhr.withCredentials = true;

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total);
      };
    }

    xhr.onload = () => {
      let parsed: unknown = null;
      try {
        parsed = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        parsed = xhr.responseText;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(parsed as T);
      } else {
        if (xhr.status === 401) redirectToLogin();
        // 413 can come from the hosting platform before the request reaches the API
        // (e.g. Vercel's request-size limit), as an HTML or text page: show plain words.
        if (xhr.status === 413) {
          reject(new ApiError(413, UPLOAD_TOO_LARGE));
          return;
        }
        reject(new ApiError(xhr.status, detailOf(parsed)));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network error"));
    xhr.send(formData);
  });
}

export { API_BASE };
