export const FARM_COOKIE = "ohush_farm";

/** Solo password for /farm. Prefer dedicated code; fall back to phone code. */
export function farmCode(): string {
  return (process.env.OHUSH_FARM_CODE || process.env.OHUSH_PHONE_CODE || "").trim();
}

export function farmCloudMode(): boolean {
  return (
    process.env.OHUSH_PUBLIC_SITE === "1" ||
    process.env.NEXT_PUBLIC_OHUSH_PUBLIC_SITE === "1"
  );
}

export function sameFarmCode(given: string, expected: string): boolean {
  if (!expected || given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}
