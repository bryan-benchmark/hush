import { NextRequest, NextResponse } from "next/server";
import { listSessions } from "@/lib/labeling";
import { labelVisible, roleOf, roleReason, SEAL } from "@/lib/datasets";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const unseal = req.nextUrl.searchParams.get("unseal");
  const includeFixtures = req.nextUrl.searchParams.get("include") === "acquisition_fixture";
  const sessions = listSessions().filter((row) => labelVisible(row.session, unseal, includeFixtures));
  const withheld = listSessions()
    .filter((row) => !labelVisible(row.session, unseal, includeFixtures))
    .map((row) => ({
      session: row.session,
      role: roleOf(row.session),
      reason: roleReason(row.session),
    }));
  return NextResponse.json({
    sessions,
    withheld,
    seal: SEAL,
  });
}
