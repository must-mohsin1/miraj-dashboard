"use client";

import { useState } from "react";
import type { CollectorReport, LatestCollectorReportResponse } from "@/lib/collector-report-types";

export function AuditDrawer({ response, report }: { response: LatestCollectorReportResponse; report: CollectorReport }) {
  const [open, setOpen] = useState(false);
  return <div className="border-t border-slate-800 pt-4"><button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} className="border border-slate-700 px-3 py-2 text-xs font-medium text-slate-300 hover:border-brass-400 hover:text-brass-300">{open ? "Close audit record" : "Open audit record"}</button>{open && <dl className="mt-3 grid gap-3 border-y border-slate-800 py-3 text-xs sm:grid-cols-2"><div><dt className="uppercase tracking-[0.12em] text-slate-500">Report ID</dt><dd className="mt-1 font-mono text-slate-200">{report.report_id}</dd></div><div><dt className="uppercase tracking-[0.12em] text-slate-500">SHA-256 prefix</dt><dd className="mt-1 font-mono text-slate-200">{report.payload_sha256.slice(0, 12)}</dd></div><div><dt className="uppercase tracking-[0.12em] text-slate-500">Generated</dt><dd className="mt-1 font-mono text-slate-200">{report.generated_at}</dd></div><div><dt className="uppercase tracking-[0.12em] text-slate-500">Received / validation</dt><dd className="mt-1 font-mono text-slate-200">{response.received_at ?? "—"} / {response.status}</dd></div></dl>}</div>;
}
