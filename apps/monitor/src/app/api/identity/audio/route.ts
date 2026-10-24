import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { repoRoot } from "@/lib/labeling";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id") ?? "";
  if (!/^[a-z0-9-]+$/.test(id)) {
    return NextResponse.json({ error: "bad id" }, { status: 400 });
  }
  const manifestPath = path.join(repoRoot(), "experiments/identity_probes/manifest.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as {
    clips: Array<{ id: string; file: string }>;
  };
  const clip = manifest.clips.find((row) => row.id === id);
  if (!clip || clip.file.includes("..")) {
    return NextResponse.json({ error: "missing clip" }, { status: 404 });
  }
  const file = path.join(repoRoot(), "experiments/identity_probes", clip.file);
  if (!fs.existsSync(file)) {
    return NextResponse.json({ error: "missing audio" }, { status: 404 });
  }
  const buf = fs.readFileSync(file);
  const total = buf.length;
  const range = req.headers.get("range");
  const headers: Record<string, string> = {
    "Content-Type": "audio/wav",
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, max-age=3600",
  };
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
    if (match) {
      const start = match[1] === "" ? 0 : Number(match[1]);
      const end = match[2] === "" ? total - 1 : Number(match[2]);
      if (start < 0 || end >= total || start > end) {
        return new NextResponse(null, { status: 416, headers: { ...headers, "Content-Range": `bytes */${total}` } });
      }
      const slice = buf.subarray(start, end + 1);
      return new NextResponse(new Uint8Array(slice), {
        status: 206,
        headers: {
          ...headers,
          "Content-Length": String(slice.length),
          "Content-Range": `bytes ${start}-${end}/${total}`,
        },
      });
    }
  }
  return new NextResponse(new Uint8Array(buf), {
    headers: { ...headers, "Content-Length": String(total) },
  });
}
