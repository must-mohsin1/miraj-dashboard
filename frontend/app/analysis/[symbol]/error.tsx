"use client";

import { useEffect } from "react";

export default function AnalysisError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[analysis/error]", error?.message, error?.stack, error?.digest);
  }, [error]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <h2 className="text-lg font-semibold text-slate-100">Analysis page error</h2>
      <pre className="overflow-auto rounded-lg border border-red-800/50 bg-red-500/5 p-4 text-xs text-red-300">
        {error?.message || "Unknown error"}
        {"\n\n"}
        {error?.stack || "No stack trace"}
        {"\n\n"}
        digest: {error?.digest || "none"}
      </pre>
      <button
        onClick={reset}
        className="rounded-md bg-slate-800 px-4 py-2 text-sm text-slate-100 hover:bg-slate-700"
      >
        Retry
      </button>
    </div>
  );
}
