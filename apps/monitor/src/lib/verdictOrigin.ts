/** Upstream for the lab episode viewer (farm_episode_viewer on :3020). */
export function verdictOrigin(): string {
  return (process.env.OHUSH_VERDICT_ORIGIN || "http://127.0.0.1:3020").replace(/\/$/, "");
}
