/**
 * Server-side fetch helpers for talking to the FastAPI backend.
 *
 * Use these ONLY inside Server Components / Route Handlers / Server Actions.
 * For client-side requests use SWR + the `useMutation` hook (or the Next.js
 * `/api/*` rewrites in `next.config.ts`).
 *
 * `API_URL` resolves to the Docker-internal service name (`http://web:8000`)
 * inside containers and falls back to `http://localhost:8000` for local dev.
 */

export const API_URL =
  process.env.API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly body?: unknown;

  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/**
 * Fetch JSON from the FastAPI backend with an optional bearer token.
 *
 * @example
 *   const { token } = await getSessionAndToken();
 *   const portfolios = await serverFetch<Porfolio[]>("/api/v1/portfolios", token);
 */
export async function serverFetch<T = unknown>(
  path: string,
  token?: string | null
): Promise<T> {
  const headers: HeadersInit = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
    headers,
    cache: "no-store",
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(
      `GET ${path} failed: ${res.status} ${res.statusText}`,
      res.status,
      body
    );
  }

  // 204 No Content / empty bodies
  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/**
 * Typed convenience wrappers for common HTTP verbs with a JSON body.
 * All of them attach the bearer token and send/receive JSON.
 */
async function sendRequest<T = unknown>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  token?: string | null,
  body?: unknown
): Promise<T> {
  const headers: HeadersInit = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });

  if (!res.ok) {
    let errBody: unknown;
    try {
      errBody = await res.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(
      `${method} ${path} failed: ${res.status} ${res.statusText}`,
      res.status,
      errBody
    );
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const serverPost = <T = unknown>(path: string, token?: string | null, body?: unknown) =>
  sendRequest<T>("POST", path, token, body);

export const serverPut = <T = unknown>(path: string, token?: string | null, body?: unknown) =>
  sendRequest<T>("PUT", path, token, body);

export const serverPatch = <T = unknown>(path: string, token?: string | null, body?: unknown) =>
  sendRequest<T>("PATCH", path, token, body);

export const serverDelete = <T = unknown>(path: string, token?: string | null) =>
  sendRequest<T>("DELETE", path, token);
