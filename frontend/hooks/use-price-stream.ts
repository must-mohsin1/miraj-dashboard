"use client";

import { useEffect, useRef, useState } from "react";

/**
 * usePriceStream — Client Component hook.
 *
 * Subscribes to the FastAPI SSE endpoint ``GET /api/v1/stream/prices`` and
 * returns a live map of ``{ price, timestamp }`` per symbol, plus a
 * connection state flag.
 *
 * Because the browser ``EventSource`` API cannot set custom headers, the
 * JWT access token is passed via the ``?token=<jwt>`` query parameter (the
 * backend's stream endpoint accepts both Bearer header and query param).
 *
 * Features:
 *  - Auto-reconnect with exponential backoff (1s → 2s → 5s → 10s → capped 15s)
 *  - Cleans up the EventSource on unmount or when the symbol list changes
 *  - Debounced symbol-list changes (250 ms) to avoid thrashing on rapid edits
 *  - Only subscribes when a token is present (no-op for unauthenticated users)
 *
 * @example
 *   const token = useSession()?.accessToken;
 *   const { prices, isConnected } = usePriceStream(["BTC-USD", "ETH-USD"], token);
 */

/** A single live price tick. */
export interface LivePrice {
  /** Latest price (float). */
  price: number;
  /** Unix timestamp (seconds) from the backend. */
  timestamp: number;
}

/** Map of symbol → live price tick. */
export type PriceMap = Record<string, LivePrice>;

/** Hook return type. */
export interface UsePriceStreamResult {
  /** Live prices keyed by symbol (upper-cased). */
  prices: PriceMap;
  /** ``true`` when the SSE connection is open and receiving data. */
  isConnected: boolean;
}

/** Base API URL — empty string means "same origin via Next.js proxy/rewrite". */
const CLIENT_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

/** Initial reconnect delay (ms). */
const INITIAL_BACKOFF_MS = 1_000;
/** Maximum reconnect delay (ms). */
const MAX_BACKOFF_MS = 15_000;
/** Debounce window for symbol-list changes (ms). */
const SYMBOL_DEBOUNCE_MS = 250;

export function usePriceStream(
  symbols: string[],
  token: string | null | undefined,
): UsePriceStreamResult {
  // Debounced copy of the symbols list so rapid edits don't open/close
  // the EventSource repeatedly.
  const [debouncedSymbols, setDebouncedSymbols] = useState<string[]>(symbols);

  useEffect(() => {
    const id = setTimeout(() => {
      // Dedupe + normalise
      const normalised = Array.from(
        new Set(
          symbols
            .map((s) => s.trim().toUpperCase())
            .filter((s) => s.length > 0),
        ),
      );
      setDebouncedSymbols((prev) => {
        const same =
          prev.length === normalised.length &&
          prev.every((s, i) => s === normalised[i]);
        return same ? prev : normalised;
      });
    }, SYMBOL_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [symbols]);

  const [prices, setPrices] = useState<PriceMap>({});
  const [isConnected, setIsConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffRef = useRef<number>(INITIAL_BACKOFF_MS);
  const mountedRef = useRef<boolean>(true);

  useEffect(() => {
    mountedRef.current = true;

    // No-op when there's no token or no symbols — keep the previous
    // prices so the UI doesn't blank out on a transient auth gap.
    if (!token || debouncedSymbols.length === 0) {
      setIsConnected(false);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      return;
    }

    const symbolsParam = debouncedSymbols.join(",");
    const url = `${CLIENT_API_URL}/api/v1/stream/prices?symbols=${encodeURIComponent(
      symbolsParam,
    )}&token=${encodeURIComponent(token)}`;

    let es: EventSource | null = null;

    const cleanup = () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (es) {
        es.onopen = null;
        es.onmessage = null;
        es.onerror = null;
        es.close();
        es = null;
      }
      eventSourceRef.current = null;
    };

    const connect = () => {
      if (!mountedRef.current) return;
      cleanup();

      es = new EventSource(url, { withCredentials: false });
      eventSourceRef.current = es;

      es.onopen = () => {
        if (!mountedRef.current) return;
        setIsConnected(true);
        // Reset backoff after a successful connection.
        backoffRef.current = INITIAL_BACKOFF_MS;
      };

      es.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(event.data) as {
            symbol: string;
            price: number;
            timestamp: number;
          };
          if (
            typeof data.symbol === "string" &&
            typeof data.price === "number" &&
            typeof data.timestamp === "number"
          ) {
            const sym = data.symbol.toUpperCase();
            setPrices((prev) => ({
              ...prev,
              [sym]: {
                price: data.price,
                timestamp: data.timestamp,
              },
            }));
          }
        } catch {
          // Ignore malformed lines (comments, partial chunks)
        }
      };

      es.onerror = () => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        // EventSource auto-reconnects natively, but if the server has
        // closed the connection (e.g. on deploy) we may hit a
        // CONNECTING → OPEN loop that never fires onopen.  To be safe,
        // we close + retry with backoff.
        if (es) {
          es.close();
          es = null;
          eventSourceRef.current = null;
        }

        const delay = backoffRef.current;
        // Exponential backoff with cap
        backoffRef.current = Math.min(
          backoffRef.current * 2,
          MAX_BACKOFF_MS,
        );
        // After a few doublings we hit the cap; reset toward the middle
        // of the range so reconnects keep trying at a reasonable cadence.
        if (backoffRef.current >= MAX_BACKOFF_MS) {
          backoffRef.current = MAX_BACKOFF_MS;
        }

        reconnectTimeoutRef.current = setTimeout(() => {
          if (mountedRef.current) {
            connect();
          }
        }, delay);
      };
    };

    connect();

    return () => {
      mountedRef.current = false;
      cleanup();
    };
    // Reconnect when the debounced symbols list or token changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSymbols, token, CLIENT_API_URL]);

  return { prices, isConnected };
}

export default usePriceStream;
