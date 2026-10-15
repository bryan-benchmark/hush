import { NextResponse } from "next/server";
import { ensureLive, liveFetch } from "@/lib/liveEngine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST() {
  const boot = await ensureLive();
  // Engine may finish warming a beat after ensureLive's wait window.
  const state = await liveFetch("/state");
  if (!boot.ok && !(state.res.ok && state.json)) {
    return NextResponse.json({ ok: false, error: boot.error }, { status: 503 });
  }
  if (!state.res.ok) {
    return NextResponse.json({ ok: false, error: boot.error || "Could not get ready." }, { status: 503 });
  }
  const devices = await liveFetch("/devices");
  return NextResponse.json({
    ok: true,
    devices: devices.json,
    state: state.json,
  });
}
