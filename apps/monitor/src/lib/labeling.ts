import fs from "fs";
import path from "path";

export function repoRoot() {
  // apps/monitor → repo root
  return path.resolve(process.cwd(), "../..");
}

export type Candidate = {
  elapsed_seconds: number;
  score: number;
  rms_dbfs: number;
  loudness_jump_db: number;
  flux_z: number;
  near_silence: boolean;
  session: string;
  file: string;
  chunk_elapsed_seconds: number;
};

export function candidatesPath(session: string) {
  return path.join(
    repoRoot(),
    "experiments/candidates",
    `${session}_candidates.jsonl`,
  );
}

export function sessionDir(session: string) {
  const recordings = path.join(repoRoot(), "recordings");
  const days = fs.readdirSync(recordings);
  for (const day of days) {
    const p = path.join(recordings, day, session);
    if (fs.existsSync(p)) return p;
  }
  throw new Error(`session not found: ${session}`);
}

export function sessionWavPath(session: string, file: string) {
  const p = path.join(sessionDir(session), file);
  if (!fs.existsSync(p)) throw new Error(`WAV not found for ${session}/${file}`);
  return p;
}

export function readSessionMeta(session: string) {
  const p = path.join(sessionDir(session), "session.json");
  const raw = JSON.parse(fs.readFileSync(p, "utf8")) as {
    session: string;
    started_at: string;
    ended_at?: string;
    audio_seconds?: number;
    chunk_minutes?: number;
    chunks?: Array<{
      file: string;
      seconds: number;
      start_elapsed_seconds?: number;
      end_elapsed_seconds?: number;
      started_at?: string;
      ended_at?: string;
    }>;
  };
  return raw;
}

/** Build chunk timeline with elapsed offsets. */
export function sessionChunks(session: string) {
  const meta = readSessionMeta(session);
  const dir = sessionDir(session);
  let chunks = meta.chunks ?? [];
  if (!chunks.length) {
    const files = fs.readdirSync(dir).filter((f) => /^audio_\d+\.wav$/.test(f)).sort();
    const mins = meta.chunk_minutes ?? 15;
    chunks = files.map((file, i) => ({
      file,
      seconds: mins * 60,
      start_elapsed_seconds: i * mins * 60,
    }));
  }
  let running = 0;
  return chunks.map((c) => {
    const start =
      c.start_elapsed_seconds !== undefined ? c.start_elapsed_seconds : running;
    const seconds = c.seconds;
    running = start + seconds;
    return { ...c, start_elapsed_seconds: start, seconds };
  });
}

type RangeCacheEntry = { buf: Buffer; at: number };
const RANGE_CACHE = new Map<string, RangeCacheEntry>();
const RANGE_CACHE_MAX = 12;

function rangeCacheKey(session: string, startSec: number, durationSec: number) {
  // Quantize so tiny float differences still hit.
  return `${session}|${startSec.toFixed(1)}|${durationSec.toFixed(1)}`;
}

/** Extract mono WAV spanning one or more session chunks (session timeline). */
export function extractSessionRange(
  session: string,
  startSec: number,
  durationSec: number,
): Buffer {
  const key = rangeCacheKey(session, startSec, durationSec);
  const hit = RANGE_CACHE.get(key);
  if (hit) {
    hit.at = Date.now();
    return hit.buf;
  }

  const chunks = sessionChunks(session);
  const endSec = startSec + durationSec;
  const parts: Buffer[] = [];
  let rate = 48000;

  for (const c of chunks) {
    const c0 = c.start_elapsed_seconds!;
    const c1 = c0 + c.seconds;
    const a = Math.max(startSec, c0);
    const b = Math.min(endSec, c1);
    if (b <= a) continue;
    const wavPath = sessionWavPath(session, c.file);
    const slice = extractWavSlice(wavPath, a - c0, b - a);
    // strip header after first
    if (parts.length === 0) {
      rate = slice.readUInt32LE(24);
      parts.push(slice);
    } else {
      parts.push(slice.subarray(44));
    }
  }

  let out: Buffer;
  if (!parts.length) {
    // empty wav
    out = Buffer.alloc(44);
    out.write("RIFF", 0);
    out.writeUInt32LE(36, 4);
    out.write("WAVE", 8);
    out.write("fmt ", 12);
    out.writeUInt32LE(16, 16);
    out.writeUInt16LE(1, 20);
    out.writeUInt16LE(1, 22);
    out.writeUInt32LE(rate, 24);
    out.writeUInt32LE(rate * 2, 28);
    out.writeUInt16LE(2, 32);
    out.writeUInt16LE(16, 34);
    out.write("data", 36);
    out.writeUInt32LE(0, 40);
  } else if (parts.length === 1) {
    out = parts[0];
  } else {
    const dataSize = parts.reduce(
      (sum, p, i) => sum + (i === 0 ? p.length - 44 : p.length),
      0,
    );
    out = Buffer.alloc(44 + dataSize);
    parts[0].copy(out, 0, 0, 44);
    out.writeUInt32LE(36 + dataSize, 4);
    out.writeUInt32LE(dataSize, 40);
    let offset = 44;
    for (let i = 0; i < parts.length; i++) {
      const payload = i === 0 ? parts[i].subarray(44) : parts[i];
      payload.copy(out, offset);
      offset += payload.length;
    }
  }

  RANGE_CACHE.set(key, { buf: out, at: Date.now() });
  while (RANGE_CACHE.size > RANGE_CACHE_MAX) {
    let oldestKey: string | null = null;
    let oldestAt = Infinity;
    for (const [k, v] of RANGE_CACHE) {
      if (v.at < oldestAt) {
        oldestAt = v.at;
        oldestKey = k;
      }
    }
    if (oldestKey) RANGE_CACHE.delete(oldestKey);
    else break;
  }
  return out;
}

export function rangeCacheStats() {
  return { size: RANGE_CACHE.size, max: RANGE_CACHE_MAX };
}

/** Same as extractSessionRange, with cache hit metadata for logging. */
export function extractSessionRangeCached(
  session: string,
  startSec: number,
  durationSec: number,
): { buf: Buffer; cacheHit: boolean; key: string } {
  const key = rangeCacheKey(session, startSec, durationSec);
  const cacheHit = RANGE_CACHE.has(key);
  const buf = extractSessionRange(session, startSec, durationSec);
  return { buf, cacheHit, key };
}

/** Multi-lane waveform views for the blind labeler (eyeball commercial hits). */
export type WaveLanes = {
  /** Max |sample| per bucket (classic envelope). */
  peak: number[];
  /** RMS energy per bucket. */
  rms: number[];
  /** |ΔRMS| — loudness jumps / cuts. */
  jump: number[];
  /** Mean |Δsample| — brightness / edge energy. */
  bright: number[];
  /** Max sample in [-1, 1] (bipolar wave top). */
  hi: number[];
  /** Min sample in [-1, 1] (bipolar wave bottom). */
  lo: number[];
  sample_rate: number;
};

type WaveCacheEntry = { lanes: WaveLanes; at: number };
const WAVE_CACHE = new Map<string, WaveCacheEntry>();
const WAVE_CACHE_MAX = 24;

function waveCacheKey(
  session: string,
  startSec: number,
  durationSec: number,
  buckets: number,
) {
  return `${session}|${startSec.toFixed(1)}|${durationSec.toFixed(1)}|${buckets}`;
}

function waveCacheGet(key: string): WaveLanes | null {
  const hit = WAVE_CACHE.get(key);
  if (!hit) return null;
  hit.at = Date.now();
  return hit.lanes;
}

function waveCacheSet(key: string, lanes: WaveLanes) {
  WAVE_CACHE.set(key, { lanes, at: Date.now() });
  while (WAVE_CACHE.size > WAVE_CACHE_MAX) {
    let oldestKey: string | null = null;
    let oldestAt = Infinity;
    for (const [k, v] of WAVE_CACHE) {
      if (v.at < oldestAt) {
        oldestAt = v.at;
        oldestKey = k;
      }
    }
    if (oldestKey) WAVE_CACHE.delete(oldestKey);
  }
}

function emptyLanes(buckets: number, sample_rate = 48000): WaveLanes {
  const z = () => new Array(buckets).fill(0);
  return {
    peak: z(),
    rms: z(),
    jump: z(),
    bright: z(),
    hi: z(),
    lo: z(),
    sample_rate,
  };
}

function normalize01(values: number[]) {
  let max = 0;
  for (const v of values) max = Math.max(max, v);
  if (max <= 1e-9) return values.map(() => 0);
  return values.map((v) => Math.min(1, v / max));
}

function finalizeLanes(lanes: WaveLanes): WaveLanes {
  const jumpRaw = lanes.rms.map((v, i) => (i === 0 ? 0 : Math.abs(v - lanes.rms[i - 1])));
  // Keep bipolar hi/lo in sample units; scale only if clipped beyond ±1.
  let amp = 1;
  for (let i = 0; i < lanes.hi.length; i++) {
    amp = Math.max(amp, Math.abs(lanes.hi[i]), Math.abs(lanes.lo[i]));
  }
  const hi = lanes.hi.map((v) => v / amp);
  const lo = lanes.lo.map((v) => v / amp);
  return {
    peak: normalize01(lanes.peak),
    rms: normalize01(lanes.rms),
    jump: normalize01(jumpRaw),
    bright: normalize01(lanes.bright),
    hi,
    lo,
    sample_rate: lanes.sample_rate,
  };
}

/**
 * Raw (unnormalized) lanes — used for session stitching.
 * Strided sampling: never scan every PCM frame (10min@48k was 30s+ of JS).
 */
function extractWaveLanesRaw(
  wavPath: string,
  startSec: number,
  durationSec: number,
  buckets = 240,
): WaveLanes {
  const fd = fs.openSync(wavPath, "r");
  try {
    const header = Buffer.alloc(44);
    fs.readSync(fd, header, 0, 44, 0);
    const channels = header.readUInt16LE(22);
    const rate = header.readUInt32LE(24);
    const bits = header.readUInt16LE(34);
    if (bits !== 16) throw new Error(`unsupported bits: ${bits}`);

    let dataOffset = 44;
    let pos = 12;
    const stat = fs.fstatSync(fd);
    const probe = Buffer.alloc(Math.min(stat.size, 2048));
    fs.readSync(fd, probe, 0, probe.length, 0);
    while (pos + 8 <= probe.length) {
      const id = probe.toString("ascii", pos, pos + 4);
      const size = probe.readUInt32LE(pos + 4);
      if (id === "data") {
        dataOffset = pos + 8;
        break;
      }
      pos += 8 + size + (size % 2);
    }

    const bytesPerFrame = channels * 2;
    const startFrame = Math.max(0, Math.floor(startSec * rate));
    const nFrames = Math.max(1, Math.floor(durationSec * rate));
    const availableFrames = Math.max(
      0,
      Math.floor(Math.max(0, stat.size - dataOffset - startFrame * bytesPerFrame) / bytesPerFrame),
    );
    const frames = Math.min(nFrames, availableFrames);
    const lanes = emptyLanes(buckets, rate);
    for (let b = 0; b < buckets; b++) {
      lanes.hi[b] = -1;
      lanes.lo[b] = 1;
    }
    if (frames === 0) {
      return emptyLanes(buckets, rate);
    }

    // ~48 probes/bucket is plenty for envelopes; hard-cap total work.
    const targetProbes = Math.min(frames, Math.max(buckets * 48, buckets));
    const stride = Math.max(1, Math.floor(frames / targetProbes));
    // Read in ~256KB blocks and sample with stride — no giant Buffer.alloc.
    const blockFrames = Math.max(stride * 64, 4096);
    const blockBytes = blockFrames * bytesPerFrame;
    const block = Buffer.alloc(blockBytes);
    const sumSq = new Array(buckets).fill(0);
    const count = new Array(buckets).fill(0);
    const brightAcc = new Array(buckets).fill(0);
    let prev = 0;

    for (let base = 0; base < frames; base += blockFrames) {
      const framesHere = Math.min(blockFrames, frames - base);
      const byteOff = dataOffset + (startFrame + base) * bytesPerFrame;
      const bytesHere = framesHere * bytesPerFrame;
      const got = fs.readSync(fd, block, 0, bytesHere, byteOff);
      const gotFrames = Math.floor(got / bytesPerFrame);
      const localStride = stride;
      for (let i = 0; i < gotFrames; i += localStride) {
        let sample = 0;
        if (channels === 1) {
          sample = block.readInt16LE(i * 2) / 32768;
        } else {
          const l = block.readInt16LE(i * bytesPerFrame) / 32768;
          const r = block.readInt16LE(i * bytesPerFrame + 2) / 32768;
          sample = (l + r) / 2;
        }
        const absFrame = base + i;
        const bucket = Math.min(buckets - 1, Math.floor((absFrame / frames) * buckets));
        const abs = sample < 0 ? -sample : sample;
        if (abs > lanes.peak[bucket]) lanes.peak[bucket] = abs;
        if (sample > lanes.hi[bucket]) lanes.hi[bucket] = sample;
        if (sample < lanes.lo[bucket]) lanes.lo[bucket] = sample;
        sumSq[bucket] += sample * sample;
        count[bucket] += 1;
        const d = sample - prev;
        brightAcc[bucket] += d < 0 ? -d : d;
        prev = sample;
      }
    }
    for (let b = 0; b < buckets; b++) {
      if (count[b] === 0) {
        lanes.hi[b] = 0;
        lanes.lo[b] = 0;
        continue;
      }
      lanes.rms[b] = Math.sqrt(sumSq[b] / count[b]);
      lanes.bright[b] = brightAcc[b] / count[b];
    }
    return lanes;
  } finally {
    fs.closeSync(fd);
  }
}

/**
 * Wave lanes over a session-absolute range.
 * Reads each overlapping chunk sparsely — does NOT concatenate a full multi‑minute WAV.
 */
export function extractSessionWaveLanes(
  session: string,
  startSec: number,
  durationSec: number,
  buckets = 320,
): WaveLanes {
  const key = waveCacheKey(session, startSec, durationSec, buckets);
  const cached = waveCacheGet(key);
  if (cached) return cached;

  const chunks = sessionChunks(session);
  const endSec = startSec + durationSec;
  const lanes = emptyLanes(buckets);
  for (let b = 0; b < buckets; b++) {
    lanes.hi[b] = -1;
    lanes.lo[b] = 1;
  }
  const rmsSum = new Array(buckets).fill(0);
  const rmsWeight = new Array(buckets).fill(0);
  const brightSum = new Array(buckets).fill(0);
  const brightWeight = new Array(buckets).fill(0);
  let touched = false;

  for (const c of chunks) {
    const c0 = c.start_elapsed_seconds!;
    const c1 = c0 + c.seconds;
    const a = Math.max(startSec, c0);
    const b = Math.min(endSec, c1);
    if (b <= a) continue;
    const frac = (b - a) / Math.max(durationSec, 1e-6);
    const localBuckets = Math.max(8, Math.ceil(buckets * frac));
    const wavPath = sessionWavPath(session, c.file);
    const local = extractWaveLanesRaw(wavPath, a - c0, b - a, localBuckets);
    lanes.sample_rate = local.sample_rate;
    touched = true;
    const g0 = Math.floor(((a - startSec) / Math.max(durationSec, 1e-6)) * buckets);
    const span = Math.max(1, Math.ceil(frac * buckets));
    for (let i = 0; i < local.peak.length; i++) {
      const g = Math.min(buckets - 1, g0 + Math.floor((i / local.peak.length) * span));
      lanes.peak[g] = Math.max(lanes.peak[g], local.peak[i]);
      lanes.hi[g] = Math.max(lanes.hi[g], local.hi[i]);
      lanes.lo[g] = Math.min(lanes.lo[g], local.lo[i]);
      rmsSum[g] += local.rms[i];
      rmsWeight[g] += 1;
      brightSum[g] += local.bright[i];
      brightWeight[g] += 1;
    }
  }
  if (!touched) {
    const empty = emptyLanes(buckets);
    waveCacheSet(key, empty);
    return empty;
  }
  for (let g = 0; g < buckets; g++) {
    if (rmsWeight[g] === 0) {
      lanes.hi[g] = 0;
      lanes.lo[g] = 0;
      continue;
    }
    lanes.rms[g] = rmsSum[g] / rmsWeight[g];
    lanes.bright[g] = brightSum[g] / brightWeight[g];
  }
  const out = finalizeLanes(lanes);
  waveCacheSet(key, out);
  return out;
}

export function extractSessionPeaks(
  session: string,
  startSec: number,
  durationSec: number,
  buckets = 320,
): { peaks: number[]; sample_rate: number } {
  const lanes = extractSessionWaveLanes(session, startSec, durationSec, buckets);
  return { peaks: lanes.peak, sample_rate: lanes.sample_rate };
}

/** Peak envelope for display. Detection suggestions come from a Python run, not from this file. */
export function extractPeaks(
  wavPath: string,
  startSec: number,
  durationSec: number,
  buckets = 240,
): { peaks: number[]; sample_rate: number } {
  const lanes = extractWaveLanes(wavPath, startSec, durationSec, buckets);
  return { peaks: lanes.peak, sample_rate: lanes.sample_rate };
}

/** Multi-metric envelope for eyeballing commercial hits. */
export function extractWaveLanes(
  wavPath: string,
  startSec: number,
  durationSec: number,
  buckets = 240,
): WaveLanes {
  return finalizeLanes(extractWaveLanesRaw(wavPath, startSec, durationSec, buckets));
}

export function labelsPath() {
  return path.join(repoRoot(), "experiments/features/labels.jsonl");
}

export function runsDir() {
  return path.join(repoRoot(), "experiments/runs");
}

export function annotationsDir() {
  return path.join(repoRoot(), "experiments/annotations");
}

export function reviewsPath() {
  return path.join(annotationsDir(), "candidate_reviews.jsonl");
}

export function truthPath() {
  return path.join(annotationsDir(), "truth_events.jsonl");
}

export function goldManifestPath(name = "GOLD_DEV_V1") {
  return path.join(repoRoot(), "experiments/gold", `${name}.json`);
}

export type RunSummary = {
  run_id: string;
  detector_id: string | null;
  params_hash: string | null;
  completed_at: string | null;
  keeps: number | null;
};

export function listRuns(): RunSummary[] {
  const dir = runsDir();
  if (!fs.existsSync(dir)) return [];
  const names = fs
    .readdirSync(dir)
    .filter((name) => {
      if (name.startsWith(".")) return false;
      return fs.existsSync(path.join(dir, name, "manifest.json"));
    })
    .sort()
    .reverse();
  return names.map((run_id) => {
    const manifest = JSON.parse(
      fs.readFileSync(path.join(dir, run_id, "manifest.json"), "utf8"),
    ) as { detector_id?: string; params_hash?: string; completed_at?: string };
    const auditPath = path.join(dir, run_id, "audit.json");
    let keeps: number | null = null;
    if (fs.existsSync(auditPath)) {
      const audit = JSON.parse(fs.readFileSync(auditPath, "utf8")) as { keeps?: number };
      keeps = audit.keeps ?? null;
    }
    return {
      run_id,
      detector_id: manifest.detector_id ?? null,
      params_hash: manifest.params_hash ?? null,
      completed_at: manifest.completed_at ?? null,
      keeps,
    };
  });
}

export function runCandidatesPath(runId: string) {
  return path.join(runsDir(), runId, "candidates.jsonl");
}

export function readRunCandidates(runId: string): Array<Record<string, unknown>> {
  const p = runCandidatesPath(runId);
  if (!fs.existsSync(p)) return [];
  return fs
    .readFileSync(p, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

export function readJsonl(p: string): Array<Record<string, unknown>> {
  if (!fs.existsSync(p)) return [];
  return fs
    .readFileSync(p, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

export function listSessions() {
  const recordings = path.join(repoRoot(), "recordings");
  if (!fs.existsSync(recordings)) return [];
  const out: Array<{
    session: string;
    audio_seconds: number | null;
    started_at: string | null;
    sample_rate_hz: number;
  }> = [];
  for (const day of fs.readdirSync(recordings)) {
    const dayPath = path.join(recordings, day);
    if (!fs.statSync(dayPath).isDirectory()) continue;
    for (const session of fs.readdirSync(dayPath)) {
      const metaPath = path.join(dayPath, session, "session.json");
      if (!fs.existsSync(metaPath)) continue;
      const raw = JSON.parse(fs.readFileSync(metaPath, "utf8")) as {
        audio_seconds?: number;
        started_at?: string;
        sample_rate_hz?: number;
      };
      out.push({
        session,
        audio_seconds: raw.audio_seconds ?? null,
        started_at: raw.started_at ?? null,
        sample_rate_hz: raw.sample_rate_hz ?? 48000,
      });
    }
  }
  return out.sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? ""));
}

export function readCandidates(session: string): Candidate[] {
  const p = candidatesPath(session);
  if (!fs.existsSync(p)) return [];
  return fs
    .readFileSync(p, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Candidate)
    .sort((a, b) => b.score - a.score);
}

export function readLabels(): Array<Record<string, unknown>> {
  const p = labelsPath();
  if (!fs.existsSync(p)) return [];
  return fs
    .readFileSync(p, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

/** Extract a mono 16-bit PCM slice from a stereo/mono WAV into a Buffer WAV. */
export function extractWavSlice(
  wavPath: string,
  startSec: number,
  durationSec: number,
): Buffer {
  const fd = fs.openSync(wavPath, "r");
  try {
    const header = Buffer.alloc(44);
    fs.readSync(fd, header, 0, 44, 0);
    if (header.toString("ascii", 0, 4) !== "RIFF") {
      throw new Error("not a RIFF wav");
    }
    const channels = header.readUInt16LE(22);
    const rate = header.readUInt32LE(24);
    const bits = header.readUInt16LE(34);
    if (bits !== 16) throw new Error(`unsupported bits: ${bits}`);

    // Find data chunk (usually at 36)
    let dataOffset = 44;
    let pos = 12;
    const stat = fs.fstatSync(fd);
    const probe = Buffer.alloc(Math.min(stat.size, 12 + 1024));
    fs.readSync(fd, probe, 0, probe.length, 0);
    while (pos + 8 <= probe.length) {
      const id = probe.toString("ascii", pos, pos + 4);
      const size = probe.readUInt32LE(pos + 4);
      if (id === "data") {
        dataOffset = pos + 8;
        break;
      }
      pos += 8 + size + (size % 2);
    }

    const bytesPerFrame = channels * 2;
    const startFrame = Math.max(0, Math.floor(startSec * rate));
    const nFrames = Math.max(1, Math.floor(durationSec * rate));
    const startByte = dataOffset + startFrame * bytesPerFrame;
    const wantBytes = nFrames * bytesPerFrame;
    const available = Math.max(0, stat.size - startByte);
    const readBytes = Math.min(wantBytes, available - (available % bytesPerFrame));

    const pcm = Buffer.alloc(readBytes);
    if (readBytes > 0) {
      fs.readSync(fd, pcm, 0, readBytes, startByte);
    }

    // Downmix to mono
    const frames = readBytes / bytesPerFrame;
    const mono = Buffer.alloc(frames * 2);
    for (let i = 0; i < frames; i++) {
      if (channels === 1) {
        mono.writeInt16LE(pcm.readInt16LE(i * 2), i * 2);
      } else {
        const l = pcm.readInt16LE(i * bytesPerFrame);
        const r = pcm.readInt16LE(i * bytesPerFrame + 2);
        mono.writeInt16LE(((l + r) / 2) | 0, i * 2);
      }
    }

    const dataSize = mono.length;
    const out = Buffer.alloc(44 + dataSize);
    out.write("RIFF", 0);
    out.writeUInt32LE(36 + dataSize, 4);
    out.write("WAVE", 8);
    out.write("fmt ", 12);
    out.writeUInt32LE(16, 16);
    out.writeUInt16LE(1, 20); // PCM
    out.writeUInt16LE(1, 22); // mono
    out.writeUInt32LE(rate, 24);
    out.writeUInt32LE(rate * 2, 28);
    out.writeUInt16LE(2, 32);
    out.writeUInt16LE(16, 34);
    out.write("data", 36);
    out.writeUInt32LE(dataSize, 40);
    mono.copy(out, 44);
    return out;
  } finally {
    fs.closeSync(fd);
  }
}
