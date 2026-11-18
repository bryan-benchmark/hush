import { NextRequest, NextResponse } from "next/server";
import { PHONE_COOKIE, localHost, phoneCode, sameCode } from "@/lib/phoneAccess";
import { FARM_COOKIE, farmCode, sameFarmCode } from "@/lib/farmAccess";
import { isPublicSite } from "@/lib/publicSite";

export function middleware(request: NextRequest) {
  const host = request.headers.get("host") || "";
  const forwarded = request.headers.get("x-forwarded-host") || "";
  const path = request.nextUrl.pathname;

  if (isPublicSite(host, forwarded)) {
    if (
      path.startsWith("/_next") ||
      path === "/favicon.ico" ||
      path === "/crowd" ||
      path.startsWith("/crowd/") ||
      path.startsWith("/api/crowd")
    ) {
      return NextResponse.next();
    }

    // Home on ohush.co → verdict labeling (crowd stays at /crowd).
    if (path === "/" || path === "") {
      const home = request.nextUrl.clone();
      home.pathname = "/verdict";
      home.search = "";
      return NextResponse.redirect(home);
    }

    // Solo /farm, /verdict, and lab /dashboard on ohush.co — same password gate.
    const farmPath =
      path === "/farm" ||
      path.startsWith("/farm/") ||
      path.startsWith("/api/farm") ||
      path === "/verdict" ||
      path.startsWith("/verdict/") ||
      path === "/dashboard" ||
      path.startsWith("/dashboard/") ||
      path === "/overnight" ||
      path === "/api/overnight" ||
      path === "/status" ||
      path.startsWith("/api/lab-status");
    if (farmPath) {
      if (path === "/farm/enter" || path === "/api/farm/enter") {
        return NextResponse.next();
      }
      const code = farmCode();
      const cookie = request.cookies.get(FARM_COOKIE)?.value || "";
      if (code && sameFarmCode(cookie, code)) {
        // Keep the URL as /dashboard; serve via the lab tunnel proxy under /verdict.
        if (path === "/dashboard" || path === "/dashboard.html" || path === "/overnight") {
          const rewrite = request.nextUrl.clone();
          rewrite.pathname = "/verdict/dashboard";
          return NextResponse.rewrite(rewrite);
        }
        if (path === "/api/overnight") {
          const rewrite = request.nextUrl.clone();
          rewrite.pathname = "/verdict/api/overnight";
          return NextResponse.rewrite(rewrite);
        }
        return NextResponse.next();
      }
      const enter = request.nextUrl.clone();
      enter.pathname = "/farm/enter";
      enter.search = "";
      const next =
        path.startsWith("/api/farm") || path.startsWith("/api/lab-status")
          ? "/status"
          : path === "/dashboard" ||
              path.startsWith("/dashboard/") ||
              path === "/overnight" ||
              path === "/api/overnight"
            ? "/dashboard"
            : path.startsWith("/verdict")
              ? "/verdict"
              : path;
      enter.searchParams.set("next", next);
      return NextResponse.redirect(enter);
    }

    const dest = request.nextUrl.clone();
    dest.pathname = "/crowd";
    dest.search = "";
    return NextResponse.redirect(dest);
  }

  if (localHost(host)) return NextResponse.next();

  if (path.startsWith("/_next") || path === "/phone/enter" || path === "/api/phone/enter") {
    return NextResponse.next();
  }
  const code = phoneCode();
  const cookie = request.cookies.get(PHONE_COOKIE)?.value || "";
  if (code && sameCode(cookie, code)) return NextResponse.next();
  const enter = request.nextUrl.clone();
  enter.pathname = "/phone/enter";
  enter.search = "";
  if (
    path.startsWith("/phone") ||
    path.startsWith("/loud") ||
    path.startsWith("/review") ||
    path.startsWith("/breaks") ||
    path.startsWith("/crowd") ||
    path.startsWith("/farm") ||
    path.startsWith("/api/farm") ||
    path.startsWith("/verdict") ||
    path.startsWith("/dashboard") ||
    path === "/overnight" ||
    path === "/api/overnight" ||
    path.startsWith("/status") ||
    path.startsWith("/api/lab-status")
  ) {
    enter.searchParams.set(
      "next",
      path.startsWith("/api/farm") || path.startsWith("/api/lab-status")
        ? "/status"
        : path === "/dashboard" ||
            path.startsWith("/dashboard/") ||
            path === "/overnight" ||
            path === "/api/overnight"
          ? "/dashboard"
          : path.startsWith("/verdict")
            ? "/verdict"
            : path,
    );
  }
  return NextResponse.redirect(enter);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
