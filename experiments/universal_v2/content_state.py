"""Universal v2 content-state challenger.

Preregistered before this process reads a score.

Question: can a causal acoustic content model, fit on earlier games and
applied without a DSP trigger, cover at least 1,000 more scorable commercial
seconds than Universal v1 while covering at most 10 seconds of programming,
on later broadcasts from at least two sources?

Frozen split, by whole recording:

- Train: Sept 9 NBC, Sept 24 Prime.
- Calibrate: Sept 13 NBC, Sept 14 ESPN. The operating point is chosen here.
- Evaluate: Oct 8 Prime Video and the four October cable recordings.
  These scores are not used to pick the operating point.
- Controls, not used to fit or to pick the point: RedZone, both Hulu files.

Frozen model: class-balanced L2 logistic regression on 5 seconds of
level-normalized mel shape, loudness, flatness, and stereo correlation.
A decision at time t uses audio [t-5, t) and applies to audio after t.
Unknown holds the previous action. Cover requires p(commercial) at or above
T_high. Return to play requires p(commercial) at or below T_low.
Gold ends, future audio, DSP alarms, fingerprint hits, booth files, and
external feeds are not inputs.

Operating-point rule, calibration games only: among the grid below, maximize
scorable commercial seconds covered, subject to scorable program seconds
covered <= 10. Break ties toward fewer false-cover incidents, then the
higher T_high. If none qualify, the policy stays play and the gate fails.

Grid: T_high in (0.90, 0.95, 0.97, 0.99, 0.995, 0.999),
T_low in (0.05, 0.10, 0.20, 0.30, 0.40), and T_low + 0.20 < T_high.

The development gate is scored on the evaluation recordings only.
Universal v1 artifacts are not rewritten.
"""

from __future__ import annotations

import csv
import json
import resource
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span
from hush.audio import find_session, load_session

RECORDINGS = REPO / "recordings"
OUT = REPO / "docs/ohush/research/UNIVERSAL_V2_CONTENT_STATE_001"
V1_DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
DSP_STARTS = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/starts.csv"
REDZONE = "hush_20260913_150934"
SR = 48000
N_FFT = 2048
HOP = 512
N_MELS = 32
WINDOW_S = 5
L2 = 1.0
IRLS_STEPS = 80
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


def mel_bank() -> np.ndarray:
    n_freq = N_FFT // 2 + 1
    def hz_to_mel(hz: float) -> float:
        return 2595.0 * np.log10(1.0 + hz / 700.0)
    def mel_to_hz(mel: float) -> float:
        return 700.0 * (10 ** (mel / 2595.0) - 1.0)
    edges = mel_to_hz(np.linspace(hz_to_mel(0.0), hz_to_mel(8000.0), N_MELS + 2))
    bins = np.floor((N_FFT + 1) * edges / SR).astype(int)
    bank = np.zeros((N_MELS, n_freq), dtype=np.float64)
    for index in range(N_MELS):
        left, center, right = bins[index], bins[index + 1], bins[index + 2]
        if center <= left:
            center = left + 1
        if right <= center:
            right = center + 1
        for freq in range(left, min(center, n_freq)):
            bank[index, freq] = (freq - left) / (center - left)
        for freq in range(center, min(right, n_freq)):
            bank[index, freq] = (right - freq) / (right - center)
    return bank


BANK = mel_bank()
WINDOW = np.hanning(N_FFT)


def second_features(stereo: np.ndarray) -> np.ndarray:
    mono = 0.5 * (stereo[:, 0].astype(np.float64) + stereo[:, 1].astype(np.float64))
    rms = float(np.sqrt(np.mean(mono * mono)) + 1e-12)
    count = 1 + (len(mono) - N_FFT) // HOP
    frames = np.lib.stride_tricks.as_strided(
        mono,
        shape=(count, N_FFT),
        strides=(mono.strides[0] * HOP, mono.strides[0]),
    )
    spec = np.abs(np.fft.rfft(frames * WINDOW, axis=1)).mean(axis=0) + 1e-12
    mel = np.log(BANK @ spec + 1e-8)
    mel = mel - np.max(mel)
    mel = mel - np.log(np.sum(np.exp(mel)))
    flat = float(np.exp(np.mean(np.log(spec))) / np.mean(spec))
    left, right = stereo[:, 0].astype(np.float64), stereo[:, 1].astype(np.float64)
    denom = float(np.sqrt(np.sum(left * left) * np.sum(right * right)))
    corr = float(np.sum(left * right) / denom) if denom > 0 else 0.0
    return np.concatenate([mel, [20.0 * np.log10(rms), flat, corr]])


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
        meta = load_session(folder)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": meta,
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods = []
    for row in raw:
        sid = row["session"]
        pods.append({
            "session": sid,
            "network": sessions[sid]["network"],
            "content": sessions[sid]["content"],
            "start": float(row["start_seconds"]),
            "end": float(row["end_seconds"]),
        })
    return sessions, pods


def scan(sessions) -> tuple[dict, dict]:
    features = {}
    holes = defaultdict(list)
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        cursor = cov0
        got = {}
        while cursor < cov1 - 0.5:
            take = min(90.0, cov1 - cursor)
            try:
                audio = read_span(bag["dir"], bag["meta"], cursor, min(cov1, cursor + take))
            except RuntimeError:
                hole = min(5.0, cov1 - cursor)
                holes[sid].append((cursor, cursor + hole))
                cursor += 5.0
                continue
            seconds = len(audio) // SR
            for index in range(seconds):
                end = cursor + index + 1.0
                if end > cov1 + 1e-6:
                    break
                sample = audio[index * SR:(index + 1) * SR]
                if len(sample) < SR:
                    break
                got[round(end, 3)] = second_features(sample)
            cursor += take
        features[sid] = got
        print(f"  scanned {sid} seconds {len(got)} holes {sum(b-a for a,b in holes[sid]):.1f}", flush=True)
    return features, holes


def decision_rows(sid, bag, seconds, holes) -> list[dict]:
    cov0, cov1 = bag["coverage"]
    hole_spans = holes.get(sid, [])
    rows = []
    t = cov0 + WINDOW_S
    while t <= cov1 + 1e-6:
        pieces = []
        missing = False
        for age in range(WINDOW_S):
            key = round(t - age, 3)
            if key not in seconds:
                missing = True
                break
            pieces.append(seconds[key])
        start = t - WINDOW_S
        if any(not (h1 <= start or h0 >= t) for h0, h1 in hole_spans):
            missing = True
        if not missing:
            rows.append({"t": t, "x": np.mean(pieces, axis=0)})
        t += 1.0
    return rows


def window_label(sid, t, pods, holes, coverage) -> str | None:
    start = t - WINDOW_S
    if any(not (h1 <= start or h0 >= t) for h0, h1 in holes.get(sid, [])):
        return None
    if overlap([(start, t)], [coverage]) < WINDOW_S - 1e-6:
        return None
    commercial = overlap([(start, t)], [(p["start"], p["end"]) for p in pods if p["session"] == sid])
    if commercial >= 2.5:
        return "commercial"
    if commercial == 0.0:
        return "program"
    return None


def fit(rows, labels) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.vstack([row["x"] for row in rows])
    y = np.array([1.0 if label == "commercial" else 0.0 for label in labels])
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-8] = 1.0
    z = (x - mean) / std
    design = np.concatenate([z, np.ones((len(z), 1))], axis=1)
    positive = float(y.sum())
    negative = float(len(y) - positive)
    weights = np.where(y > 0.5, 0.5 * len(y) / positive, 0.5 * len(y) / negative)
    beta = np.zeros(design.shape[1])
    eye = np.eye(design.shape[1])
    eye[-1, -1] = 0.0
    for _ in range(IRLS_STEPS):
        linear = np.clip(design @ beta, -20.0, 20.0)
        prob = 1.0 / (1.0 + np.exp(-linear))
        curved = weights * prob * (1.0 - prob) + 1e-6
        hessian = design.T @ (design * curved[:, None]) + L2 * eye
        grad = design.T @ (weights * (prob - y)) + L2 * (eye @ beta)
        beta -= np.linalg.solve(hessian, grad)
    return beta, mean, std


def probability(x, beta, mean, std) -> float:
    z = (x - mean) / std
    linear = float(np.clip(np.dot(beta[:-1], z) + beta[-1], -20.0, 20.0))
    return float(1.0 / (1.0 + np.exp(-linear)))


def grid_pairs():
    pairs = []
    for high in T_HIGH:
        for low in T_LOW:
            if low + 0.20 < high:
                pairs.append((high, low))
    return pairs


def actions_for(coverage, decisions, high, low):
    cov0, cov1 = coverage
    state, reason = "play", "insufficient_evidence"
    spans = []
    cursor = cov0
    for row in decisions:
        if row["t"] > cursor:
            spans.append((cursor, row["t"], state, reason))
        if row["p"] >= high:
            state, reason = "cover", "positive_commercial_content"
        elif row["p"] <= low:
            state, reason = "play", "positive_program_content"
        cursor = row["t"]
    if cov1 > cursor:
        spans.append((cursor, cov1, state, reason))
    return [(a, b, action, why) for a, b, action, why in spans if b > a]


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


def covers(actions):
    return [(a, b) for a, b, action, _why in actions if action == "cover"]


def plays(actions):
    return [(a, b) for a, b, action, _why in actions if action == "play"]


def score_sessions(name, sids, sessions, pods, holes, action_map) -> dict:
    per = []
    for sid in sids:
        bag = sessions[sid]
        cov = [bag["coverage"]]
        hole = holes.get(sid, [])
        commercial = subtract([(p["start"], p["end"]) for p in pods if p["session"] == sid], hole)
        program = subtract(subtract(cov, [(p["start"], p["end"]) for p in pods if p["session"] == sid]), hole)
        covered = covers(action_map[sid])
        heard = overlap(commercial, plays(action_map[sid]))
        program_covered = overlap(program, covered)
        incidents = intersect(covered, program)
        per.append({
            "session": sid,
            "network": bag["network"],
            "commercial_seconds_heard": round(heard, 1),
            "commercial_seconds_covered": round(overlap(commercial, covered), 1),
            "program_seconds_covered": round(program_covered, 1),
            "false_cover_incidents": len(incidents),
            "worst_program_interruption_s": round(max((b - a for a, b in incidents), default=0.0), 1),
            "scorable_commercial_s": round(sum(b - a for a, b in commercial), 1),
            "scorable_program_s": round(sum(b - a for a, b in program), 1),
            "unscorable_s": round(sum(b - a for a, b in hole), 1),
        })
    return {
        "population": name,
        "commercial_seconds_heard": round(sum(row["commercial_seconds_heard"] for row in per), 1),
        "commercial_seconds_covered": round(sum(row["commercial_seconds_covered"] for row in per), 1),
        "program_seconds_covered": round(sum(row["program_seconds_covered"] for row in per), 1),
        "false_cover_incidents": sum(row["false_cover_incidents"] for row in per),
        "worst_program_interruption_s": round(max((row["worst_program_interruption_s"] for row in per), default=0.0), 1),
        "sessions": per,
    }


def select(calibration_scores: list[dict]) -> dict:
    feasible = [row for row in calibration_scores if row["program_seconds_covered"] <= PROGRAM_CAP_S]
    if not feasible:
        return {"T_high": None, "T_low": None, "fallback": "play", "reason": "no grid point stayed within 10 program seconds"}
    feasible.sort(key=lambda row: (-row["commercial_seconds_covered"], row["false_cover_incidents"], -row["T_high"]))
    return {"T_high": feasible[0]["T_high"], "T_low": feasible[0]["T_low"], "fallback": None, "reason": "max commercial seconds within the program cap"}


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    sessions, pods = load_world()
    print("scanning", flush=True)
    features, holes = scan(sessions)
    football = [sid for sid, bag in sessions.items() if bag["content"] == "sports" and sid != REDZONE]
    gross_cov = sum(sessions[sid]["coverage"][1] - sessions[sid]["coverage"][0] for sid in football)
    gross_ad = sum(pod["end"] - pod["start"] for pod in pods if pod["session"] in football)
    hole_s = {sid: round(sum(b - a for a, b in holes.get(sid, [])), 3) for sid in football}
    if abs(hole_s.get("hush_20261008_205100", 0) - 240.0) > 0.05 or abs(hole_s.get("hush_20261011_204300", 0) - 35.0) > 0.05:
        raise SystemExit(f"read-failure holes do not match Universal v1: {hole_s}")
    missing_commercial = 0.0
    missing_program = 0.0
    for sid in football:
        hole = holes.get(sid, [])
        ads = [(pod["start"], pod["end"]) for pod in pods if pod["session"] == sid]
        cov = [sessions[sid]["coverage"]]
        missing_commercial += overlap(ads, hole)
        missing_program += overlap(subtract(cov, ads), hole)
    gate0 = {
        "gross_football_coverage_s": round(gross_cov, 3),
        "gross_commercial_s": round(gross_ad, 3),
        "gross_program_s": round(gross_cov - gross_ad, 3),
        "dsp_integer_program_s": 67446,
        "published_18_73h_s": round(18.73 * 3600, 3),
        "published_note": "18.73 is 67446/3600 rounded to two decimals. 18.73*3600 is 67428, eighteen seconds under the DSP integer total.",
        "v1_read_failure_s": round(sum(hole_s.values()), 3),
        "missing_commercial_s": round(missing_commercial, 3),
        "missing_program_s": round(missing_program, 3),
        "scorable_commercial_s": round(gross_ad - missing_commercial, 3),
        "scorable_program_s": round(gross_cov - gross_ad - missing_program, 3),
        "like_for_like_no_cover_heard_s": round(gross_ad - missing_commercial, 3),
        "budget_99_99_on_gross_coverage_s": round(0.0001 * gross_cov, 3),
        "budget_99_99_published_s": round(0.0001 * (18.73 * 3600 + gross_ad), 3),
    }
    print("gate0", json.dumps(gate0), flush=True)

    decisions = {}
    train_x = []
    train_y = []
    for sid, bag in sessions.items():
        rows = decision_rows(sid, bag, features[sid], holes)
        for row in rows:
            row["p"] = None
            if sid in TRAIN and abs((row["t"] - bag["coverage"][0]) % 5.0) < 1e-6:
                label = window_label(sid, row["t"], pods, holes, bag["coverage"])
                if label is not None:
                    train_x.append(row)
                    train_y.append(label)
        decisions[sid] = rows
        print(f"  decisions {sid} {len(rows)}", flush=True)
    if train_y.count("commercial") < 10 or train_y.count("program") < 10:
        raise SystemExit("training split is missing a class")
    beta, mean, std = fit(train_x, train_y)
    for sid, rows in decisions.items():
        for row in rows:
            row["p"] = probability(row["x"], beta, mean, std)
            row.pop("x")

    def metrics_for(sids, high, low) -> dict:
        action_map = {sid: actions_for(sessions[sid]["coverage"], decisions[sid], high, low) for sid in sids}
        scored = score_sessions("block", sids, sessions, pods, holes, action_map)
        scored["T_high"] = high
        scored["T_low"] = low
        return scored

    calibration_frontier = [metrics_for(CALIBRATE, high, low) for high, low in grid_pairs()]
    chosen = select(calibration_frontier)
    print("chosen", chosen, flush=True)
    if chosen["fallback"] == "play":
        high, low = 1.1, -0.1
    else:
        high, low = chosen["T_high"], chosen["T_low"]
    populations = {
        "train": TRAIN,
        "calibration": CALIBRATE,
        "evaluation": EVAL,
        "redzone": (REDZONE,),
        "scripted": tuple(sid for sid, bag in sessions.items() if bag["content"] != "sports"),
        "football": tuple(football),
    }
    scored = {name: metrics_for(sids, high, low) for name, sids in populations.items()}
    evaluation_frontier = [metrics_for(EVAL, pair_high, pair_low) for pair_high, pair_low in grid_pairs()]

    v1_rows = []
    for line in V1_DECISIONS.open(encoding="utf-8"):
        row = json.loads(line)
        v1_rows.append(row)
    v1_map = {sid: v1_actions(sid, sessions[sid]["coverage"], v1_rows) for sid in sessions}
    v1_eval = score_sessions("v1", EVAL, sessions, pods, holes, v1_map)
    v2_eval = scored["evaluation"]
    additional = 0.0
    for sid in EVAL:
        hole = holes.get(sid, [])
        commercial = subtract([(p["start"], p["end"]) for p in pods if p["session"] == sid], hole)
        gained = intersect(commercial, covers(actions_for(sessions[sid]["coverage"], decisions[sid], high, low)))
        already = intersect(commercial, covers(v1_map[sid]))
        additional += sum(b - a for a, b in subtract(gained, already))
    by_network = defaultdict(lambda: {"additional_commercial_s": 0.0, "program_s": 0.0})
    for row in v2_eval["sessions"]:
        v1_row = next(item for item in v1_eval["sessions"] if item["session"] == row["session"])
        extra = row["commercial_seconds_covered"] - v1_row["commercial_seconds_covered"]
        by_network[row["network"]]["additional_commercial_s"] += extra
        by_network[row["network"]]["program_s"] += row["program_seconds_covered"]
    positive_networks = [name for name, row in by_network.items() if row["additional_commercial_s"] > 0 and row["program_s"] <= PROGRAM_CAP_S]
    gate_pass = (
        additional >= COMMERCIAL_GAIN_S
        and v2_eval["program_seconds_covered"] <= PROGRAM_CAP_S
        and len(positive_networks) >= 2
    )
    verdict = "PASS" if gate_pass else "FAIL"

    missed = []
    starts = list(csv.DictReader(DSP_STARTS.open(encoding="utf-8")))
    for pod in pods:
        if pod["session"] not in football:
            continue
        hit = next((row for row in starts if row["session"] == pod["session"] and abs(float(row["boundary_s"]) - pod["start"]) < 0.05), None)
        if hit is None or hit["or_within_3"] == "True":
            continue
        action = actions_for(sessions[pod["session"]]["coverage"], decisions[pod["session"]], high, low)
        first = None
        for left, right in covers(action):
            if right > pod["start"] and left < pod["end"]:
                first = max(left, pod["start"])
                break
        advance = any(row["p"] >= high and row["t"] <= pod["start"] for row in decisions[pod["session"]])
        hole = holes.get(pod["session"], [])
        span = subtract([(pod["start"], pod["end"])], hole)
        heard = overlap(span, plays(action))
        missed.append({
            "session": pod["session"],
            "network": pod["network"],
            "start": round(pod["start"], 3),
            "length_s": round(pod["end"] - pod["start"], 1),
            "detected": first is not None,
            "earliest_cover_s": None if first is None else round(first, 3),
            "delay_s": None if first is None else round(first - pod["start"], 3),
            "commercial_seconds_still_heard": round(heard, 1),
            "evidence_before_boundary": advance,
            "dsp": "no_within_3s",
        })

    errors = []
    for sid in football:
        action = actions_for(sessions[sid]["coverage"], decisions[sid], high, low)
        hole = holes.get(sid, [])
        program = subtract(subtract([sessions[sid]["coverage"]], [(p["start"], p["end"]) for p in pods if p["session"] == sid]), hole)
        for left, right in intersect(covers(action), program):
            errors.append({"kind": "program_covered", "session": sid, "start": round(left, 3), "seconds": round(right - left, 1)})
        for pod in pods:
            if pod["session"] != sid:
                continue
            heard = overlap(subtract([(pod["start"], pod["end"])], hole), plays(action))
            if heard > 0:
                errors.append({"kind": "commercial_heard", "session": sid, "start": round(pod["start"], 3), "seconds": round(heard, 1)})
    errors.sort(key=lambda row: -row["seconds"])

    # Reliability on calibration, bins of predicted probability, commercial rate. Gold is the audit, not an input.
    bins = []
    for lo in np.linspace(0.0, 0.9, 10):
        hi = lo + 0.1
        mass = []
        for sid in CALIBRATE:
            for row in decisions[sid]:
                if lo <= row["p"] < hi or (hi == 1.0 and row["p"] == 1.0):
                    label = window_label(sid, row["t"], pods, holes, sessions[sid]["coverage"])
                    if label is not None:
                        mass.append(1.0 if label == "commercial" else 0.0)
        bins.append({
            "p_lo": round(float(lo), 1),
            "n": len(mass),
            "commercial_rate": None if not mass else round(float(np.mean(mass)), 3),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    receipt_path = OUT / "receipts.jsonl"
    with receipt_path.open("w", encoding="utf-8") as handle:
        for sid in list(TRAIN) + list(CALIBRATE) + list(EVAL) + [REDZONE] + list(populations["scripted"]):
            for row in decisions[sid]:
                if row["p"] >= high:
                    label, action = "COMMERCIAL", "cover"
                elif row["p"] <= low:
                    label, action = "PROGRAM", "play"
                else:
                    label, action = "UNKNOWN", "hold"
                handle.write(json.dumps({
                    "session": sid,
                    "t_decision": row["t"],
                    "audio": [round(row["t"] - WINDOW_S, 3), row["t"]],
                    "p_commercial": round(row["p"], 6),
                    "state": label,
                    "action_after_decision": action,
                    "T_high": high,
                    "T_low": low,
                    "dsp": "not_an_input",
                    "fingerprint": "not_an_input",
                    "handoff": "not_measured",
                    "verified_speaker": "none_enrolled",
                }) + "\n")

    payload = {
        "system": "universal_v2_content_state",
        "verdict": verdict,
        "gate": {
            "additional_commercial_seconds_vs_v1_on_evaluation": round(additional, 3),
            "evaluation_program_seconds_covered": v2_eval["program_seconds_covered"],
            "program_cap_s": PROGRAM_CAP_S,
            "commercial_gain_required_s": COMMERCIAL_GAIN_S,
            "broadcasters_with_a_gain_inside_the_cap": positive_networks,
            "met": gate_pass,
        },
        "chosen_on_calibration": chosen,
        "gate0": gate0,
        "not_measured": {
            "cnn14_full_embedding": "The stored series are anomaly scores, not embedding vectors, and October football has no series. Torch is not installed.",
            "audio_text_model": "No CLAP or audio-text checkpoint is installed.",
            "full_stream_asr": "Not run. The sign-off study remains the gold-neighborhood transcripts only.",
            "verified_speaker": "Enrollment count is 0. Booth files were not read.",
            "enhanced_feed": "No accuracy number.",
        },
        "split": {"train": TRAIN, "calibration": CALIBRATE, "evaluation": EVAL},
        "train_windows": {"n": len(train_y), "commercial": train_y.count("commercial"), "program": train_y.count("program")},
        "scored": scored,
        "v1_evaluation": v1_eval,
        "calibration_frontier": [
            {key: row[key] for key in ("T_high", "T_low", "commercial_seconds_covered", "program_seconds_covered", "false_cover_incidents", "worst_program_interruption_s")}
            for row in calibration_frontier
        ],
        "evaluation_frontier_not_used_for_selection": [
            {key: row[key] for key in ("T_high", "T_low", "commercial_seconds_covered", "program_seconds_covered", "false_cover_incidents", "worst_program_interruption_s")}
            for row in evaluation_frontier
        ],
        "dsp_missed_starts": {
            "n": len(missed),
            "detected": sum(1 for row in missed if row["detected"]),
            "evidence_before_boundary": sum(1 for row in missed if row["evidence_before_boundary"]),
            "rows": missed,
        },
        "top_errors": errors[:20],
        "calibration_reliability": bins,
        "by_network_evaluation": {name: {key: round(value, 1) for key, value in row.items()} for name, row in by_network.items()},
        "wall_s": round(time.perf_counter() - started, 1),
        "max_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "gate": payload["gate"], "chosen": chosen}, indent=2))


if __name__ == "__main__":
    main()
