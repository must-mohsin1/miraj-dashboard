"use client";

import { AlertCircle, Bell, Mail, Plus, Send, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMutation } from "@/hooks/use-mutation";
import type { AlertChannel, PairSettingsResponse } from "@/lib/types";

/**
 * AlertPreferencesForm — Client Component.
 *
 * Two-part settings panel:
 *
 *  1. **Alert Channels** — lists configured delivery channels from
 *     `GET /api/v1/settings/channels`. The dashboard currently exposes a
 *     Telegram configuration form via `POST /api/v1/settings/channels`.
 *     Each channel can be deleted (DELETE) or toggled (PUT enabled).
 *
 *  2. **Per-Pair Thresholds** — lists pair-level alert settings from
 *     `GET /api/v1/settings/pairs` (read-only summary; full editing is done
 *     on the scanner page).
 *
 * The initial data is fetched by the parent Server Component and passed in;
 * mutations here use the `useMutation` hook and revalidate via `router.refresh`.
 */

interface AlertPreferencesFormProps {
  token: string | null;
  channels: AlertChannel[];
  pairSettings: PairSettingsResponse[];
  fetchError: boolean;
}

export function AlertPreferencesForm({
  token,
  channels,
  pairSettings,
  fetchError,
}: AlertPreferencesFormProps) {
  // New channel form state
  const [tgToken, setTgToken] = useState("");
  const [tgChatId, setTgChatId] = useState("");

  const {
    trigger: createChannel,
    isMutating: isCreating,
    error: createError,
  } = useMutation("/api/v1/settings/channels", "POST");

  const [actionId, setActionId] = useState<number | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  async function handleAddChannel(e: React.FormEvent) {
    e.preventDefault();
    const t = tgToken.trim();
    const c = tgChatId.trim();
    if (!t || !c) return;
    try {
      await createChannel(
        {
          channel_type: "telegram",
          config: { bot_token: t, chat_id: c },
          enabled: true,
        },
        token
      );
      setTgToken("");
      setTgChatId("");
      // Revalidate server component
      window.location.reload();
    } catch {
      // error surfaced via createError
    }
  }

  async function handleDeleteChannel(id: number) {
    setActionId(id);
    setLocalError(null);
    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`/api/v1/settings/channels/${id}`, {
        method: "DELETE",
        headers,
      });
      if (!res.ok && res.status !== 204) {
        const d = await res.json().catch(() => null);
        throw new Error(
          `Delete failed: ${res.status}${d?.detail ? ` — ${d.detail}` : ""}`
        );
      }
      window.location.reload();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionId(null);
    }
  }

  async function handleToggleChannel(channel: AlertChannel) {
    setActionId(channel.id);
    setLocalError(null);
    try {
      const headers: HeadersInit = { "Content-Type": "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`/api/v1/settings/channels/${channel.id}`, {
        method: "PUT",
        headers,
        body: JSON.stringify({ enabled: !channel.enabled }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => null);
        throw new Error(
          `Update failed: ${res.status}${d?.detail ? ` — ${d.detail}` : ""}`
        );
      }
      window.location.reload();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionId(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {fetchError && (
        <div className="flex items-start gap-2 rounded-md border border-amber-800/50 bg-amber-500/10 p-3 text-sm text-amber-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Could not load alert settings from the backend. You can still
            add channels below.
          </span>
        </div>
      )}

      {(localError || createError) && (
        <div className="flex items-start gap-2 rounded-md border border-red-800/50 bg-red-500/10 p-3 text-sm text-red-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="break-words">
            {localError ?? createError?.message}
          </span>
        </div>
      )}

      {/* Channels list */}
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-base font-semibold text-slate-100">
            Alert Channels
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-4 text-sm text-slate-400">
            Telegram can be configured in this dashboard today. Discord and
            email delivery are coming soon and cannot be configured here.
          </p>
          <dl className="mb-4 grid gap-2 rounded-lg border border-slate-800 p-3 text-sm sm:grid-cols-3">
            <ChannelDeliveryState
              label="Telegram"
              state={deliveryState(channels, "telegram")}
            />
            <ChannelDeliveryState
              label="Discord"
              state={deliveryState(channels, "discord")}
            />
            <ChannelDeliveryState
              label="Email"
              state={deliveryState(channels, "email")}
            />
          </dl>
          {channels.length === 0 ? (
            <p className="text-sm text-slate-400">
              No alert channels configured. Add a Telegram channel below to
              start receiving signals.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-slate-800">
              <Table>
                <TableHeader>
                  <TableRow className="border-slate-800 hover:bg-transparent">
                    <TableHead className="text-slate-500">Type</TableHead>
                    <TableHead className="text-slate-500">Details</TableHead>
                    <TableHead className="text-slate-500">Status</TableHead>
                    <TableHead className="text-right text-slate-500">
                      Actions
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {channels.map((ch) => (
                    <TableRow
                      key={ch.id}
                      className="border-slate-800/60 last:border-0 hover:bg-slate-800/30"
                    >
                      <TableCell className="font-medium capitalize text-slate-100">
                        {ch.channel_type}
                      </TableCell>
                      <TableCell className="text-slate-400">
                        {summariseChannel(ch)}
                      </TableCell>
                      <TableCell>
                        <button
                          onClick={() => handleToggleChannel(ch)}
                          disabled={actionId === ch.id}
                          className="cursor-pointer disabled:opacity-50"
                        >
                          <Badge
                            variant="outline"
                            className={
                              ch.enabled
                                ? "border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
                                : "border-slate-700 bg-slate-800/50 text-slate-500"
                            }
                          >
                            {ch.enabled ? "Active" : "Disabled"}
                          </Badge>
                        </button>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-red-400 hover:bg-red-500/10 hover:text-red-300"
                          onClick={() => handleDeleteChannel(ch.id)}
                          disabled={actionId === ch.id}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Telegram channel form */}
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base font-semibold text-slate-100">
            <Plus className="h-4 w-4 text-emerald-400" />
            Add Telegram Channel
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={handleAddChannel}
            className="flex flex-col gap-4 sm:flex-row sm:items-end"
          >
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="tg_token" className="text-slate-200">
                Bot Token
              </Label>
              <Input
                id="tg_token"
                type="password"
                placeholder="123456:ABC-…"
                value={tgToken}
                onChange={(e) => setTgToken(e.target.value)}
                disabled={isCreating}
                className="border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
              />
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="tg_chat_id" className="text-slate-200">
                Chat ID
              </Label>
              <Input
                id="tg_chat_id"
                type="text"
                placeholder="-1001234567890"
                value={tgChatId}
                onChange={(e) => setTgChatId(e.target.value)}
                disabled={isCreating}
                className="border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
              />
            </div>
            <Button
              type="submit"
              disabled={isCreating || !tgToken.trim() || !tgChatId.trim()}
              className="bg-emerald-600 text-white hover:bg-emerald-500"
            >
              {isCreating ? "Adding…" : "Add Channel"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Per-pair settings summary */}
      {pairSettings.length > 0 && (
        <Card className="border-slate-800 bg-slate-900/60">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-slate-100">
              <Bell className="h-4 w-4 text-slate-400" />
              Per-Pair Alert Thresholds
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-hidden rounded-lg border border-slate-800">
              <Table>
                <TableHeader>
                  <TableRow className="border-slate-800 hover:bg-transparent">
                    <TableHead className="text-slate-500">Pair</TableHead>
                    <TableHead className="text-right text-slate-500">
                      Threshold
                    </TableHead>
                    <TableHead className="text-slate-500">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pairSettings.map((ps) => {
                    const s = ps.settings ?? {};
                    const threshold = (s.alert_threshold as number | undefined) ?? null;
                    const enabled = s.alert_enabled !== false;
                    return (
                      <TableRow
                        key={ps.id}
                        className="border-slate-800/60 last:border-0 hover:bg-slate-800/30"
                      >
                        <TableCell className="font-medium text-slate-100">
                          {ps.pair}
                        </TableCell>
                        <TableCell className="text-right text-slate-300 tabular-nums">
                          {threshold != null ? `${threshold} / 100` : "—"}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={
                              enabled
                                ? "border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
                                : "border-slate-700 bg-slate-800/50 text-slate-500"
                            }
                          >
                            {enabled ? "Enabled" : "Disabled"}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** Produce a human-readable summary of an alert channel's config. */
function summariseChannel(ch: AlertChannel): string {
  const cfg = ch.config ?? {};
  if (ch.channel_type === "telegram") {
    const chatId = cfg.chat_id ?? cfg.channel_id;
    return chatId ? `Chat: ${String(chatId)}` : "Configured";
  }
  if (ch.channel_type === "discord") {
    const webhook = cfg.webhook_url ?? cfg.id;
    return webhook ? `Webhook: ${String(webhook).slice(0, 20)}…` : "Configured";
  }
  if (ch.channel_type === "email") {
    const email = cfg.email ?? cfg.address;
    return email ? String(email) : "Configured";
  }
  return "Configured";
}

function deliveryState(channels: AlertChannel[], channelType: string): string {
  const configuredChannels = channels.filter(
    (channel) => channel.channel_type === channelType
  );

  if (configuredChannels.length === 0) return "Not configured";

  return configuredChannels.some((channel) => channel.enabled)
    ? "Configured — enabled"
    : "Configured — disabled";
}

function ChannelDeliveryState({
  label,
  state,
}: {
  label: string;
  state: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2 sm:flex-col sm:items-start">
      <dt className="font-medium text-slate-200">{label}</dt>
      <dd className="text-slate-400">{state}</dd>
    </div>
  );
}

export default AlertPreferencesForm;
