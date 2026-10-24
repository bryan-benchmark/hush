import { randomBytes } from "crypto";
import { GoogleAuth } from "google-auth-library";
import { adminAuth, adminDb } from "@/lib/firebaseAdmin";
import { clipStatus, mcuCount, readQueue, type Action, type Store, type Vote } from "@/lib/crowd";

export const SESSION_COOKIE = "ohush_id";
const SESSION_MS = 14 * 24 * 60 * 60 * 1000;
const BUCKET = process.env.CROWD_BUCKET || "hushdev-748439071367-crowd";

const clipCache = new Map<string, Buffer>();
let auth: GoogleAuth | null = null;

function visible(clip: ReturnType<typeof readQueue>[number] | null) {
  if (!clip) return null;
  const { object: _object, ...rest } = clip;
  return rest;
}

function storeFromDocs(docs: { id: string; data: () => { votes?: Vote[] } }[]): Store {
  const votes: Record<string, Vote[]> = {};
  for (const doc of docs) votes[doc.id] = (doc.data().votes || []).filter((vote) => vote?.who && vote?.action);
  return { votes };
}

export async function openSession(idToken: string) {
  const decoded = await adminAuth().verifyIdToken(idToken);
  const token = randomBytes(32).toString("hex");
  const name = String(decoded.name || decoded.email || "Listener").replace(/\s+/g, " ").trim().slice(0, 80) || "Listener";
  const exp = Date.now() + SESSION_MS;
  await adminDb().collection("crowd_sessions").doc(token).set({ uid: decoded.uid, name, exp });
  return { token, name, maxAge: Math.floor(SESSION_MS / 1000) };
}

export async function readSession(token: string): Promise<{ uid: string; name: string } | null> {
  if (!/^[a-f0-9]{64}$/.test(token)) return null;
  const snap = await adminDb().collection("crowd_sessions").doc(token).get();
  if (!snap.exists) return null;
  const data = snap.data() as { uid?: string; name?: string; exp?: number };
  if (!data.uid || !data.exp || data.exp < Date.now()) return null;
  return { uid: data.uid, name: data.name || "Listener" };
}

export async function closeSession(token: string) {
  if (!/^[a-f0-9]{64}$/.test(token)) return;
  await adminDb().collection("crowd_sessions").doc(token).delete();
}

async function allVotes(): Promise<Store> {
  const snap = await adminDb().collection("crowd_clips").get();
  return storeFromDocs(snap.docs);
}

export async function cloudState(uid: string, name: string) {
  const store = await allVotes();
  const queue = readQueue();
  const clip = queue.find((item) => !(store.votes[item.id] || []).some((vote) => vote.who === uid)) || null;
  const done = queue.filter((item) => (store.votes[item.id] || []).some((vote) => vote.who === uid)).length;
  return { name, mcus: mcuCount(store, uid), done, total: queue.length, clip: visible(clip) };
}

export async function cloudVote(uid: string, name: string, id: string, action: Action, note: string) {
  const queue = readQueue();
  if (!queue.some((item) => item.id === id)) return { error: "unknown clip" as const };
  const ref = adminDb().collection("crowd_clips").doc(id);
  let status: "waiting" | "matched" | "split";
  try {
    status = await adminDb().runTransaction(async (tx) => {
      const snap = await tx.get(ref);
      const votes = ((snap.exists ? (snap.data()?.votes as Vote[]) : []) || []).slice();
      if (votes.some((vote) => vote.who === uid)) throw new Error("already labeled");
      const next = votes.concat({
        who: uid,
        name,
        action,
        note: note.trim().slice(0, 200),
        at: new Date().toISOString(),
      });
      tx.set(ref, { votes: next });
      return clipStatus(next);
    });
  } catch (err) {
    if (err instanceof Error && err.message === "already labeled") return { error: "already labeled" as const };
    throw err;
  }
  const state = await cloudState(uid, name);
  return { status, mcus: state.mcus };
}

export async function clipAudio(id: string): Promise<Buffer | null> {
  const clip = readQueue().find((item) => item.id === id);
  if (!clip?.object || clip.object.includes("..") || !clip.object.startsWith("clips/")) return null;
  const hit = clipCache.get(clip.object);
  if (hit) return hit;
  if (!auth) auth = new GoogleAuth({ scopes: ["https://www.googleapis.com/auth/devstorage.read_only"] });
  const client = await auth.getClient();
  const token = await client.getAccessToken();
  if (!token.token) throw new Error("clip auth");
  const url = `https://storage.googleapis.com/storage/v1/b/${encodeURIComponent(BUCKET)}/o/${encodeURIComponent(clip.object)}?alt=media`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token.token}` } });
  if (!res.ok) throw new Error(`clip ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  clipCache.set(clip.object, buf);
  return buf;
}
