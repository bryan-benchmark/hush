import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import { goldManifestPath } from "@/lib/labeling";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const name = String(req.nextUrl.searchParams.get("manifest") ?? "GOLD_DEV_V1");
  if (!/^GOLD_[A-Z0-9_]+$/.test(name)) {
    return NextResponse.json({ error: "bad manifest name" }, { status: 400 });
  }
  const p = goldManifestPath(name);
  if (!fs.existsSync(p)) {
    return NextResponse.json({ error: "manifest not found" }, { status: 404 });
  }
  const manifest = JSON.parse(fs.readFileSync(p, "utf8")) as {
    id?: string;
    coverage?: Array<Record<string, unknown>>;
  };
  return NextResponse.json({ id: manifest.id ?? name, coverage: manifest.coverage ?? [] });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const session = String(body.session ?? "");
  const from = Number(body.from_seconds);
  const to = Number(body.to_seconds);
  if (!session || !(to > from)) {
    return NextResponse.json({ error: "session, from_seconds, and to_seconds required" }, { status: 400 });
  }
  const name = String(body.manifest ?? "GOLD_DEV_V1");
  if (!/^GOLD_[A-Z0-9_]+$/.test(name)) {
    return NextResponse.json({ error: "bad manifest name" }, { status: 400 });
  }
  const p = goldManifestPath(name);
  if (!fs.existsSync(p)) {
    return NextResponse.json({ error: "manifest not found" }, { status: 404 });
  }
  const manifest = JSON.parse(fs.readFileSync(p, "utf8")) as {
    coverage?: Array<Record<string, unknown>>;
  };
  const rate = Number(body.sample_rate_hz ?? 48000);
  const range = {
    session,
    from_seconds: from,
    to_seconds: to,
    from_sample: Math.round(from * rate),
    to_sample: Math.round(to * rate),
    fully_annotated: body.fully_annotated !== false,
    note: body.note ? String(body.note) : null,
    created_at: new Date().toISOString(),
  };
  manifest.coverage = [...(manifest.coverage ?? []), range];
  fs.writeFileSync(p, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  return NextResponse.json({ ok: true, coverage: range });
}
