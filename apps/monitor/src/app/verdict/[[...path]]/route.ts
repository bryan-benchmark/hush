import { NextRequest, NextResponse } from "next/server";
import { verdictOrigin } from "@/lib/verdictOrigin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const HOP = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "upgrade",
]);

function upstreamUrl(parts: string[] | undefined, search: string): string {
  const base = verdictOrigin();
  const suffix = parts?.length ? `/${parts.join("/")}` : "/";
  return `${base}${suffix}${search}`;
}

function filterReqHeaders(src: Headers): Headers {
  const out = new Headers();
  src.forEach((value, key) => {
    if (HOP.has(key.toLowerCase())) return;
    out.set(key, value);
  });
  return out;
}

function filterResHeaders(src: Headers): Headers {
  const out = new Headers();
  src.forEach((value, key) => {
    const k = key.toLowerCase();
    if (HOP.has(k) || k === "content-encoding") return;
    out.set(key, value);
  });
  out.set("Cache-Control", "no-store");
  return out;
}

function offlineHtml(): NextResponse {
  const origin = verdictOrigin();
  const body = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><title>Verdict lab offline</title>
<style>
  body{font:16px/1.45 system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem;color:#1a1a1a}
  code{background:#f2f2f2;padding:.1em .35em;border-radius:4px}
</style></head><body>
  <h1>Verdict lab is offline</h1>
  <p>ohush.co/verdict proxies the Windows lab viewer at <code>${origin}</code>.</p>
  <p>On the lab machine: start the viewer, then a tunnel, and set <code>OHUSH_VERDICT_ORIGIN</code> to that https URL.</p>
  <pre>python -m tools.windows_lab.farm_episode_viewer --no-open
.\\scripts\\verdict.ps1</pre>
</body></html>`;
  return new NextResponse(body, {
    status: 502,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}

async function proxy(req: NextRequest, parts: string[] | undefined): Promise<NextResponse> {
  const url = upstreamUrl(parts, req.nextUrl.search);
  const headers = filterReqHeaders(req.headers);
  const streaming = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      redirect: "manual",
      ...(streaming ? { body: req.body, duplex: "half" as const } : {}),
    });
  } catch {
    return offlineHtml();
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: filterResHeaders(upstream.headers),
  });
}

type Ctx = { params: Promise<{ path?: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function HEAD(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
