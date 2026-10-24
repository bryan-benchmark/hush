export function publicHost(host: string): boolean {
  const name = host.replace(/:\d+$/, "").replace(/^\[|\]$/g, "").toLowerCase();
  return name.endsWith(".hosted.app") || name.endsWith(".run.app") || name === "ohush.co" || name.endsWith(".ohush.co");
}

export function isPublicSite(host: string, forwardedHost = ""): boolean {
  if (process.env.NEXT_PUBLIC_OHUSH_PUBLIC_SITE === "1") return true;
  return publicHost(forwardedHost) || publicHost(host);
}
