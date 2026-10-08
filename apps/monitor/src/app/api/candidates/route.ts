import { NextRequest, NextResponse } from "next/server";
import {
  readJsonl,
  readLabels,
  readRunCandidates,
  readSessionMeta,
  reviewsPath,
} from "@/lib/labeling";
import { labelVisible, roleOf, roleReason } from "@/lib/datasets";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const runId = req.nextUrl.searchParams.get("run_id");
  if (!runId) {
    return NextResponse.json({ error: "run_id required" }, { status: 400 });
  }
  const unseal = req.nextUrl.searchParams.get("unseal");
  const includeFixtures = req.nextUrl.searchParams.get("include") === "acquisition_fixture";
  const candidates = readRunCandidates(runId).filter((row) =>
    labelVisible(String(row.session), unseal, includeFixtures),
  );
  const withheldMap = new Map<string, number>();
  for (const row of readRunCandidates(runId)) {
    const session = String(row.session);
    if (!labelVisible(session, unseal, includeFixtures)) {
      withheldMap.set(session, (withheldMap.get(session) ?? 0) + 1);
    }
  }
  const reviews = readJsonl(reviewsPath()).filter((row) => row.run_id === runId);
  const reviewed = new Set(reviews.map((row) => String(row.proposal_id)));
  const legacy = readLabels();

  const enriched = candidates
    .map((c) => {
      const session = String(c.session);
      let startedAt: string | null = null;
      try {
        startedAt = readSessionMeta(session).started_at;
      } catch {
        startedAt = null;
      }
      const elapsed = Number(c.elapsed_seconds);
      const suggested = c.suggested_out as { elapsed_seconds?: number } | null;
      const row: Record<string, unknown> = {
        ...c,
        labeled: reviewed.has(String(c.proposal_id)),
        started_at: startedAt,
        wall_time:
          startedAt && Number.isFinite(elapsed)
            ? new Date(Date.parse(startedAt) + elapsed * 1000).toISOString()
            : null,
        suggested_out_seconds: suggested?.elapsed_seconds ?? null,
      };
      return row;
    })
    .sort((a, b) => Number(b.score) - Number(a.score));

  const sessions = [...new Set(enriched.map((c) => String(c.session)))];
  return NextResponse.json({
    run_id: runId,
    total: enriched.length,
    labeled: enriched.filter((c) => c.labeled).length,
    sessions,
    withheld: [...withheldMap.entries()].map(([session, count]) => ({
      session,
      count,
      role: roleOf(session),
      reason: roleReason(session),
    })),
    legacy_label_count: legacy.length,
    candidates: enriched,
  });
}
