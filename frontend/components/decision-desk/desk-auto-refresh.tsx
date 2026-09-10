"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const DESK_REFRESH_MS = 60_000;

export function DeskAutoRefresh({ lastRefreshedAt }: { lastRefreshedAt: string | null }) {
  const router = useRouter();
  const [lastRefreshed, setLastRefreshed] = useState(lastRefreshedAt);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setChecking(true);
      setLastRefreshed(new Date().toISOString());
      router.refresh();
      window.setTimeout(() => setChecking(false), 750);
    }, DESK_REFRESH_MS);

    return () => window.clearInterval(interval);
  }, [router]);

  return <p className="mt-3 font-mono text-[11px] leading-5 text-slate-500" aria-live="polite"><span>Last refreshed: {lastRefreshed ?? "unavailable"}</span><span className="mx-2" aria-hidden>·</span><span>Collector runs hourly; this desk checks for the latest report every minute.</span>{checking ? <span className="ml-2 text-slate-400">Checking…</span> : null}</p>;
}
