"use client";

import { useCallback, useState } from "react";
import { mutate } from "swr";

/**
 * SWR-integrated mutation hook for POST / DELETE / PUT / PATCH calls to the
 * FastAPI backend.
 *
 * After a successful mutation it revalidates the supplied SWR cache keys so any
 * dependent lists / dashboards refresh automatically.
 *
 * @example
 *   const { trigger, isMutating, error } = useMutation(
 *     "/api/v1/portfolios",
 *     "POST",
 *     { revalidateKeys: ["/api/v1/portfolios"] }
 *   );
 *   await trigger({ name: "BTC spot" }, token);
 */

const CLIENT_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

type RevalidateKey = string | ((key: unknown) => boolean);

interface UseMutationOptions {
  /** SWR cache keys (or matcher functions) to revalidate after success. */
  revalidateKeys?: RevalidateKey[];
}

export interface UseMutationResult<TData, TBody> {
  data: TData | null;
  error: Error | null;
  isMutating: boolean;
  /** Fire the request. Returns the parsed JSON (or null for 204). */
  trigger: (body?: TBody, token?: string | null) => Promise<TData | null>;
  /** Reset data/error back to initial state. */
  reset: () => void;
}

export function useMutation<TData = unknown, TBody = unknown>(
  path: string,
  method: "POST" | "DELETE" | "PUT" | "PATCH" = "POST",
  options: UseMutationOptions = {}
): UseMutationResult<TData, TBody> {
  const [data, setData] = useState<TData | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isMutating, setIsMutating] = useState(false);

  const trigger = useCallback(
    async (body?: TBody, token?: string | null): Promise<TData | null> => {
      setIsMutating(true);
      setError(null);
      try {
        const headers: HeadersInit = {};
        if (token) {
          headers.Authorization = `Bearer ${token}`;
        }
        if (body !== undefined) {
          headers["Content-Type"] = "application/json";
        }

        // Relative path → proxied through next.config.ts rewrites when the
        // public API URL isn't set (avoids CORS in the browser).
        const url = `${CLIENT_API_URL}${path}`;

        const res = await fetch(url, {
          method,
          headers,
          body: body !== undefined ? JSON.stringify(body) : undefined,
        });

        if (!res.ok) {
          let detail: unknown;
          try {
            detail = await res.json();
          } catch {
            /* no JSON body */
          }
          throw new Error(
            `API ${method} ${path} failed: ${res.status} ${res.statusText}` +
              (detail ? ` — ${JSON.stringify(detail)}` : "")
          );
        }

        const json: TData | null =
          res.status === 204 ? null : ((await res.json()) as TData);
        setData(json);

        // Revalidate any dependent SWR caches.
        const keys = options.revalidateKeys ?? [];
        if (keys.length > 0) {
          await Promise.all(
            keys.map((key) =>
              typeof key === "function" ? mutate(key) : mutate(key)
            )
          );
        }

        return json;
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        setError(e);
        throw e;
      } finally {
        setIsMutating(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [path, method]
  );

  const reset = useCallback(() => {
    setData(null);
    setError(null);
    setIsMutating(false);
  }, []);

  return { data, error, isMutating, trigger, reset };
}

export default useMutation;
