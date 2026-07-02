"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ChevronDown } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ExchangesResponse } from "@/lib/types";

/**
 * ExchangeSelector — Client Component.
 *
 * A dropdown that fetches the list of supported exchanges from
 * `GET /api/v1/portfolio/exchanges` and persists the selected exchange to
 * the URL query string (`/portfolio?exchange=binance`) so that refresh /
 * back-button work and the server component re-renders with the new
 * exchange's data.
 *
 * Falls back to a static list (`["mexc", "binance", "bybit"]`) if the
 * backend is unavailable.
 */
const FALLBACK_EXCHANGES = ["mexc", "binance", "bybit"];

function titleCase(slug: string): string {
  return slug.charAt(0).toUpperCase() + slug.slice(1);
}

interface ExchangeSelectorProps {
  /** The currently-selected exchange slug (from searchParams). */
  value: string;
}

export function ExchangeSelector({ value }: ExchangeSelectorProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [exchanges, setExchanges] = useState<string[]>(FALLBACK_EXCHANGES);
  const [mounted, setMounted] = useState(false);

  // Fetch the list of supported exchanges from the backend on mount.
  useEffect(() => {
    setMounted(true);
    let cancelled = false;
    fetch("/api/v1/portfolio/exchanges")
      .then((res) => (res.ok ? res.json() : null))
      .then((data: ExchangesResponse | null) => {
        if (!cancelled && data?.exchanges?.length) {
          setExchanges(data.exchanges);
        }
      })
      .catch(() => {
        // Backend / ccxt unavailable → keep the fallback list.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleChange(next: string) {
    if (next === value) return;
    // Build the new URL preserving other search params.
    const params = new URLSearchParams(searchParams.toString());
    params.set("exchange", next);
    router.push(`/portfolio?${params.toString()}`);
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-slate-400 dark:text-slate-500">
        Exchange
      </span>
      <Select value={value} onValueChange={handleChange} disabled={!mounted}>
        <SelectTrigger
          className="w-[140px] border-slate-700 bg-slate-900/60 text-slate-200 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
          aria-label="Select exchange"
        >
          <SelectValue placeholder="Select exchange" />
        </SelectTrigger>
        <SelectContent>
          {exchanges.map((slug) => (
            <SelectItem key={slug} value={slug}>
              {titleCase(slug)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <ChevronDown className="h-4 w-4 text-slate-500" aria-hidden />
    </div>
  );
}

export default ExchangeSelector;
