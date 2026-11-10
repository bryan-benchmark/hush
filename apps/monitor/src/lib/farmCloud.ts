import { GoogleAuth } from "google-auth-library";
import { adminDb } from "@/lib/firebaseAdmin";

const BUCKET = process.env.FARM_BUCKET || process.env.CROWD_BUCKET || "hushdev-748439071367-crowd";
const QUEUE_OBJECT = "farm/queue.json";

export type FarmCloudFrame = { t_s: number; object: string };
export type FarmCloudClip = {
  id: string;
  channel: string;
  duration_s: number;
  caption?: string;
  why?: string | null;
  ask?: string | null;
  help?: boolean;
  priority?: number;
  source?: string;
  expect_bucket?: string | null;
  audio_object: string;
  frames: FarmCloudFrame[];
  whole_clip?: boolean;
};

type Judgment = {
  id: string;
  regions: Array<{ start_s: number; end_s: number; bucket: string; kind: string; note: string }>;
  saved_at: string;
};

let auth: GoogleAuth | null = null;
const objectCache = new Map<string, Buffer>();
let queueCache: { at: number; clips: FarmCloudClip[] } | null = null;

async function gcsGet(object: string): Promise<Buffer | null> {
  if (!object || object.includes("..") || !object.startsWith("farm/")) return null;
  const hit = objectCache.get(object);
  if (hit) return hit;
  if (!auth) auth = new GoogleAuth({ scopes: ["https://www.googleapis.com/auth/devstorage.read_only"] });
  const client = await auth.getClient();
  const token = await client.getAccessToken();
  if (!token.token) throw new Error("farm gcs auth");
  const url = `https://storage.googleapis.com/storage/v1/b/${encodeURIComponent(BUCKET)}/o/${encodeURIComponent(object)}?alt=media`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token.token}` } });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`farm gcs ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length < 2_000_000) objectCache.set(object, buf);
  return buf;
}

export async function readFarmCloudQueue(): Promise<FarmCloudClip[]> {
  if (queueCache && Date.now() - queueCache.at < 15_000) return queueCache.clips;
  const buf = await gcsGet(QUEUE_OBJECT);
  if (!buf) {
    queueCache = { at: Date.now(), clips: [] };
    return [];
  }
  const parsed = JSON.parse(buf.toString("utf8")) as { items?: FarmCloudClip[] } | FarmCloudClip[];
  const clips = Array.isArray(parsed) ? parsed : parsed.items || [];
  queueCache = { at: Date.now(), clips };
  return clips;
}

export function invalidateFarmQueueCache() {
  queueCache = null;
}

export async function farmCloudAudio(id: string): Promise<Buffer | null> {
  const clip = (await readFarmCloudQueue()).find((row) => row.id === id);
  if (!clip?.audio_object) return null;
  return gcsGet(clip.audio_object);
}

export async function farmCloudFrame(id: string, objectOrIndex: string): Promise<Buffer | null> {
  const clip = (await readFarmCloudQueue()).find((row) => row.id === id);
  if (!clip) return null;
  let object = objectOrIndex;
  if (/^\d+$/.test(objectOrIndex)) {
    const frame = clip.frames[Number(objectOrIndex)];
    object = frame?.object || "";
  } else if (!object.startsWith("farm/")) {
    const frame = clip.frames.find((row) => row.object.endsWith(objectOrIndex) || row.object === objectOrIndex);
    object = frame?.object || "";
  }
  if (!object.startsWith("farm/clips/")) return null;
  return gcsGet(object);
}

export async function readFarmCloudJudgments(): Promise<Record<string, Judgment>> {
  const snap = await adminDb().collection("farm_judgments").get();
  const out: Record<string, Judgment> = {};
  for (const doc of snap.docs) {
    const data = doc.data() as Judgment;
    if (data?.id && Array.isArray(data.regions)) out[doc.id] = data;
  }
  return out;
}

export async function writeFarmCloudJudgment(row: Judgment) {
  await adminDb().collection("farm_judgments").doc(row.id).set(row, { merge: true });
  invalidateFarmQueueCache();
}

export function visibleFarmClip(clip: FarmCloudClip) {
  return {
    id: clip.id,
    session: clip.id,
    session_dir: "",
    audio_rel: "",
    audio_start_s: 0,
    duration_s: clip.duration_s,
    channel: clip.channel,
    group: "",
    program: "",
    date: "",
    time: "",
    dow: "",
    daypart: "",
    recorded_utc: "",
    caption: clip.caption || "",
    why: clip.why || null,
    ask: clip.ask || null,
    help: Boolean(clip.help || clip.ask === "needs_human" || clip.ask === "review"),
    expect_bucket: clip.expect_bucket || null,
    source: clip.source || "cloud",
    whole_clip: clip.whole_clip !== false,
    priority: clip.priority ?? 99,
    cloud: true,
    frames: (clip.frames || []).map((frame, i) => ({
      file: frame.object,
      t_s: frame.t_s,
      index: i,
    })),
  };
}
