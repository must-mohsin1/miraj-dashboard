"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, KeyRound, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMutation } from "@/hooks/use-mutation";
import type { ConnectResponse } from "@/lib/types";

/**
 * ConnectForm — Client Component.
 *
 * Two-field form (API key + secret) that POSTs to
 * `POST /api/v1/portfolio/mexc/connect`. On success the page is refreshed
 * via `router.refresh()` so the server component re-renders the connected
 * portfolio dashboard.
 *
 * The backend validates the credentials with a live `fetchBalance` call
 * before persisting them — on a 400 (invalid keys) or 502 (exchange error)
 * the error message is surfaced inline.
 */

interface ConnectFormProps {
  /** The signed-in user's JWT access token (or null when unauthenticated). */
  token: string | null;
}

export function ConnectForm({ token }: ConnectFormProps) {
  const router = useRouter();
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");

  const {
    trigger,
    isMutating,
    error,
  } = useMutation<ConnectResponse, { api_key: string; api_secret: string }>(
    "/api/v1/portfolio/mexc/connect",
    "POST"
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const key = apiKey.trim();
    const secret = apiSecret.trim();
    if (!key || !secret) return;
    try {
      await trigger({ api_key: key, api_secret: secret }, token);
      // Server component re-fetches keys → renders the dashboard.
      router.refresh();
    } catch {
      // Error rendered inline via `error`.
    }
  }

  return (
    <div className="mx-auto w-full max-w-md">
      <form
        onSubmit={handleSubmit}
        className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 shadow-lg"
      >
        <div className="mb-6 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-emerald-400" />
            <h2 className="text-lg font-semibold text-slate-100">
              Connect MEXC Account
            </h2>
          </div>
          <p className="text-sm text-slate-400">
            Enter your MEXC API credentials. Keys are encrypted at rest and
            never exposed to the client after submission.
          </p>
        </div>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="api_key" className="text-slate-200">
              API Key
            </Label>
            <Input
              id="api_key"
              type="text"
              autoComplete="off"
              placeholder="mex…"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              disabled={isMutating}
              className="border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="api_secret" className="text-slate-200">
              API Secret
            </Label>
            <Input
              id="api_secret"
              type="password"
              autoComplete="off"
              placeholder="••••••••••••"
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
              disabled={isMutating}
              className="border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-md border border-red-800/50 bg-red-500/10 p-3 text-sm text-red-400">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="break-words">{error.message}</span>
            </div>
          )}

          <Button
            type="submit"
            disabled={isMutating || !apiKey.trim() || !apiSecret.trim()}
            className="w-full bg-emerald-600 text-white hover:bg-emerald-500"
          >
            {isMutating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Validating…
              </>
            ) : (
              "Connect"
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}

export default ConnectForm;
