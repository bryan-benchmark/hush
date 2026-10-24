import fs from "fs";
import path from "path";
import queueFile from "@/data/crowdQueue.json";
import { repoRoot } from "@/lib/labeling";

export type Action = "on" | "off";

export type Vote = {
  who: string;
  name?: string;
  action: Action;
  note: string;
  at: string;
};

export type Clip = {
  id: string;
  session: string;
  play_start: number;
  duration: number;
  mark_s?: number;
  caption?: string;
  object?: string;
};

export type Store = { votes: Record<string, Vote[]> };

function crowdDir() {
  return path.join(repoRoot(), "docs/ohush/research/CROWD_001");
}

function storePath() {
  return path.join(crowdDir(), "votes.json");
}

export function readQueue(): Clip[] {
  return queueFile as Clip[];
}

function visibleClip(clip: Clip | null) {
  if (!clip) return null;
  const { object: _object, ...rest } = clip;
  return rest;
}

function readStore(): Store {
  if (!fs.existsSync(storePath())) return { votes: {} };
  const parsed = JSON.parse(fs.readFileSync(storePath(), "utf8")) as Store;
  return parsed?.votes ? parsed : { votes: {} };
}

function writeStore(store: Store) {
  fs.mkdirSync(crowdDir(), { recursive: true });
  fs.writeFileSync(storePath(), JSON.stringify(store, null, 2) + "\n", "utf8");
}

export function clipStatus(votes: Vote[]): "waiting" | "matched" | "split" {
  const on = votes.filter((vote) => vote.action === "on").length;
  const off = votes.filter((vote) => vote.action === "off").length;
  if (on > 0 && off > 0) return "split";
  if (on >= 2 || off >= 2) return "matched";
  return "waiting";
}

export function mcuCount(store: Store, who: string): number {
  let total = 0;
  for (const votes of Object.values(store.votes)) {
    if (clipStatus(votes) !== "matched") continue;
    if (votes.some((vote) => vote.who === who)) total += 1;
  }
  return total;
}

export function crowdState(who: string) {
  const store = readStore();
  const queue = readQueue();
  const clip = queue.find((item) => !(store.votes[item.id] || []).some((vote) => vote.who === who)) || null;
  const done = queue.filter((item) => (store.votes[item.id] || []).some((vote) => vote.who === who)).length;
  return { name: who, mcus: mcuCount(store, who), done, total: queue.length, clip: visibleClip(clip) };
}

export function castVote(who: string, id: string, action: Action, note: string) {
  const queue = readQueue();
  if (!queue.some((item) => item.id === id)) return { error: "unknown clip" as const };
  const store = readStore();
  const votes = store.votes[id] || [];
  if (votes.some((vote) => vote.who === who)) return { error: "already labeled" as const };
  const next = votes.concat({
    who,
    action,
    note: note.trim().slice(0, 200),
    at: new Date().toISOString(),
  });
  store.votes[id] = next;
  writeStore(store);
  return { status: clipStatus(next), mcus: mcuCount(store, who) };
}
