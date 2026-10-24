export function publicHost(host: string): boolean {
  const name = host.replace(/:\d+$/, "").replace(/^\[|\]$/g, "").toLowerCase();
  return name.endsWith(".hosted.app") || name === "ohush.co" || name.endsWith(".ohush.co");
}
