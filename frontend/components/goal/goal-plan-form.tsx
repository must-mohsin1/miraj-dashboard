"use client";

import { useState } from "react";
import type { GoalNowResponse } from "@/lib/goal-types";

export function GoalPlanForm({
  initial,
}: {
  token?: string | null;
  initial: GoalNowResponse | null;
}) {
  const [target, setTarget] = useState(String(initial?.goal?.target_return_pct ?? 35));
  const [redeem, setRedeem] = useState(String(initial?.goal?.redeem_pct ?? 40));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const session = await fetch("/api/auth/session").then((r) => r.json()).catch(() => null);
    const accessToken = session?.user?.accessToken as string | undefined;
    if (!accessToken) {
      setError("Sign in to save a goal.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/goal/now", {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          target_return_pct: Number(target),
          redeem_pct: Number(redeem),
          exchange: "mexc",
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Save failed (${res.status})`);
      }
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const reinvest = 100 - (Number(redeem) || 0);

  return (
    <form onSubmit={onSubmit} className="border border-[#2A2620] bg-[#161411] p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
        This month's plan
      </h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="text-sm text-[#8E8778]">
          Target return %
          <input
            type="number"
            min={0.1}
            max={500}
            step={0.1}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="mt-1 w-full border border-[#2A2620] bg-[#0F0E0C] px-3 py-2 font-mono text-[#EDE7DB]"
          />
        </label>
        <label className="text-sm text-[#8E8778]">
          Redeem % of profit
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={redeem}
            onChange={(e) => setRedeem(e.target.value)}
            className="mt-1 w-full border border-[#2A2620] bg-[#0F0E0C] px-3 py-2 font-mono text-[#EDE7DB]"
          />
        </label>
      </div>
      <p className="mt-2 font-mono text-xs text-[#8E8778]">
        Reinvest {Number.isFinite(reinvest) ? reinvest : "—"}% · Miraj does not withdraw funds.
      </p>
      {error && <p className="mt-2 text-sm text-[#C96A55]">{error}</p>}
      <button
        type="submit"
        disabled={saving}
        className="mt-4 border border-[#C2A36B] px-4 py-2 text-sm text-[#C2A36B] disabled:opacity-50"
      >
        {saving ? "Saving…" : "Save month"}
      </button>
    </form>
  );
}
