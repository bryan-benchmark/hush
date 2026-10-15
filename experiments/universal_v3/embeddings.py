"""Universal v3: frozen CNN14 penultimate embeddings as a causal challenger.

Preregistered before scores are read.

The vector is the L2-normalized penultimate embedding. The anomaly distance
is not computed and is not a threshold. Window 10 s, hop 10 s. A decision
at time t uses audio [t-10, t) and applies after t.

Train prototypes: Sept 9 NBC and Sept 24 Prime.
Thresholds: Sept 13 NBC and ESPN only.
October games are scored and were already inspected, so they are not blind
validation. The operating point is not chosen there.

Score = cosine to the train commercial mean minus cosine to the train
program mean. A two-parameter logistic maps that scalar to a probability
on the train windows only. The same grid and 10-second program cap as v2
decide the action. If no calibration point qualifies, the policy stays play.

Fingerprints, DSP, booth files, gold ends, and external feeds are not inputs.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span
from hush.audio import find_session, load_session

RECORDINGS = REPO / "recordings"
OUT = REPO / "docs/ohush/research/UNIVERSAL_V3_EMBEDDINGS_001"
CACHE = REPO / "experiments/universal_v3/cache"
CHECKPOINT = REPO / "experiments/exp003/models/Cnn14_mAP=0.431.pth"
V1_DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
DSP_STARTS = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/starts.csv"
REDZONE = "hush_20260913_150934"
SR_IN = 48000
SR = 32000
WINDOW_S = 10.0
HOP_S = 10.0
BATCH = 16
TRAIN = ("hush_20260909_213047", "hush_20260924_220624")
CALIBRATE = ("hush_20260913_210542", "hush_20260914_212529")
EVAL = (
    "hush_20261008_205100",
    "hush_20261010_222400",
    "hush_20261011_135700",
    "hush_20261011_204300",
    "hush_20261012_204200",
)
T_HIGH = (0.90, 0.95, 0.97, 0.99, 0.995, 0.999)
T_LOW = (0.05, 0.10, 0.20, 0.30, 0.40)
PROGRAM_CAP_S = 10.0
COMMERCIAL_GAIN_S = 1000.0


def subtract(base, cuts):
    parts = list(base)
    for cut0, cut1 in cuts:
        nxt = []
        for left, right in parts:
            if cut1 <= left or cut0 >= right:
                nxt.append((left, right))
                continue
            if left < cut0:
                nxt.append((left, min(cut0, right)))
            if cut1 < right:
                nxt.append((max(cut1, left), right))
        parts = [(left, right) for left, right in nxt if right - left > 1e-9]
    return parts


def overlap(left, right) -> float:
    total = 0.0
    for a0, a1 in left:
        for b0, b1 in right:
            total += max(0.0, min(a1, b1) - max(a0, b0))
    return total


def merge(spans):
    ordered = sorted((a, b) for a, b in spans if b > a)
    if not ordered:
        return []
    out = [list(ordered[0])]
    for left, right in ordered[1:]:
        if left <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], right)
        else:
            out.append([left, right])
    return [(a, b) for a, b in out]


def intersect(left, right):
    pieces = []
    for a0, a1 in left:
        for b0, b1 in right:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                pieces.append((lo, hi))
    return merge(pieces)


def load_world():
    catalog = load_catalog()
    spans = coverage()
    raw = commercials(spans)
    if len(raw) != 166:
        raise SystemExit(f"expected 166 commercials, found {len(raw)}")
    sessions = {}
    for span in spans:
        sid = span["session"]
        folder = find_session(RECORDINGS, sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods = [{
        "session": row["session"],
        "start": float(row["start_seconds"]),
        "end": float(row["end_seconds"]),
        "network": sessions[row["session"]]["network"],
    } for row in raw]
    return sessions, pods


def extract(sessions, tagger) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    stored = {}
    for sid, bag in sessions.items():
        cache = CACHE / f"{sid}.npz"
        if cache.exists():
            data = np.load(cache)
            hole_a = data["hole_a"] if "hole_a" in data.files else np.zeros(0)
            hole_b = data["hole_b"] if "hole_b" in data.files else np.zeros(0)
            stored[sid] = {"t": data["t"], "embedding": data["embedding"], "holes": list(zip(hole_a.tolist(), hole_b.tolist()))}
            print(f"  cache {sid} {len(data['t'])}", flush=True)
            continue
        print(f"  start {sid}", flush=True)
        cov0, cov1 = bag["coverage"]
        times = []
        vectors = []
        hole_spans = []
        pending_audio = []
        pending_t = []
        carry = np.zeros(0, np.float32)
        carry_origin = None
        cursor = cov0
        while cursor < cov1 - 0.5:
            take = min(90.0, cov1 - cursor)
            try:
                audio = read_span(bag["dir"], bag["meta"], cursor, min(cov1, cursor + take))
            except RuntimeError:
                hole_spans.append((cursor, cursor + min(5.0, cov1 - cursor)))
                cursor += 5.0
                carry = np.zeros(0, np.float32)
                carry_origin = None
                continue
            mono = 0.5 * (audio[:, 0].astype(np.float64) + audio[:, 1].astype(np.float64))
            fresh = resample_poly(mono, 2, 3).astype(np.float32)
            used_carry = carry_origin is not None and abs((carry_origin + len(carry) / SR) - cursor) < 0.02
            if used_carry:
                samples = np.concatenate([carry, fresh])
                origin = float(carry_origin)
            else:
                samples = fresh
                origin = cursor
            read_end = min(cov1, cursor + take)
            end = cov0 + WINDOW_S
            # A window that ended on the previous read is already stored.
            skip_until = cursor if used_carry else origin
            while end < skip_until + 1e-3:
                end += HOP_S
            while end <= read_end + 1e-6:
                a = int(round((end - WINDOW_S - origin) * SR))
                b = a + int(WINDOW_S * SR)
                if a >= 0 and b <= len(samples):
                    pending_audio.append(samples[a:b])
                    pending_t.append(end)
                end += HOP_S
                if len(pending_audio) == BATCH:
                    _clip, emb = tagger.inference(np.stack(pending_audio))
                    matrix = np.asarray(emb, dtype=np.float32)
                    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12
                    vectors.append(matrix)
                    times.extend(pending_t)
                    pending_audio, pending_t = [], []
            keep_from = read_end - WINDOW_S
            keep_at = int(round((keep_from - origin) * SR))
            if 0 <= keep_at < len(samples):
                carry = samples[keep_at:].copy()
                carry_origin = keep_from
            else:
                carry = np.zeros(0, np.float32)
                carry_origin = None
            cursor += take
        if pending_audio:
            _clip, emb = tagger.inference(np.stack(pending_audio))
            matrix = np.asarray(emb, dtype=np.float32)
            matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12
            vectors.append(matrix)
            times.extend(pending_t)
        embedding = np.vstack(vectors) if vectors else np.zeros((0, 2048), np.float32)
        t = np.asarray(times, dtype=np.float64)
        np.savez_compressed(cache, t=t, embedding=embedding, hole_a=np.asarray([a for a, _b in hole_spans], dtype=np.float64), hole_b=np.asarray([b for _a, b in hole_spans], dtype=np.float64))
        stored[sid] = {"t": t, "embedding": embedding, "holes": hole_spans}
        print(f"  embedded {sid} {len(t)}", flush=True)
    return stored


def label_of(sid, t, pods) -> str | None:
    start = t - WINDOW_S
    commercial = overlap([(start, t)], [(p["start"], p["end"]) for p in pods if p["session"] == sid])
    if commercial >= 5.0:
        return "commercial"
    if commercial == 0.0:
        return "program"
    return None


def fit_scalar(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    design = np.column_stack([scores, np.ones(len(scores))])
    y = labels.astype(np.float64)
    positive = max(float(y.sum()), 1.0)
    negative = max(float(len(y) - y.sum()), 1.0)
    weights = np.where(y > 0.5, 0.5 * len(y) / positive, 0.5 * len(y) / negative)
    beta = np.zeros(2)
    for _ in range(80):
        linear = np.clip(design @ beta, -20.0, 20.0)
        prob = 1.0 / (1.0 + np.exp(-linear))
        curved = weights * prob * (1.0 - prob) + 1e-6
        hessian = design.T @ (design * curved[:, None]) + np.diag([1.0, 0.0])
        grad = design.T @ (weights * (prob - y)) + np.array([beta[0], 0.0])
        beta -= np.linalg.solve(hessian, grad)
    return float(beta[0]), float(beta[1])


def actions_for(coverage, rows, high, low):
    cov0, cov1 = coverage
    state, reason = "play", "insufficient_evidence"
    spans = []
    cursor = cov0
    for row in rows:
        if row["t"] > cursor:
            spans.append((cursor, row["t"], state, reason))
        if row["p"] >= high:
            state, reason = "cover", "positive_commercial_embedding"
        elif row["p"] <= low:
            state, reason = "play", "positive_program_embedding"
        cursor = row["t"]
    if cov1 > cursor:
        spans.append((cursor, cov1, state, reason))
    return [(a, b, action, why) for a, b, action, why in spans if b > a]


def covers(actions):
    return [(a, b) for a, b, action, _why in actions if action == "cover"]


def plays(actions):
    return [(a, b) for a, b, action, _why in actions if action == "play"]


def v1_actions(sid, coverage, rows):
    cov0, cov1 = coverage
    here = [row for row in rows if row["session"] == sid]
    if not here:
        return [(cov0, cov1, "play", "insufficient_evidence")]
    spans = [(cov0, here[0]["available_at"], "play", "insufficient_evidence")]
    for index, row in enumerate(here):
        end = cov1 if index + 1 == len(here) else here[index + 1]["available_at"]
        if row["score"] >= 200 and not row["same_session"]:
            spans.append((row["available_at"], end, "cover", "positive_commercial_fingerprint"))
        else:
            spans.append((row["available_at"], end, "play", "insufficient_evidence"))
    return [(a, b, action, why) for a, b, action, why in spans if b > a]


def score_block(sids, sessions, pods, holes, action_map) -> dict:
    per = []
    for sid in sids:
        bag = sessions[sid]
        hole = holes.get(sid, [])
        commercial = subtract([(p["start"], p["end"]) for p in pods if p["session"] == sid], hole)
        program = subtract(subtract([bag["coverage"]], [(p["start"], p["end"]) for p in pods if p["session"] == sid]), hole)
        covered = covers(action_map[sid])
        incidents = intersect(covered, program)
        per.append({
            "session": sid,
            "network": bag["network"],
            "commercial_seconds_heard": round(overlap(commercial, plays(action_map[sid])), 1),
            "commercial_seconds_covered": round(overlap(commercial, covered), 1),
            "program_seconds_covered": round(overlap(program, covered), 1),
            "false_cover_incidents": len(incidents),
            "worst_program_interruption_s": round(max((b - a for a, b in incidents), default=0.0), 1),
        })
    return {
        "commercial_seconds_covered": round(sum(row["commercial_seconds_covered"] for row in per), 1),
        "commercial_seconds_heard": round(sum(row["commercial_seconds_heard"] for row in per), 1),
        "program_seconds_covered": round(sum(row["program_seconds_covered"] for row in per), 1),
        "false_cover_incidents": sum(row["false_cover_incidents"] for row in per),
        "worst_program_interruption_s": round(max((row["worst_program_interruption_s"] for row in per), default=0.0), 1),
        "sessions": per,
    }


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    import torch
    torch.set_num_threads(4)
    from panns_inference import AudioTagging
    tagger = AudioTagging(checkpoint_path=str(CHECKPOINT), device="cpu")
    sessions, pods = load_world()
    print("extracting", flush=True)
    stored = extract(sessions, tagger)
    holes = {sid: stored[sid]["holes"] for sid in stored}
    football = [sid for sid, bag in sessions.items() if bag["content"] == "sports" and sid != REDZONE]
    thursday = sum(b - a for a, b in holes.get("hush_20261008_205100", []))
    night = sum(b - a for a, b in holes.get("hush_20261011_204300", []))
    if abs(thursday - 240.0) > 0.05 or abs(night - 35.0) > 0.05:
        raise SystemExit(f"read failures do not match v1: thursday {thursday:.3f}, night {night:.3f}")

    train_scores = []
    train_labels = []
    rows = {}
    # Prototypes need train embeddings first.
    commercial_vecs = []
    program_vecs = []
    for sid in TRAIN:
        for index, t in enumerate(stored[sid]["t"]):
            label = label_of(sid, float(t), pods)
            vector = stored[sid]["embedding"][index]
            if label == "commercial":
                commercial_vecs.append(vector)
            elif label == "program":
                program_vecs.append(vector)
    if len(commercial_vecs) < 10 or len(program_vecs) < 10:
        raise SystemExit("training prototypes are missing a class")
    mu_c = np.mean(np.stack(commercial_vecs), axis=0)
    mu_p = np.mean(np.stack(program_vecs), axis=0)
    mu_c /= np.linalg.norm(mu_c) + 1e-12
    mu_p /= np.linalg.norm(mu_p) + 1e-12
    for sid, bag in sessions.items():
        session_rows = []
        for index, t in enumerate(stored[sid]["t"]):
            vector = stored[sid]["embedding"][index]
            score = float(np.dot(vector, mu_c) - np.dot(vector, mu_p))
            session_rows.append({"t": float(t), "score": score})
            if sid in TRAIN:
                label = label_of(sid, float(t), pods)
                if label is not None:
                    train_scores.append(score)
                    train_labels.append(1.0 if label == "commercial" else 0.0)
        rows[sid] = session_rows
    slope, intercept = fit_scalar(np.asarray(train_scores), np.asarray(train_labels))
    for sid in rows:
        for row in rows[sid]:
            linear = max(-20.0, min(20.0, slope * row["score"] + intercept))
            row["p"] = float(1.0 / (1.0 + np.exp(-linear)))

    def metrics(sids, high, low):
        action_map = {sid: actions_for(sessions[sid]["coverage"], rows[sid], high, low) for sid in sids}
        scored = score_block(sids, sessions, pods, holes, action_map)
        scored["T_high"] = high
        scored["T_low"] = low
        return scored, action_map

    frontier = []
    for high in T_HIGH:
        for low in T_LOW:
            if low + 0.20 >= high:
                continue
            scored, _map = metrics(CALIBRATE, high, low)
            frontier.append(scored)
    feasible = [row for row in frontier if row["program_seconds_covered"] <= PROGRAM_CAP_S]
    if not feasible:
        chosen = {"T_high": None, "T_low": None, "fallback": "play"}
        high, low = 1.1, -0.1
    else:
        feasible.sort(key=lambda row: (-row["commercial_seconds_covered"], row["false_cover_incidents"], -row["T_high"]))
        chosen = {"T_high": feasible[0]["T_high"], "T_low": feasible[0]["T_low"], "fallback": None}
        high, low = chosen["T_high"], chosen["T_low"]
    print("chosen", chosen, flush=True)
    populations = {
        "calibration": CALIBRATE,
        "evaluation": EVAL,
        "redzone": (REDZONE,),
        "football": tuple(football),
    }
    scored = {}
    maps = {}
    for name, sids in populations.items():
        block, action_map = metrics(sids, high, low)
        scored[name] = block
        maps[name] = action_map
    v1_rows = [json.loads(line) for line in V1_DECISIONS.open(encoding="utf-8")]
    v1_map = {sid: v1_actions(sid, sessions[sid]["coverage"], v1_rows) for sid in EVAL}
    v1_eval = score_block(EVAL, sessions, pods, holes, v1_map)
    new_seconds = 0.0
    lost_seconds = 0.0
    by_network = {}
    for sid in EVAL:
        hole = holes.get(sid, [])
        commercial = subtract([(p["start"], p["end"]) for p in pods if p["session"] == sid], hole)
        got = intersect(commercial, covers(maps["evaluation"][sid]))
        had = intersect(commercial, covers(v1_map[sid]))
        gained = sum(b - a for a, b in subtract(got, had))
        dropped = sum(b - a for a, b in subtract(had, got))
        new_seconds += gained
        lost_seconds += dropped
        bucket = by_network.setdefault(sessions[sid]["network"], {"newly_covered_s": 0.0, "lost_s": 0.0})
        bucket["newly_covered_s"] += gained
        bucket["lost_s"] += dropped
    for name, row in by_network.items():
        row["newly_covered_s"] = round(row["newly_covered_s"], 3)
        row["lost_s"] = round(row["lost_s"], 3)
        row["net_s"] = round(row["newly_covered_s"] - row["lost_s"], 3)
    net = new_seconds - lost_seconds
    positive = [name for name, row in by_network.items() if row["net_s"] > 0]
    gate_met = net >= COMMERCIAL_GAIN_S and scored["evaluation"]["program_seconds_covered"] <= PROGRAM_CAP_S and len(positive) >= 2
    verdict = "PASS" if gate_met and chosen["fallback"] is None else "FAIL"

    starts = list(csv.DictReader(DSP_STARTS.open(encoding="utf-8")))
    missed = []
    for pod in pods:
        if pod["session"] not in football:
            continue
        hit = next((row for row in starts if row["session"] == pod["session"] and abs(float(row["boundary_s"]) - pod["start"]) < 0.05), None)
        if hit is None or hit["or_within_3"] == "True":
            continue
        first = None
        for left, right in covers(maps["football"][pod["session"]]):
            if right > pod["start"] and left < pod["end"]:
                first = max(left, pod["start"])
                break
        missed.append({"session": pod["session"], "start": round(pod["start"], 3), "detected": first is not None})

    bins = []
    for lo in np.linspace(0.0, 0.9, 10):
        hi = round(float(lo + 0.1), 1)
        mass = []
        for sid in CALIBRATE:
            for row in rows[sid]:
                if lo <= row["p"] < hi or (hi == 1.0 and row["p"] == 1.0):
                    label = label_of(sid, row["t"], pods)
                    if label is not None:
                        mass.append(1.0 if label == "commercial" else 0.0)
        bins.append({"p_lo": round(float(lo), 1), "n": len(mass), "commercial_rate": None if not mass else round(float(np.mean(mass)), 3)})

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "system": "universal_v3_cnn14_embedding",
        "verdict": verdict,
        "october_status": "already_inspected_not_blind",
        "fresh_recordings": 0,
        "embedding": "CNN14 penultimate, L2-normalized, window 10 s, hop 10 s",
        "anomaly_distance_used": False,
        "chosen_on_calibration": chosen,
        "gate": {
            "newly_covered_commercial_s": round(new_seconds, 3),
            "previously_covered_seconds_lost": round(lost_seconds, 3),
            "net_commercial_s_vs_v1": round(net, 3),
            "evaluation_program_seconds_covered": scored["evaluation"]["program_seconds_covered"],
            "broadcasters_with_a_net_gain": positive,
            "by_network": by_network,
            "met": gate_met,
        },
        "scored": scored,
        "v1_evaluation": v1_eval,
        "calibration_frontier": [
            {key: row[key] for key in ("T_high", "T_low", "commercial_seconds_covered", "program_seconds_covered", "false_cover_incidents", "worst_program_interruption_s")}
            for row in frontier
        ],
        "dsp_missed_starts": {"n": len(missed), "detected": sum(1 for row in missed if row["detected"])},
        "calibration_reliability": bins,
        "train_windows": {"n": len(train_labels), "commercial": int(sum(train_labels)), "program": int(len(train_labels) - sum(train_labels))},
        "prototype_separation": round(float(np.dot(mu_c, mu_p)), 4),
        "wall_s": round(time.perf_counter() - started, 1),
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "gate": payload["gate"], "chosen": chosen, "reliability_top": bins[-1]}, indent=2))


if __name__ == "__main__":
    main()
