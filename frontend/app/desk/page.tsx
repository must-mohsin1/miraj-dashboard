import { CollectorWorkspace } from "@/components/decision-desk/collector-workspace";
import { getAccessToken } from "@/lib/auth";
import { fetchLatestCollectorReport } from "@/lib/collector-reports-api";
import type { LatestCollectorReportResponse } from "@/lib/collector-report-types";

export const dynamic = "force-dynamic";

/**
 * Auth is enforced by the root middleware. The workspace reads the collector
 * API only; it cannot write a report, an exchange, or collector state.
 */
export default async function DeskPage() {
  const token = await getAccessToken();
  let response: LatestCollectorReportResponse = {
    status: "unavailable",
    stale: true,
    received_at: null,
    report: null,
  };

  if (token) {
    try {
      response = await fetchLatestCollectorReport("SOLUSDT", token);
    } catch {
      // Until Tasks 1–3 are deployed, and during any API failure, render no inferred verdict.
    }
  }

  return <CollectorWorkspace response={response} />;
}
