import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { name?: string };
  const name = String(body.name || "").trim().replace(/\s+/g, " ").slice(0, 24);
  if (!/^[A-Za-z0-9][A-Za-z0-9 .'-]{0,23}$/.test(name)) {
    return NextResponse.json({ error: "Use your name, up to 24 letters." }, { status: 400 });
  }
  const res = NextResponse.json({ ok: true, name });
  res.cookies.set("ohush_crowd", name, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
  return res;
}
