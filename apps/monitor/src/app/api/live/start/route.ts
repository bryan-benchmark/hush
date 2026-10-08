import { NextRequest, NextResponse } from "next/server";
import { ensureLive, liveFetch } from "@/lib/liveEngine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const boot = await ensureLive();
  if (!boot.ok) {
    return NextResponse.json({ ok: false, error: boot.error }, { status: 503 });
  }
  const body = await req.json().catch(() => ({}));
  const { res, json } = await liveFetch("/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return NextResponse.json(json, { status: res.status });
}
