import { NextResponse } from "next/server";
import { ensureLive, liveFetch } from "@/lib/liveEngine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const boot = await ensureLive();
  if (!boot.ok) {
    return NextResponse.json({ ok: false, error: boot.error, recording: false }, { status: 503 });
  }
  const { res, json } = await liveFetch("/state");
  return NextResponse.json(json, { status: res.status });
}
