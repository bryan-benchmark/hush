import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { farmCloudMode } from "@/lib/farmAccess";
import {
  readFarmCloudJudgments,
  readFarmCloudQueue,
  visibleFarmClip,
  writeFarmCloudJudgment,
} from "@/lib/farmCloud";
import { lockHumanClip, skipBadClip } from "@/lib/farmLabelLock";

export const runtime = "nodejs";

function dataRoot() {
  return process.env.OHUSH_DATA_ROOT || "C:\\OHushData";
}

function streamersRoot() {
  return path.join(dataRoot(), "work", "capture", "streamers");
}

function farmLabelDir() {
  return path.join(dataRoot(), "indexes", "farm_labels");
}

function judgmentsPath() {
  return path.join(farmLabelDir(), "take_judgments.json");
}

function queuePath() {
  return path.join(farmLabelDir(), "queue.jsonl");
}

type Region = {
  start_s: number;
  end_s: number;
  bucket: string;
  kind: string;
  note: string;
};

type TakeJudgment = {
  id: string;
  regions: Region[];
  saved_at: string;
  /** Still and audio don't line up — usually extreme stream lag. */
  av_mismatch?: boolean;
  discarded?: boolean;
  discard_reason?: string;
  note?: string;
};

function readJudgments(): Record<string, TakeJudgment> {
  const file = judgmentsPath();
  if (!fs.existsSync(file)) return {};
  return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, TakeJudgment>;
}

function writeJudgments(notes: Record<string, TakeJudgment>) {
  const dir = path.dirname(judgmentsPath());
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(judgmentsPath(), JSON.stringify(notes, null, 2) + "\n", "utf8");
}

function etParts(iso: string | undefined) {
  const d = iso ? new Date(iso) : new Date();
  if (Number.isNaN(d.getTime())) {
    return { date: "", time: "", dow: "", daypart: "" };
  }
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "long",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  const parts = Object.fromEntries(fmt.formatToParts(d).map((p) => [p.type, p.value]));
  const hourFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    hour12: false,
  });
  const hour = Number(hourFmt.format(d));
  let daypart = "late";
  if (hour >= 5 && hour < 12) daypart = "morning";
  else if (hour >= 12 && hour < 17) daypart = "afternoon";
  else if (hour >= 17 && hour < 23) daypart = "primetime";
  return {
    date: `${parts.month} ${parts.day}, ${parts.year}`,
    time: `${parts.hour}:${parts.minute} ${parts.dayPeriod}`,
    dow: parts.weekday || "",
    daypart,
  };
}

function listFrames(sessionDir: string, t0 = 0, t1?: number) {
  if (!fs.existsSync(sessionDir)) return [];
  const out: Array<{ file: string; t_s: number }> = [];
  const stillsDir = path.join(sessionDir, "stills");
  if (fs.existsSync(stillsDir)) {
    for (const name of fs.readdirSync(stillsDir)) {
      const m = name.match(/^still_t(\d+(?:\.\d+)?)\.jpe?g$/i);
      if (!m) continue;
      out.push({ file: `stills/${name}`, t_s: Number(m[1]) });
    }
  }
  for (const name of fs.readdirSync(sessionDir)) {
    const m = name.match(/^frame_(\d+)s\.jpe?g$/i);
    if (!m) continue;
    out.push({ file: name, t_s: Number(m[1]) });
  }
  out.sort((a, b) => a.t_s - b.t_s);
  const hasStills = out.some((row) => row.file.startsWith("stills/"));
  const frames = hasStills ? out.filter((row) => row.file.startsWith("stills/")) : out;
  const end = t1 == null ? Number.POSITIVE_INFINITY : t1;
  // Remap to clip-local time so the playhead matches windowed audio.
  return frames
    .filter((row) => row.t_s >= t0 - 0.05 && row.t_s <= end + 0.05)
    .map((row) => ({ file: row.file, t_s: Math.max(0, Math.round((row.t_s - t0) * 10) / 10) }));
}

function loadKeyByClip() {
  const file = path.join(farmLabelDir(), "key.jsonl");
  const out: Record<string, Record<string, unknown>> = {};
  if (!fs.existsSync(file)) return out;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/).filter(Boolean)) {
    try {
      const row = JSON.parse(line) as Record<string, unknown>;
      const clip = String(row.clip || "");
      if (clip) out[clip] = row;
    } catch {
      // skip
    }
  }
  return out;
}

function loadQueueClips(opts?: { unlabeledOnly?: boolean; morningOnly?: boolean }) {
  const unlabeledOnly = opts?.unlabeledOnly !== false;
  const morningOnly = opts?.morningOnly !== false;
  const judged = unlabeledOnly
    ? new Set(
        Object.values(readJudgments())
          .filter((row) => (row.regions || []).length > 0 || row.discarded || row.av_mismatch)
          .map((row) => row.id),
      )
    : new Set<string>();
  const keys = loadKeyByClip();
  const file = queuePath();
  if (!fs.existsSync(file)) return { items: [] as Array<Record<string, unknown>>, active: 0, parked: 0 };
  const lines = fs.readFileSync(file, "utf8").split(/\r?\n/).filter(Boolean);
  const items: Array<Record<string, unknown>> = [];
  let active = 0;
  let parked = 0;
  for (const line of lines) {
    try {
      const row = JSON.parse(line) as Record<string, unknown>;
      const sessionDir = String(row.session_dir || "");
      if (!sessionDir || !fs.existsSync(path.join(sessionDir, "audio.wav"))) continue;
      const t0 = Number(row.t0 || 0);
      const t1 = Number(row.t1 || t0 + 12);
      if (!(t1 > t0)) continue;
      const id = String(row.clip || `${row.session}_${t0}_${t1}`);
      if (judged.has(id)) continue;
      // Skip auto-accepted drafts and already-locked gold — not help work.
      const key = keys[id] || {};
      const ask = String(row.ask || key.ask || "");
      if (ask === "optional_confirm" || ask === "skip") continue;
      if (ask === "locked" || key.gold || key.source === "gold" || key.source === "human") continue;
      const source = String(row.source || "queue");
      const reviewBatch = String(row.review_batch || "");
      if (reviewBatch === "active") active += 1;
      if (reviewBatch === "parked") parked += 1;
      // Default /farm: only today's morning batch (+ gold candidates always visible).
      if (
        morningOnly &&
        source !== "gold_candidate" &&
        reviewBatch === "parked"
      ) {
        continue;
      }
      // transcript_boundary chops are weak soup — hide until the model marks them help.
      if (
        source === "transcript_boundary" &&
        ask !== "needs_human" &&
        ask !== "review" &&
        !row.expect_bucket
      ) {
        continue;
      }
      const aidPath = path.join(sessionDir, "label_aid.json");
      const aid = fs.existsSync(aidPath)
        ? (JSON.parse(fs.readFileSync(aidPath, "utf8")) as Record<string, unknown>)
        : {};
      const guide = (aid.guide as Record<string, unknown>) || {};
      const recorded = String(aid.recorded_utc || "");
      const clock = etParts(recorded);
      const channel = String(row.channel || guide.name || row.session || "channel");
      const duration = Math.max(0.5, t1 - t0);
      const why = String(row.why || key.why || key.note || "");
      const caption = String(row.caption || why || "");
      const expect = row.expect_bucket ? String(row.expect_bucket) : "";
      const priority = Number(row.priority || 99);
      items.push({
        id,
        session: String(row.session || path.basename(sessionDir)),
        session_dir: sessionDir,
        audio_rel: String(row.audio_rel || "audio.wav"),
        audio_start_s: t0,
        duration_s: duration,
        recorded_utc: recorded,
        channel,
        group: String(guide.group || ""),
        program: String(guide.program_at_open || guide.program || ""),
        rights_status: String(aid.rights_status || "authorized"),
        ...clock,
        frames: listFrames(sessionDir, t0, t1),
        caption,
        why: why || null,
        ask: ask || null,
        draft_bucket: row.draft_bucket || key.bucket || null,
        draft_confidence: row.draft_confidence || key.confidence || null,
        expect_bucket: expect || null,
        source,
        review_batch: reviewBatch || null,
        whole_clip: true,
        priority,
        help:
          ask === "needs_human" ||
          ask === "review" ||
          source === "gold_candidate",
      });
    } catch {
      // skip bad line
    }
  }
  // Active batch first, then help, gold candidates, rest.
  items.sort((a, b) => {
    const rank = (row: Record<string, unknown>) => {
      if (row.review_batch === "active") return 0;
      if (row.help) return 1;
      if (row.expect_bucket || row.source === "gold_candidate") return 2;
      if (row.source === "still_diff" || row.source === "label_aid") return 3;
      if (row.source === "transcript_boundary") return 9;
      return 5;
    };
    const ra = rank(a);
    const rb = rank(b);
    if (ra !== rb) return ra - rb;
    const pa = Number(a.priority || 99);
    const pb = Number(b.priority || 99);
    if (pa !== pb) return pa - pb;
    const sa = String(a.session || "");
    const sb = String(b.session || "");
    if (sa !== sb) return sa.localeCompare(sb);
    return Number(a.audio_start_s || 0) - Number(b.audio_start_s || 0);
  });
  return { items, active, parked };
}

function loadTake(dir: string) {
  const takePath = path.join(dir, "take.json");
  const aidPath = path.join(dir, "label_aid.json");
  const take = fs.existsSync(takePath) ? (JSON.parse(fs.readFileSync(takePath, "utf8")) as Record<string, unknown>) : {};
  const aid = fs.existsSync(aidPath) ? (JSON.parse(fs.readFileSync(aidPath, "utf8")) as Record<string, unknown>) : {};
  const guide = (aid.guide as Record<string, unknown>) || {};
  const media = (aid.media as Record<string, unknown>) || {};
  const session = String(take.session || aid.session || path.basename(dir));
  const recorded = String(take.recorded_utc || aid.recorded_utc || "");
  const clock = etParts(recorded);
  const duration = Number(take.duration_s || media.duration_s || 180);
  const channel = String(take.channel_name || guide.name || session);
  const group = String(take.group || guide.group || "");
  const program = String(take.guide_title_at_start || guide.program_at_open || guide.program || "");
  return {
    id: session,
    session,
    session_dir: dir,
    audio_rel: fs.existsSync(path.join(dir, "audio.wav")) ? "audio.wav" : "",
    audio_start_s: 0,
    duration_s: duration,
    recorded_utc: recorded,
    channel,
    group,
    program,
    rights_status: String(take.rights_status || aid.rights_status || "authorized"),
    ...clock,
    frames: listFrames(dir),
    caption: `${channel}${program ? ` · ${program}` : ""}`,
    whole_clip: false,
    source: "full_take",
  };
}

export async function GET(req: NextRequest) {
  const all = req.nextUrl.searchParams.get("all") === "1";
  if (farmCloudMode()) {
    const judgments = await readFarmCloudJudgments();
    const saved = Object.values(judgments);
    const judged = new Set(saved.filter((row) => row.regions.length > 0).map((row) => row.id));
    const queue = await readFarmCloudQueue();
    const clips = queue
      .filter((row) => {
        if (judged.has(row.id) || row.ask === "optional_confirm") return false;
        const source = String(row.source || "");
        const ask = String(row.ask || "");
        if (
          (source === "transcript_boundary" || source === "fallback_tile") &&
          ask !== "needs_human" &&
          ask !== "review" &&
          !row.expect_bucket
        ) {
          return false;
        }
        return true;
      })
      .map(visibleFarmClip)
      .sort((a, b) => {
        const rank = (row: { help?: boolean; expect_bucket?: string | null; source?: string }) => {
          if (row.help) return 0;
          if (row.expect_bucket || row.source === "gold_candidate") return 1;
          if (row.source === "still_diff" || row.source === "label_aid" || row.source === "label_aid_boundary") return 2;
          if (row.source === "transcript_boundary" || row.source === "fallback_tile") return 9;
          return 5;
        };
        const ra = rank(a);
        const rb = rank(b);
        if (ra !== rb) return ra - rb;
        return (a.priority ?? 99) - (b.priority ?? 99);
      });
    const helpN = clips.filter((row) => row.help).length;
    return NextResponse.json({
      mode: "clips",
      cloud: true,
      instructions:
        helpN > 0
          ? "Model needs help on these clips. Pick what it is, Add, Done."
          : clips.length > 0
            ? "Queue has clips to label. Pick what it is, Add, Done."
            : "No unlabeled clips right now — sync from the lab after the next farm tick.",
      items: clips,
      saved,
      help_n: helpN,
      remaining: clips.length,
      morning_batch: false,
    });
  }

  const judgments = readJudgments();
  const saved = Object.values(judgments);
  const loaded = loadQueueClips({ unlabeledOnly: true, morningOnly: !all });
  // Full pile used to return 7k+ clips with every still → browser freeze / empty UI.
  const ALL_CAP = 100;
  let clips = loaded.items;
  if (all && clips.length > ALL_CAP) {
    clips = clips.slice(0, ALL_CAP).map((row) => {
      const frames = Array.isArray(row.frames) ? (row.frames as unknown[]) : [];
      return { ...row, frames: frames.slice(0, 5) };
    });
  }
  if (clips.length) {
    const helpN = clips.filter((row) => row.help).length;
    const batchN = clips.filter((row) => row.review_batch === "active").length;
    return NextResponse.json({
      mode: "clips",
      cloud: false,
      instructions: all
        ? `Next ${clips.length} of pile (capped). Prefer morning batch for easy paid_ad confirms.`
        : batchN > 0
          ? `Morning batch: clear these ${batchN} first (paid_ad high → program → rest). ${loaded.parked} parked.`
          : helpN > 0
            ? "Model needs help on these clips. Pick what it is, Add, Done."
            : "Queue has clips to label. Pick what it is, Add, Done.",
      items: clips,
      saved,
      help_n: helpN,
      remaining: all ? loaded.items.length : clips.length,
      morning_batch: !all,
      morning_active: loaded.active,
      morning_parked: loaded.parked,
      capped: all ? ALL_CAP : null,
    });
  }

  const root = streamersRoot();
  if (!fs.existsSync(root)) {
    return NextResponse.json({
      items: [],
      saved: [],
      help_n: 0,
      remaining: 0,
      instructions: "No streamers takes yet.",
    });
  }
  const dirs = fs
    .readdirSync(root)
    .map((name) => path.join(root, name))
    .filter((p) => fs.statSync(p).isDirectory() && fs.existsSync(path.join(p, "audio.wav")))
    .sort();
  const unlabeledTakes = dirs.map(loadTake).filter((row) => {
    const prior = judgments[row.id];
    return !(prior && prior.regions && prior.regions.length > 0);
  });
  return NextResponse.json({
    mode: "takes",
    cloud: false,
    instructions: "Drag the wave to grab a section, then pick what it is.",
    items: unlabeledTakes,
    saved,
    help_n: 0,
    remaining: unlabeledTakes.length,
  });
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    id?: string;
    regions?: Region[];
    av_mismatch?: boolean;
    /** Throw out of dataset: av_lag | black_silent | other */
    discard?: string;
    note?: string;
  };
  const id = String(body.id || "").trim();
  if (!id) return NextResponse.json({ error: "id required" }, { status: 400 });

  const discard = String(body.discard || "").trim();
  if (discard) {
    const reason = discard === "av_lag" || discard === "black_silent" || discard === "other" ? discard : "av_lag";
    const judgment = {
      id,
      regions: [] as Region[],
      saved_at: new Date().toISOString(),
      discarded: true,
      discard_reason: reason,
      av_mismatch: reason === "av_lag",
      note: String(body.note || "").slice(0, 800),
    };
    if (farmCloudMode()) {
      await writeFarmCloudJudgment(judgment);
      return NextResponse.json({ ok: true, id, discarded: true, reason, cloud: true });
    }
    const notes = readJudgments();
    notes[id] = judgment;
    writeJudgments(notes);
    try {
      const out = skipBadClip({ id, reason, note: String(body.note || "") });
      return NextResponse.json({
        ok: true,
        id,
        discarded: true,
        reason,
        trust_gate: out.trust,
      });
    } catch (err) {
      return NextResponse.json({ ok: true, id, discarded: true, reason, lock_error: String(err) });
    }
  }

  const regions = Array.isArray(body.regions) ? body.regions : [];
  for (const row of regions) {
    if (!["paid_ad", "program", "show_promo", "program_mention", "uncertain"].includes(row.bucket)) {
      return NextResponse.json({ error: `bad bucket ${row.bucket}` }, { status: 400 });
    }
  }
  const avBad = Boolean(body.av_mismatch);
  const judgment = {
    id,
    regions: regions.map((r) => ({
      start_s: Number(r.start_s),
      end_s: Number(r.end_s),
      bucket: r.bucket,
      kind: r.kind || "unknown",
      note: String(r.note || "").slice(0, 800),
    })),
    saved_at: new Date().toISOString(),
    ...(avBad ? { av_mismatch: true } : {}),
  };

  if (farmCloudMode()) {
    await writeFarmCloudJudgment(judgment);
    return NextResponse.json({ ok: true, id, regions: judgment.regions.length, cloud: true });
  }

  const notes = readJudgments();
  notes[id] = judgment;
  writeJudgments(notes);

  // A/V lag flag on Done → skip out of dataset (do not gold-lock).
  if (avBad) {
    try {
      const out = skipBadClip({
        id,
        reason: "av_lag",
        note: judgment.regions[0]?.note || "audio≠picture",
      });
      return NextResponse.json({
        ok: true,
        id,
        discarded: true,
        reason: "av_lag",
        regions: judgment.regions.length,
        trust_gate: out.trust,
      });
    } catch (err) {
      return NextResponse.json({
        ok: true,
        id,
        discarded: true,
        regions: judgment.regions.length,
        lock_error: String(err),
      });
    }
  }

  let lock: { trust?: Record<string, unknown> } | null = null;
  if (judgment.regions.length > 0) {
    const pick =
      judgment.regions.find((r) => r.bucket !== "uncertain") || judgment.regions[0];
    try {
      lock = lockHumanClip({
        id,
        bucket: pick.bucket,
        kind: pick.kind || "unknown",
        note: pick.note || "",
        regions: judgment.regions as unknown as Array<Record<string, unknown>>,
      });
    } catch (err) {
      return NextResponse.json(
        {
          ok: true,
          id,
          regions: notes[id].regions.length,
          lock_error: String(err),
        },
        { status: 200 },
      );
    }
  }
  return NextResponse.json({
    ok: true,
    id,
    regions: notes[id].regions.length,
    trust_gate: lock?.trust ?? null,
  });
}
