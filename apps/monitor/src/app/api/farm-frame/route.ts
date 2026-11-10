import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { farmCloudMode } from "@/lib/farmAccess";
import { farmCloudFrame } from "@/lib/farmCloud";

export const runtime = "nodejs";

function allowedFarmPath(p: string) {
  const root = path.resolve(process.env.OHUSH_DATA_ROOT || "C:\\OHushData");
  const resolved = path.resolve(p);
  return resolved === root || resolved.startsWith(root + path.sep);
}

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const id = sp.get("id") || "";
  const file = sp.get("file") || "";
  if ((farmCloudMode() || id) && id) {
    try {
      const buf = await farmCloudFrame(id, file || "0");
      if (!buf) return NextResponse.json({ error: "missing" }, { status: 404 });
      return new NextResponse(buf, {
        status: 200,
        headers: { "Content-Type": "image/jpeg", "Cache-Control": "no-store" },
      });
    } catch (err) {
      return NextResponse.json({ error: String(err) }, { status: 500 });
    }
  }

  const sessionDir = sp.get("session_dir") || "";
  if (!sessionDir || !file) {
    return NextResponse.json({ error: "session_dir and file required (or id)" }, { status: 400 });
  }
  // Allow root JPEGs or stills/<name>.jpg only — no path escape.
  const norm = file.replace(/\\/g, "/");
  if (
    norm.includes("..") ||
    !/^(?:stills\/)?[A-Za-z0-9._-]+\.jpe?g$/i.test(norm)
  ) {
    return NextResponse.json({ error: "bad file" }, { status: 400 });
  }
  if (!allowedFarmPath(sessionDir)) {
    return NextResponse.json({ error: "session_dir outside data root" }, { status: 403 });
  }
  const full = path.join(sessionDir, ...norm.split("/"));
  if (!allowedFarmPath(full) || !fs.existsSync(full)) {
    return NextResponse.json({ error: "missing" }, { status: 404 });
  }
  const buf = fs.readFileSync(full);
  const type = file.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg";
  return new NextResponse(buf, {
    status: 200,
    headers: { "Content-Type": type, "Cache-Control": "no-store" },
  });
}
