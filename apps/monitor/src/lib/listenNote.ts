export type ListenTags = {
  what: string;
  who: string;
  tags: string[];
  kind: "splice" | "whole";
};

const TAG_RULES: { id: string; test: RegExp }[] = [
  { id: "commercial", test: /\b(ad|ads|advert|advertisement|commercial|spot|promo|promotion)\b/i },
  { id: "return", test: /\b(return|back to the game|coming back|we'?re back|were back)\b/i },
  { id: "departure", test: /\b(departure|going to break|to break|throw to|toss)\b/i },
  { id: "program", test: /\b(program|booth|play[- ]by[- ]play|in[- ]game)\b/i },
  { id: "announcer", test: /\b(announcer|broadcaster|commentator|host)\b/i },
  { id: "crowd", test: /\b(crowd|cheer|cheering|stadium|fans)\b/i },
  { id: "music", test: /\b(music|song|jingle|sting|bed)\b/i },
  { id: "studio", test: /\bstudio\b/i },
  { id: "replay", test: /\breplay\b/i },
  { id: "uncertain", test: /\b(unsure|not sure|uncertain|idk|don'?t know|dont know)\b/i },
];

export function coversClip(start: number, end: number, duration: number) {
  return start <= 0.05 && end >= Math.max(0.2, duration) - 0.05;
}

export function splitNote(text: string, start = 0, end = 0, duration = 0): ListenTags {
  const raw = text.trim().replace(/\s+/g, " ");
  const parts = raw.split(/\s+·\s+/);
  const what = (parts[0] || "").trim();
  const who = parts.slice(1).join(" · ").trim();
  const tags = TAG_RULES.filter((rule) => rule.test.test(raw)).map((rule) => rule.id);
  const kind = duration > 0 && coversClip(start, end, duration) ? "whole" : "splice";
  if (kind === "whole") tags.push("whole");
  else if (end - start >= 0.2) tags.push("splice");
  if (who) tags.push("named");
  return { what, who, tags: [...new Set(tags)], kind };
}

export function noteLine(what: string, who: string) {
  return [what, who].filter(Boolean).join(" · ");
}

export function judgmentFor(tags: string[], allowed: Set<string>) {
  return tags.find((tag) => allowed.has(tag)) ?? null;
}

export function clipHasSplice(regions: { start_s: number; end_s: number }[], duration: number) {
  return regions.some((region) => !coversClip(region.start_s, region.end_s, duration));
}

export type StoredRegion = {
  start_s: number;
  end_s: number;
  what: string;
  who: string;
  tags: string[];
  kind: "splice" | "whole";
};

export function normalizeRegions(
  input: { start_s?: number; end_s?: number; what?: string; who?: string }[],
  duration: number,
): { ok: true; regions: StoredRegion[]; tags: string[] } | { ok: false; error: string } {
  if (input.length > 30) return { ok: false, error: "too many boxes" };
  const regions: StoredRegion[] = [];
  for (const region of input) {
    const start = Number(region.start_s);
    const end = Number(region.end_s);
    const parsed = splitNote(noteLine(String(region.what ?? ""), String(region.who ?? "")), start, end, duration);
    if (!parsed.what || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > duration + 0.05 || end - start < 0.05) {
      return { ok: false, error: "each box needs a span and what it is" };
    }
    regions.push({
      start_s: Math.round(start * 100) / 100,
      end_s: Math.round(end * 100) / 100,
      what: parsed.what.slice(0, 200),
      who: parsed.who.slice(0, 200),
      tags: parsed.tags,
      kind: parsed.kind,
    });
  }
  regions.sort((a, b) => a.start_s - b.start_s);
  if (regions.some((region) => region.kind === "whole") && regions.some((region) => region.kind === "splice")) {
    return { ok: false, error: "a spliced clip cannot take the whole clip" };
  }
  return { ok: true, regions, tags: [...new Set(regions.flatMap((region) => region.tags))] };
}
