import { PUBLISHED_VERDICT_ORIGIN } from "@/lib/verdictOrigin.published";

/** Upstream for the lab episode viewer (farm_episode_viewer on :3020). */
export function verdictOrigin(): string {
  // Prefer the URL last shipped in git (quick tunnels go stale in Secret Manager).
  // Optional override for named tunnels / emergency without a redeploy.
  const override = (process.env.OHUSH_VERDICT_ORIGIN_OVERRIDE || "").trim();
  const published = (PUBLISHED_VERDICT_ORIGIN || "").trim();
  const secret = (process.env.OHUSH_VERDICT_ORIGIN || "").trim();
  const raw = override || published || secret || "http://127.0.0.1:3020";
  return raw.replace(/\/$/, "");
}
