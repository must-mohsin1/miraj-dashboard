"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, ImagePlus, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type {
  JournalEntryCreateRequest,
  TradeJournalEntry,
} from "@/lib/types";

/**
 * JournalEntryDialog — Client Component.
 *
 * A shadcn Dialog form for creating or editing a trading-journal entry.
 *
 * Fields:
 *  - Symbol (required text input, uppercased)
 *  - Tags (free-text input rendered as removable chips)
 *  - Notes (textarea)
 *  - Lessons (textarea)
 *  - Optional trade metadata (exchange, entry_price, exit_price, pnl, position_id)
 *  - Screenshot upload (drag-and-drop or file picker), shown when editing
 *
 * ## Modes
 *
 * - **Create**: `entry` is null. POSTs to `/api/v1/journal`.
 * - **Edit**: `entry` is provided. PUTs to `/api/v1/journal/{id}`.
 *
 * The dialog calls `onSaved` after a successful create/update so the parent
 * can refresh its list. Screenshot uploads use multipart/form-data and hit
 * `POST /api/v1/journal/{id}/screenshot`.
 */

interface JournalEntryDialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Called when the user requests to close the dialog. */
  onOpenChange: (open: boolean) => void;
  /** Existing entry for edit mode, or null for create mode. */
  entry: TradeJournalEntry | null;
  /** JWT access token (or null when unauthenticated). */
  token: string | null;
  /** Optional default exchange slug applied to new entries. */
  exchange?: string;
  /** Called after a successful create/update so the parent can refresh. */
  onSaved: () => void;
}

export function JournalEntryDialog({
  open,
  onOpenChange,
  entry,
  token,
  exchange,
  onSaved,
}: JournalEntryDialogProps) {
  const isEdit = entry !== null;

  // ── Form state ──────────────────────────────────────────────────────────
  const [symbol, setSymbol] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [lessons, setLessons] = useState("");
  const [entryPrice, setEntryPrice] = useState("");
  const [exitPrice, setExitPrice] = useState("");
  const [pnl, setPnl] = useState("");
  const [showError, setShowError] = useState(false);
  const [saving, setSaving] = useState(false);
  // screenshot state
  const [screenshots, setScreenshots] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // ── Populate form fields when `open` or `entry` changes ────────────────
  useEffect(() => {
    if (!open) return;
    if (entry) {
      setSymbol(entry.symbol);
      const parsed = (entry.tags ?? "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      setTags(parsed);
      setTagsText("");
      setNotes(entry.notes ?? "");
      setLessons(entry.lessons ?? "");
      setEntryPrice(entry.entry_price != null ? String(entry.entry_price) : "");
      setExitPrice(entry.exit_price != null ? String(entry.exit_price) : "");
      setPnl(entry.pnl != null ? String(entry.pnl) : "");
      setScreenshots(entry.screenshots ?? []);
    } else {
      setSymbol("");
      setTags([]);
      setTagsText("");
      setNotes("");
      setLessons("");
      setEntryPrice("");
      setExitPrice("");
      setPnl("");
      setScreenshots([]);
    }
    setShowError(false);
    setUploadError(null);
  }, [open, entry]);

  // ── Tags chip handling ─────────────────────────────────────────────────
  function addTagFromInput() {
    const raw = tagsText.trim();
    if (!raw) return;
    // Allow pasting comma-separated tags.
    const parts = raw
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    setTags((prev) => {
      const lower = new Set(prev.map((t) => t.toLowerCase()));
      const next = [...prev];
      for (const p of parts) {
        if (!lower.has(p.toLowerCase())) {
          next.push(p);
          lower.add(p.toLowerCase());
        }
      }
      return next;
    });
    setTagsText("");
  }

  function removeTag(tag: string) {
    setTags((prev) => prev.filter((t) => t !== tag));
  }

  function handleTagsKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTagFromInput();
    } else if (e.key === "Backspace" && tagsText === "" && tags.length > 0) {
      // Backspace on empty input removes the last chip.
      setTags((prev) => prev.slice(0, -1));
    }
  }

  // ── Screenshot upload ──────────────────────────────────────────────────
  async function uploadFiles(files: FileList | File[]) {
    if (!entry || files.length === 0) return;
    const arr = Array.from(files);
    setUploading(true);
    setUploadError(null);
    try {
      // Fetch token client-side (EventSource-style) for the multipart request.
      let authToken = token;
      if (!authToken) {
        try {
          const res = await fetch("/api/auth/session");
          const data = await res.json();
          authToken = data?.user?.accessToken ?? null;
        } catch {
          authToken = null;
        }
      }

      for (const file of arr) {
        const formData = new FormData();
        formData.append("file", file);
        const res = await fetch(
          `/api/v1/journal/${entry.id}/screenshot`,
          {
            method: "POST",
            headers: authToken
              ? { Authorization: `Bearer ${authToken}` }
              : {},
            body: formData,
          },
        );
        if (!res.ok) {
          let detail = "";
          try {
            detail = (await res.json())?.detail ?? "";
          } catch {
            /* no body */
          }
          throw new Error(
            `Upload failed: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ""}`,
          );
        }
        const data = await res.json();
        if (data?.path) {
          setScreenshots((prev) => [...prev, data.path]);
        }
      }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  function handleFilePick(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      void uploadFiles(e.target.files);
      // Reset so re-selecting the same file fires onChange again.
      e.target.value = "";
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      void uploadFiles(e.dataTransfer.files);
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
  }

  function screenshotFilename(path: string): string {
    try {
      return path.split("/").pop() ?? path;
    } catch {
      return path;
    }
  }

  // ── Save (create / update) ──────────────────────────────────────────────
  async function handleSave() {
    const sym = symbol.trim().toUpperCase();
    if (!sym) {
      setShowError(true);
      return;
    }

    // Fetch token client-side if not provided as a prop.
    let authToken = token;
    if (!authToken) {
      try {
        const res = await fetch("/api/auth/session");
        const data = await res.json();
        authToken = data?.user?.accessToken ?? null;
      } catch {
        authToken = null;
      }
    }

    const headers: HeadersInit = {
      "Content-Type": "application/json",
    };
    if (authToken) headers.Authorization = `Bearer ${authToken}`;

    const tagsStr = tags.length > 0 ? tags.join(",") : null;

    setSaving(true);
    setShowError(false);
    try {
      if (isEdit && entry) {
        // ── Update ──
        const body = {
          notes: notes || null,
          tags: tagsStr,
          lessons: lessons || null,
        };
        const res = await fetch(`/api/v1/journal/${entry.id}`, {
          method: "PUT",
          headers,
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          let detail = "";
          try {
            detail = (await res.json())?.detail ?? "";
          } catch {
            /* no body */
          }
          throw new Error(
            `Update failed: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ""}`,
          );
        }
      } else {
        // ── Create ──
        const body: JournalEntryCreateRequest = {
          symbol: sym,
          exchange: exchange ?? null,
          tags: tagsStr,
          notes: notes || null,
          lessons: lessons || null,
          entry_price: entryPrice ? Number(entryPrice) : null,
          exit_price: exitPrice ? Number(exitPrice) : null,
          pnl: pnl ? Number(pnl) : null,
        };
        const res = await fetch("/api/v1/journal", {
          method: "POST",
          headers,
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          let detail = "";
          try {
            detail = (await res.json())?.detail ?? "";
          } catch {
            /* no body */
          }
          throw new Error(
            `Create failed: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ""}`,
          );
        }
      }
      onSaved();
      onOpenChange(false);
    } catch (err) {
      setShowError(true);
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto bg-slate-900 border-slate-800 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-slate-100">
            {isEdit ? "Edit Journal Entry" : "New Journal Entry"}
          </DialogTitle>
          <DialogDescription className="text-slate-400">
            {isEdit
              ? "Update notes, tags, and lessons for this trade."
              : "Record a trade with notes, tags, and lessons learned."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {/* Symbol */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="je-symbol" className="text-slate-200">
              Symbol
            </Label>
            <Input
              id="je-symbol"
              type="text"
              placeholder="BTCUSDT"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              disabled={isEdit || saving}
              className="border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
            />
            {isEdit && (
              <p className="text-xs text-slate-500">
                Symbol cannot be changed after creation.
              </p>
            )}
          </div>

          {/* Tags — chips */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="je-tags" className="text-slate-200">
              Tags
            </Label>
            <div
              className={cn(
                "flex flex-wrap items-center gap-1.5 rounded-md border border-slate-700 bg-slate-950/50 px-2 py-1.5 min-h-[2.5rem]",
                "focus-within:ring-1 focus-within:ring-ring",
              )}
            >
              {tags.map((tag) => (
                <Badge
                  key={tag}
                  variant="outline"
                  className="border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => removeTag(tag)}
                    className="ml-1 hover:text-emerald-200"
                    aria-label={`Remove tag ${tag}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
              <input
                id="je-tags"
                type="text"
                value={tagsText}
                onChange={(e) => setTagsText(e.target.value)}
                onKeyDown={handleTagsKeyDown}
                onBlur={addTagFromInput}
                placeholder={tags.length === 0 ? "scalp, swing, breakout…" : ""}
                disabled={saving}
                className="flex-1 min-w-[8rem] bg-transparent text-sm text-slate-100 placeholder:text-slate-600 outline-none"
              />
            </div>
            <p className="text-xs text-slate-500">
              Press Enter or comma to add a tag.
            </p>
          </div>

          {/* Notes */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="je-notes" className="text-slate-200">
              Notes
            </Label>
            <textarea
              id="je-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={saving}
              rows={4}
              placeholder="What was the setup? Why did you enter?"
              className="rounded-md border border-slate-700 bg-slate-950/50 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>

          {/* Lessons */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="je-lessons" className="text-slate-200">
              Lessons
            </Label>
            <textarea
              id="je-lessons"
              value={lessons}
              onChange={(e) => setLessons(e.target.value)}
              disabled={saving}
              rows={3}
              placeholder="What did you learn? What would you do differently?"
              className="rounded-md border border-slate-700 bg-slate-950/50 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>

          {/* Trade metadata (create only) */}
          {!isEdit && (
            <div className="grid grid-cols-3 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="je-entry" className="text-slate-200">
                  Entry
                </Label>
                <Input
                  id="je-entry"
                  type="number"
                  step="any"
                  placeholder="50000"
                  value={entryPrice}
                  onChange={(e) => setEntryPrice(e.target.value)}
                  disabled={saving}
                  className="border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="je-exit" className="text-slate-200">
                  Exit
                </Label>
                <Input
                  id="je-exit"
                  type="number"
                  step="any"
                  placeholder="50500"
                  value={exitPrice}
                  onChange={(e) => setExitPrice(e.target.value)}
                  disabled={saving}
                  className="border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="je-pnl" className="text-slate-200">
                  PnL
                </Label>
                <Input
                  id="je-pnl"
                  type="number"
                  step="any"
                  placeholder="500"
                  value={pnl}
                  onChange={(e) => setPnl(e.target.value)}
                  disabled={saving}
                  className="border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
                />
              </div>
            </div>
          )}

          {/* Screenshot upload (edit mode only — needs an entry id) */}
          {isEdit && (
            <div className="flex flex-col gap-1.5">
              <Label className="text-slate-200">Screenshots</Label>
              <div
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                className={cn(
                  "flex flex-col items-center justify-center gap-2 rounded-md border border-dashed p-4 text-center transition-colors",
                  isDragging
                    ? "border-emerald-600 bg-emerald-500/5"
                    : "border-slate-700 bg-slate-950/30",
                )}
              >
                <ImagePlus className="h-5 w-5 text-slate-500" />
                <p className="text-xs text-slate-400">
                  Drag &amp; drop or{" "}
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="text-emerald-400 hover:text-emerald-300 underline"
                  >
                    browse
                  </button>{" "}
                  (PNG/JPEG/WebP, max 5 MB)
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  multiple
                  onChange={handleFilePick}
                  className="hidden"
                />
              </div>
              {uploading && (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Uploading…
                </div>
              )}
              {screenshots.length > 0 && (
                <ul className="flex flex-col gap-1 text-xs text-slate-400">
                  {screenshots.map((s, i) => (
                    <li key={`${s}-${i}`} className="truncate">
                      📎 {screenshotFilename(s)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Errors */}
          {showError && !symbol.trim() && (
            <div className="flex items-start gap-2 rounded-md border border-red-800/50 bg-red-500/10 p-3 text-sm text-red-400">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>Symbol is required.</span>
            </div>
          )}
          {uploadError && (
            <div className="flex items-start gap-2 rounded-md border border-red-800/50 bg-red-500/10 p-3 text-sm text-red-400">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="break-words">{uploadError}</span>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving || uploading}
            className="border-slate-700 bg-slate-900/60 text-slate-200 hover:bg-slate-800 hover:text-slate-100"
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving || uploading || !symbol.trim()}
            className="bg-emerald-600 text-white hover:bg-emerald-500"
          >
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {isEdit ? "Saving…" : "Creating…"}
              </>
            ) : isEdit ? (
              "Save Changes"
            ) : (
              "Create Entry"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default JournalEntryDialog;
