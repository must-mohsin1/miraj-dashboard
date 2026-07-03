"use client";

import { useEffect, useState } from "react";
import type { JSX } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { CheckCircle2, Loader2, MinusCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import { useClientToken } from "@/hooks/use-client-token";
import type { ExchangesResponse, KeysResponse } from "@/lib/types";

/**
 * ExchangeSelector — Client Component.
 *
 * A prominent, card-style exchange picker that fetches the list of supported
 * exchanges from `GET /api/v1/portfolio/exchanges` and, for each exchange,
 * checks the connection status via `GET /api/v1/portfolio/{exchange}/keys`.
 * Every exchange is rendered as a selectable card showing its logo and a
 * connected / disconnected / unknown badge.
 *
 * Selecting an exchange persists the choice to the URL query string
 * (`/portfolio?exchange=binance`) so that the server component re-renders
 * with that exchange's data and back-button / refresh work.
 *
 * Falls back to a static list (`["mexc", "binance", "bybit"]`) if the backend
 * is unavailable.
 */

const FALLBACK_EXCHANGES = ["mexc", "binance", "bybit"] as const;

/** Per-exchange connection state. */
type ConnStatus = "connected" | "disconnected" | "loading" | "unknown";

function titleCase(slug: string): string {
  return slug.charAt(0).toUpperCase() + slug.slice(1);
}

interface ExchangeSelectorProps {
  /** The currently-selected exchange slug (from searchParams). */
  value: string;
}

/**
 * Inline brand logos for the supported exchanges (no external icon dependency).
 * Each is a compact SVG sized to fit a 20×20 box. Unknown exchanges fall back
 * to the first letter of their name rendered by the card itself.
 */
function ExchangeLogo({ slug }: { slug: string }): JSX.Element | null {
  switch (slug) {
    case "binance":
      return (
        <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden role="img">
          <path
            fill="#F0B90B"
            d="M12 2.4 14.4 4.8 9.6 4.8 12 2.4Zm5.4 5.4 2.4 2.4-2.4 2.4-2.4-2.4 2.4-2.4ZM12 7.2 16.8 12 12 16.8 7.2 12 12 7.2ZM4.2 10.2 6.6 7.8 9 10.2 6.6 12.6 4.2 10.2Zm11.4 6.6 2.4-2.4 2.4 2.4-2.4 2.4-2.4-2.4ZM9.6 19.2 12 16.8 14.4 19.2 12 21.6 9.6 19.2Z"
          />
          <path
            fill="#F0B90B"
            d="M7.8 9.6 5.4 12l2.4 2.4 2.4-2.4-2.4-2.4Zm4.2 9.6 2.4-2.4L12 14.4l-2.4 2.4L12 19.2Zm4.2-4.2 2.4-2.4-2.4-2.4-2.4 2.4 2.4 2.4ZM12 9.6 9.6 12 12 14.4 14.4 12 12 9.6Z"
            opacity="0.3"
          />
        </svg>
      );
    case "bybit":
      return (
        <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden role="img">
          <rect width="24" height="24" rx="5" fill="#F7A600" />
          <path
            fill="#1B1B1B"
            d="M5.5 8.2h6.9c.6 0 1 .3 1 .9 0 .6-.4.9-1 .9H9.6v5.7c0 .6-.4 1-1 1s-1-.4-1-1V10H5.5c-.6 0-1-.3-1-.9 0-.6.4-.9 1-.9Zm9.6 0h3.4c1.7 0 2.9 1.2 2.9 3 0 1.8-1.2 3-2.9 3h-2.4v2.5c0 .6-.4 1-1 1s-1-.4-1-1V9.1c0-.6.4-.9 1-.9Z"
          />
        </svg>
      );
    case "mexc":
      return (
        <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden role="img">
          <rect width="24" height="24" rx="5" fill="#1972E2" />
          <path
            fill="#fff"
            d="M5 16.5v-9l3.5 4 3.5-4 3.5 4 3.5-4v9l-3.5-4-3.5 4-3.5-4L5 16.5Z"
          />
        </svg>
      );
    default:
      return null;
  }
}

function StatusBadge({ status }: { status: ConnStatus }): JSX.Element {
  if (status === "loading") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        <Loader2 className="h-3 w-3 animate-spin" />
        Checking
      </span>
    );
  }
  if (status === "connected") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-400">
        <CheckCircle2 className="h-3 w-3" />
        Connected
      </span>
    );
  }
  if (status === "disconnected") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-slate-600 bg-slate-800/60 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-400">
        <MinusCircle className="h-3 w-3" />
        Not linked
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-800/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-500">
      Offline
    </span>
  );
}

export function ExchangeSelector({ value }: ExchangeSelectorProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = useClientToken();
  const [exchanges, setExchanges] = useState<string[]>([...FALLBACK_EXCHANGES]);
  const [statuses, setStatuses] = useState<Record<string, ConnStatus>>({});

  // Fetch the list of supported exchanges from the backend on mount.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/portfolio/exchanges")
      .then((res) => (res.ok ? res.json() : null))
      .then((data: ExchangesResponse | null) => {
        if (!cancelled && data?.exchanges?.length) {
          setExchanges(data.exchanges);
          // Initialize every exchange to "loading".
          setStatuses((prev) => {
            const next: Record<string, ConnStatus> = { ...prev };
            for (const slug of data.exchanges) {
              next[slug] = "loading";
            }
            return next;
          });
        }
      })
      .catch(() => {
        // Backend / ccxt unavailable → keep the fallback list.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Check connection status for each exchange once we have a token.
  // Re-runs whenever the token or the exchange list changes.
  useEffect(() => {
    if (!token) {
      // No auth token — mark all as "unknown" (can't check).
      const cleared: Record<string, ConnStatus> = {};
      for (const slug of exchanges) cleared[slug] = "unknown";
      setStatuses(cleared);
      return;
    }

    let cancelled = false;
    const controllers: AbortController[] = [];

    async function checkOne(slug: string) {
      const ctrl = new AbortController();
      controllers.push(ctrl);
      try {
        const res = await fetch(`/api/v1/portfolio/${slug}/keys`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: ctrl.signal,
        });
        if (cancelled) return;
        if (!res.ok) {
          setStatuses((prev) => ({ ...prev, [slug]: "unknown" }));
          return;
        }
        const data: KeysResponse = await res.json();
        setStatuses((prev) => ({
          ...prev,
          [slug]: data.connected ? "connected" : "disconnected",
        }));
      } catch {
        if (!cancelled) {
          setStatuses((prev) => ({ ...prev, [slug]: "unknown" }));
        }
      }
    }

    // Mark all as loading, then probe each in parallel.
    setStatuses((prev) => {
      const next = { ...prev };
      for (const slug of exchanges) next[slug] = "loading";
      return next;
    });
    for (const slug of exchanges) checkOne(slug);

    return () => {
      cancelled = true;
      for (const ctrl of controllers) ctrl.abort();
    };
  }, [token, exchanges]);

  function handleChange(next: string) {
    if (next === value) return;
    // Build the new URL preserving other search params.
    const params = new URLSearchParams(searchParams.toString());
    params.set("exchange", next);
    router.push(`/portfolio?${params.toString()}`);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Select Exchange
        </h2>
        <span className="text-[11px] text-slate-500">
          {Object.values(statuses).filter((s) => s === "connected").length} of{" "}
          {exchanges.length} linked
        </span>
      </div>

      <div
        role="radiogroup"
        aria-label="Select exchange"
        className="grid grid-cols-1 gap-3 sm:grid-cols-3"
      >
        {exchanges.map((slug) => {
          const isSelected = slug === value;
          const status = statuses[slug];
          return (
            <button
              key={slug}
              type="button"
              role="radio"
              aria-checked={isSelected}
              onClick={() => handleChange(slug)}
              className={cn(
                "flex items-center gap-3 rounded-xl border p-4 text-left transition-all",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60",
                isSelected
                  ? "border-emerald-500/70 bg-emerald-500/10 shadow-lg shadow-emerald-500/10"
                  : "border-slate-800 bg-slate-900/60 hover:border-slate-700 hover:bg-slate-800/60",
              )}
            >
              <span
                className={cn(
                  "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border",
                  isSelected
                    ? "border-emerald-500/50 bg-emerald-500/10"
                    : "border-slate-700 bg-slate-950/60",
                )}
              >
                <ExchangeLogo slug={slug} />
              </span>

              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span
                  className={cn(
                    "truncate text-sm font-semibold",
                    isSelected ? "text-emerald-300" : "text-slate-100",
                  )}
                >
                  {titleCase(slug)}
                </span>
                {isSelected && (
                  <span className="text-[11px] font-medium text-emerald-400/80">
                    Active
                  </span>
                )}
              </span>

              <StatusBadge status={status ?? "unknown"} />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default ExchangeSelector;
