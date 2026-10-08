import { NextResponse } from "next/server";
import { ensureLive, liveFetch } from "@/lib/liveEngine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST() {
  const boot = await ensureLive();
  if (!boot.ok) {
    return NextResponse.json({ ok: false, error: boot.error }, { status: 503 });
  }
  const devices = await liveFetch("/devices");
  const state = await liveFetch("/state");
  return NextResponse.json({
    ok: true,
    devices: devices.json,
    state: state.json,
  });
}
