import fs from "fs";
import path from "path";
import os from "os";

function dataRoot() {
  return process.env.OHUSH_DATA_ROOT || "C:\\OHushData";
}

export function farmLabelDir() {
  return path.join(dataRoot(), "indexes", "farm_labels");
}

function atomicWriteJsonl(file: string, rows: Record<string, unknown>[]) {
  const dir = path.dirname(file);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = `${file}.tmp.${process.pid}.${Date.now()}`;
  const body = rows.map((row) => JSON.stringify(row)).join("\n") + (rows.length ? "\n" : "");
  fs.writeFileSync(tmp, body, "utf8");
  fs.renameSync(tmp, file);
}

function readJsonl(file: string): Record<string, unknown>[] {
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line) as Record<string, unknown>;
      } catch {
        return null;
      }
    })
    .filter((row): row is Record<string, unknown> => Boolean(row));
}

function appendDraftEvent(row: Record<string, unknown>) {
  const file = path.join(farmLabelDir(), "label_draft.jsonl");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, JSON.stringify(row) + "\n", "utf8");
}

function refreshTrustGate() {
  const dir = farmLabelDir();
  const keyPath = path.join(dir, "key.jsonl");
  let gold = 0;
  for (const row of readJsonl(keyPath)) {
    const ask = String(row.ask || "");
    const source = String(row.source || "");
    if (row.gold || ask === "locked" || source === "gold" || source === "human") {
      if (String(row.bucket || "") !== "uncertain") gold += 1;
    }
  }
  const trustPath = path.join(dir, "trust_gate.json");
  let minGold = 30;
  let probeOk = true;
  if (fs.existsSync(trustPath)) {
    try {
      const prior = JSON.parse(fs.readFileSync(trustPath, "utf8")) as Record<string, unknown>;
      minGold = Number(prior.min_gold_for_auto || 30);
    } catch {
      // keep defaults
    }
  }
  const probePath = path.join(dir, "accuracy_probe_results.json");
  if (fs.existsSync(probePath)) {
    try {
      const probe = JSON.parse(fs.readFileSync(probePath, "utf8")) as Record<string, unknown>;
      const score = String(probe.accuracy_probe_score || "");
      if (score.includes("/")) {
        const [n, d] = score.split("/");
        const den = Number(d);
        if (den > 0) probeOk = Number(n) / den >= 0.85;
      }
    } catch {
      probeOk = true;
    }
  }
  const enabled = gold >= minGold && probeOk;
  const trust = {
    gold_clips: gold,
    auto_paid_ad_enabled: enabled,
    min_gold_for_auto: minGold,
    probe_ok: probeOk,
    updated_utc: new Date().toISOString(),
    why: enabled
      ? "Auto paid_ad enabled"
      : `Auto paid_ad disabled until gold ≥${minGold}${probeOk ? "" : " and probe precision ≥0.85"}`,
  };
  fs.writeFileSync(trustPath, JSON.stringify(trust, null, 2) + "\n", "utf8");
  return trust;
}

/** Throw clip out of dataset (A/V lag, black air, etc.) — ask=skip, not gold. */
export function skipBadClip(opts: {
  id: string;
  reason?: string;
  note?: string;
}) {
  const dir = farmLabelDir();
  const keyPath = path.join(dir, "key.jsonl");
  const keys = new Map<string, Record<string, unknown>>();
  for (const row of readJsonl(keyPath)) {
    const clip = String(row.clip || "");
    if (clip) keys.set(clip, row);
  }
  const prior = keys.get(opts.id) || {};
  const now = new Date().toISOString();
  const reason = opts.reason || "av_lag";
  const skipped: Record<string, unknown> = {
    ...prior,
    clip: opts.id,
    bucket: "uncertain",
    kind: prior.kind || "unknown",
    confidence: "low",
    ask: "skip",
    why: `skip_${reason}${opts.note ? `:${opts.note.slice(0, 80)}` : ""}`,
    human_note: (opts.note || "").slice(0, 240),
    source: "human_skip",
    gold: false,
    locked_from: `farm_skip_${reason}`,
    locked_utc: now,
    av_mismatch: reason === "av_lag" ? true : prior.av_mismatch,
  };
  keys.set(opts.id, skipped);
  atomicWriteJsonl(keyPath, Array.from(keys.values()));
  appendDraftEvent({
    utc: now,
    tick_id: `human_skip:${now}`,
    clip: opts.id,
    session: skipped.session ?? null,
    t0: skipped.t0 ?? null,
    t1: skipped.t1 ?? null,
    ask: "skip",
    bucket: "uncertain",
    why: skipped.why,
    prior_ask: prior.ask ?? null,
    prior_bucket: prior.bucket ?? null,
  });
  const queuePath = path.join(dir, "queue.jsonl");
  if (fs.existsSync(queuePath)) {
    const rows = readJsonl(queuePath).map((row) => {
      if (String(row.clip || "") !== opts.id) return row;
      return { ...row, ask: "skip", priority: 99, review_batch: "skip" };
    });
    atomicWriteJsonl(queuePath, rows);
  }
  try {
    const runLog = path.join(dataRoot(), "work", "logs", "farm_run.jsonl");
    fs.mkdirSync(path.dirname(runLog), { recursive: true });
    fs.appendFileSync(
      runLog,
      JSON.stringify({
        utc: now,
        event: "label_human_skip",
        detail: `${opts.id}→skip_${reason}`,
        ok: true,
        extra: { clip: opts.id, reason },
        host: os.hostname(),
      }) + "\n",
      "utf8",
    );
  } catch {
    // ignore
  }
  return { skipped, trust: refreshTrustGate() };
}

/** Lock key + audit after a human /farm save. */
export function lockHumanClip(opts: {
  id: string;
  bucket: string;
  kind: string;
  note: string;
  regions: Array<Record<string, unknown>>;
}) {
  const dir = farmLabelDir();
  const keyPath = path.join(dir, "key.jsonl");
  const keys = new Map<string, Record<string, unknown>>();
  for (const row of readJsonl(keyPath)) {
    const clip = String(row.clip || "");
    if (clip) keys.set(clip, row);
  }
  const prior = keys.get(opts.id) || {};
  const now = new Date().toISOString();
  const isGold = opts.bucket !== "uncertain";
  const locked: Record<string, unknown> = {
    ...prior,
    clip: opts.id,
    bucket: opts.bucket,
    kind: opts.kind || prior.kind || "unknown",
    confidence: "high",
    ask: "locked",
    note: (opts.note || String(prior.note || "")).slice(0, 240),
    human_note: opts.note.slice(0, 240),
    source: "human",
    gold: isGold,
    locked_from: "farm_human",
    locked_utc: now,
    regions: opts.regions,
  };
  keys.set(opts.id, locked);
  atomicWriteJsonl(keyPath, Array.from(keys.values()));
  appendDraftEvent({
    utc: now,
    tick_id: `human:${now}`,
    clip: opts.id,
    session: locked.session ?? null,
    t0: locked.t0 ?? null,
    t1: locked.t1 ?? null,
    ask: "locked",
    bucket: opts.bucket,
    kind: locked.kind,
    confidence: "high",
    why: `human_lock:${opts.note || opts.bucket}`,
    prior_ask: prior.ask ?? null,
    prior_bucket: prior.bucket ?? null,
  });
  const queuePath = path.join(dir, "queue.jsonl");
  if (fs.existsSync(queuePath)) {
    const rows = readJsonl(queuePath).map((row) => {
      if (String(row.clip || "") !== opts.id) return row;
      return { ...row, ask: "locked", priority: 99, review_batch: "done" };
    });
    atomicWriteJsonl(queuePath, rows);
  }
  const trust = refreshTrustGate();
  // Best-effort farm_run receipt (append JSONL).
  try {
    const runLog = path.join(dataRoot(), "work", "logs", "farm_run.jsonl");
    fs.mkdirSync(path.dirname(runLog), { recursive: true });
    fs.appendFileSync(
      runLog,
      JSON.stringify({
        utc: now,
        event: "label_human_lock",
        detail: `${opts.id}→${opts.bucket}`,
        ok: true,
        extra: { clip: opts.id, bucket: opts.bucket, gold: isGold, trust },
        host: os.hostname(),
      }) + "\n",
      "utf8",
    );
  } catch {
    // ignore
  }
  return { locked, trust };
}
