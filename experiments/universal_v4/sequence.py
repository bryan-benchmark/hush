"""Universal v4: causal broadcast departure and return.

Preregistered before scores are read.

This is not another commercial-versus-program snapshot. Three heads are
trained separately:

- depart_advance: a gold start falls in the next 10 seconds. Features end at
  the decision time.
- depart_cut: a gold start falls in the past 1 second, so the cut has been
  heard.
- return_cut: a gold end falls in the past 1 second. A return is not the
  inverse of a departure.

The playback rule covers after a departure probability clears its threshold
and returns to play only after the return head clears its own threshold.
Thresholds are chosen on Sept 13 NBC and ESPN. October is not used to choose
them. If no calibration point covers any commercial audio inside 10 program
seconds, the action policy is retired.

Feature ablations, also chosen only on those two games:
snapshot (frozen 10-second CNN14 probability), subsecond change, one-to-two
second context, a 30-second delay line, and that delay line plus the frozen
CNN14 probability. The CNN14 probability is the v3 prototype and logistic.
It is checked against the published calibration bin before it is used. It is
not refit. The 18 dB micro-dip gate is not applied. Fingerprints, the mel
logistic, and the anomaly distance are not inputs.

Replays and booth transitions are not classes in the frozen gold, so they
are not a separate negative set. Hard negatives that do exist are ordinary
non-events, pod interiors, and RedZone. RedZone is a training negative, so a
later RedZone score is not an unseen control. The 53-clip queue is not
applied. Gold is not edited.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import read_span
from experiments.universal_v3 import embeddings as v3

RECORDINGS = REPO / "recordings"
OUT = REPO / "docs/ohush/research/UNIVERSAL_V4_BROADCAST_SEQUENCE_001"
CACHE = REPO / "experiments/universal_v4/cache"
SR = 48000
FRAME = 1920
LOOKBACK = 2.5
HOP = 1.0
LAGS = (0.0, 2.0, 10.0, 30.0)
THRESHOLDS = (0.90, 0.95, 0.99, 0.999)
PROGRAM_CAP_S = 10.0
COMMERCIAL_GAIN_S = 1000.0
PRIMARY = "history_plus_pretrained"
ABLATION_ORDER = (
    "history_plus_pretrained",
    "history",
    "context",
    "subsecond",
    "snapshot",
)
ACOUSTIC = ("sub_db", "flux", "flat", "rms", "dip_db")


def rms_db(samples: np.ndarray) -> float:
    return float(20.0 * np.log10(np.sqrt(np.mean(np.square(samples))) + 1e-12))


def magnitude(samples: np.ndarray) -> np.ndarray:
    return np.abs(np.fft.rfft(samples * np.hanning(len(samples))))


def spectral_flux(older: np.ndarray, newer: np.ndarray) -> float:
    left = magnitude(older)
    right = magnitude(newer)
    left = left / (np.linalg.norm(left) + 1e-12)
    right = right / (np.linalg.norm(right) + 1e-12)
    return float(np.sum(np.maximum(right - left, 0.0)))


def spectral_flatness(samples: np.ndarray) -> float:
    power = np.maximum(magnitude(samples), 1e-12)
    return float(np.exp(np.mean(np.log(power))) / np.mean(power))


def frame_db(samples: np.ndarray) -> np.ndarray | None:
    count = len(samples) // FRAME
    if count < 1:
        return None
    frames = samples[: count * FRAME].reshape(count, FRAME)
    power = np.mean(np.square(frames), axis=1)
    return 10.0 * np.log10(power + 1e-12)


def features_at(window: np.ndarray) -> list[float]:
    one = SR
    half = SR // 2
    recent = window[-half:]
    previous_half = window[-one:-half]
    last = window[-one:]
    prior = window[-2 * one:-one]
    levels = frame_db(prior)
    recent_levels = frame_db(recent)
    dip = 0.0
    if levels is not None and recent_levels is not None and len(levels) and len(recent_levels):
        dip = float(np.median(levels) - np.min(recent_levels))
    return [
        rms_db(recent) - rms_db(previous_half),
        spectral_flux(prior, last),
        spectral_flatness(last),
        rms_db(last),
        dip,
    ]


def extract(sessions) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    stored = {}
    for sid, bag in sessions.items():
        cache = CACHE / f"{sid}.npz"
        if cache.exists():
            data = np.load(cache)
            stored[sid] = {
                "t": np.array(data["t"]),
                "features": np.array(data["features"]),
                "holes": list(zip(data["hole_a"].tolist(), data["hole_b"].tolist())),
            }
            print(f"  cache {sid} {len(data['t'])}", flush=True)
            continue
        print(f"  start {sid}", flush=True)
        cov0, cov1 = bag["coverage"]
        times = []
        rows = []
        holes = []
        carry = np.zeros(0, np.float32)
        carry_origin = None
        cursor = cov0
        while cursor < cov1 - 0.5:
            take = min(60.0, cov1 - cursor)
            try:
                audio = read_span(bag["dir"], bag["meta"], cursor, min(cov1, cursor + take))
            except RuntimeError:
                holes.append((cursor, cursor + min(5.0, cov1 - cursor)))
                cursor += 5.0
                carry = np.zeros(0, np.float32)
                carry_origin = None
                continue
            mono = 0.5 * (audio[:, 0].astype(np.float32) + audio[:, 1].astype(np.float32))
            used_carry = carry_origin is not None and abs((carry_origin + len(carry) / SR) - cursor) < 0.02
            if used_carry:
                samples = np.concatenate([carry, mono])
                origin = float(carry_origin)
            else:
                samples = mono
                origin = cursor
            read_end = min(cov1, cursor + take)
            t = cov0 + HOP
            while t < cov0 + LOOKBACK - 1e-9:
                t += HOP
            skip_until = cursor if used_carry else origin - HOP
            while t <= read_end + 1e-6:
                if t > skip_until + 1e-6:
                    a = int(round((t - LOOKBACK - origin) * SR))
                    b = int(round((t - origin) * SR))
                    if a >= 0 and b <= len(samples) and b - a >= int(LOOKBACK * SR) - 2:
                        rows.append(features_at(samples[a:b]))
                        times.append(t)
                t += HOP
            keep_from = read_end - LOOKBACK
            keep_at = int(round((keep_from - origin) * SR))
            if 0 <= keep_at < len(samples):
                carry = samples[keep_at:].copy()
                carry_origin = keep_from
            else:
                carry = np.zeros(0, np.float32)
                carry_origin = None
            cursor += take
        features = np.asarray(rows, dtype=np.float32) if rows else np.zeros((0, 5), np.float32)
        clock = np.asarray(times, dtype=np.float64)
        np.savez_compressed(
            cache,
            t=clock,
            features=features,
            hole_a=np.asarray([a for a, _b in holes], dtype=np.float64),
            hole_b=np.asarray([b for _a, b in holes], dtype=np.float64),
        )
        stored[sid] = {"t": clock, "features": features, "holes": holes}
        print(f"  featured {sid} {len(clock)}", flush=True)
    return stored


def frozen_probability(sessions, pods) -> dict:
    commercial = []
    program = []
    raw = {}
    for sid in v3.TRAIN:
        data = np.load(v3.CACHE / f"{sid}.npz")
        raw[sid] = (data["t"], data["embedding"])
        for index, end in enumerate(data["t"]):
            label = v3.label_of(sid, float(end), pods)
            vector = data["embedding"][index]
            if label == "commercial":
                commercial.append(vector)
            elif label == "program":
                program.append(vector)
    mu_c = np.mean(np.stack(commercial), axis=0)
    mu_p = np.mean(np.stack(program), axis=0)
    mu_c /= np.linalg.norm(mu_c) + 1e-12
    mu_p /= np.linalg.norm(mu_p) + 1e-12
    separation = float(np.dot(mu_c, mu_p))
    scores = []
    labels = []
    for sid in v3.TRAIN:
        clock, embedding = raw[sid]
        for index, end in enumerate(clock):
            label = v3.label_of(sid, float(end), pods)
            if label is None:
                continue
            score = float(embedding[index] @ mu_c - embedding[index] @ mu_p)
            scores.append(score)
            labels.append(1.0 if label == "commercial" else 0.0)
    slope, intercept = v3.fit_scalar(np.asarray(scores), np.asarray(labels))
    series = {}
    high_bin = []
    for sid in sessions:
        data = np.load(v3.CACHE / f"{sid}.npz")
        clock = data["t"]
        score = data["embedding"] @ mu_c - data["embedding"] @ mu_p
        linear = np.clip(slope * score + intercept, -20.0, 20.0)
        probability = 1.0 / (1.0 + np.exp(-linear))
        series[sid] = (clock, probability.astype(np.float64))
        if sid in v3.CALIBRATE:
            for end, prob in zip(clock, probability):
                if 0.9 <= float(prob) <= 1.0:
                    label = v3.label_of(sid, float(end), pods)
                    if label is not None:
                        high_bin.append(1.0 if label == "commercial" else 0.0)
    rate = float(np.mean(high_bin)) if high_bin else -1.0
    if abs(separation - 0.835) > 0.001 or len(high_bin) != 191 or abs(rate - 0.743) > 0.002:
        raise SystemExit(f"frozen CNN14 scalar does not match v3: separation {separation:.4f}, n {len(high_bin)}, rate {rate:.3f}")
    print(f"frozen scalar reproduced n={len(high_bin)} rate={rate:.3f}", flush=True)
    return series


def align_probability(clock: np.ndarray, cnn_t: np.ndarray, cnn_p: np.ndarray) -> np.ndarray:
    out = np.zeros(len(clock), dtype=np.float64)
    if len(cnn_t) == 0:
        return out
    index = np.searchsorted(cnn_t, clock, side="right") - 1
    valid = index >= 0
    out[valid] = cnn_p[index[valid]]
    return out


def lookup(clock: np.ndarray, moment: float) -> int | None:
    index = int(np.searchsorted(clock, moment))
    if index < len(clock) and abs(float(clock[index]) - moment) < 0.05:
        return index
    if index > 0 and abs(float(clock[index - 1]) - moment) < 0.05:
        return index - 1
    return None


def design_matrix(clock: np.ndarray, features: np.ndarray, probability: np.ndarray) -> np.ndarray:
    rows = np.zeros((len(clock), 20 + 1), dtype=np.float64)
    for index, moment in enumerate(clock):
        cursor = 0
        for lag in LAGS:
            found = lookup(clock, float(moment) - lag)
            if found is not None:
                rows[index, cursor:cursor + 5] = features[found]
            cursor += 5
        rows[index, 20] = probability[index]
    return rows


def event_labels(clock: np.ndarray, sid: str, pods) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    starts = [pod["start"] for pod in pods if pod["session"] == sid]
    ends = [pod["end"] for pod in pods if pod["session"] == sid]
    advance = np.zeros(len(clock))
    cut = np.zeros(len(clock))
    returned = np.zeros(len(clock))
    for index, moment in enumerate(clock):
        moment = float(moment)
        if any(moment < start <= moment + 10.0 for start in starts):
            advance[index] = 1.0
        if any(moment - 1.0 <= start < moment for start in starts):
            cut[index] = 1.0
        if any(moment - 1.0 <= end < moment for end in ends):
            returned[index] = 1.0
    return advance, cut, returned


def fit_logistic(features: np.ndarray, labels: np.ndarray) -> np.ndarray | None:
    if labels.sum() < 1 or labels.sum() > len(labels) - 1:
        return None
    count, width = features.shape
    design = np.column_stack([features, np.ones(count)])
    positive = max(float(labels.sum()), 1.0)
    negative = max(float(count - labels.sum()), 1.0)
    weights = np.where(labels > 0.5, 0.5 * count / positive, 0.5 * count / negative)
    beta = np.zeros(width + 1)
    penalty = np.ones(width + 1)
    penalty[-1] = 0.0
    for _ in range(80):
        linear = np.clip(design @ beta, -20.0, 20.0)
        probability = 1.0 / (1.0 + np.exp(-linear))
        curved = weights * probability * (1.0 - probability) + 1e-6
        hessian = design.T @ (design * curved[:, None]) + np.diag(penalty)
        gradient = design.T @ (weights * (probability - labels)) + penalty * beta
        beta -= np.linalg.solve(hessian, gradient)
    return beta


def predict(features: np.ndarray, beta: np.ndarray | None) -> np.ndarray:
    if beta is None or len(features) == 0:
        return np.zeros(len(features))
    design = np.column_stack([features, np.ones(len(features))])
    linear = np.clip(design @ beta, -20.0, 20.0)
    return 1.0 / (1.0 + np.exp(-linear))


def playback(coverage, clock, advance, cut, returned, high_advance, high_cut, high_return):
    cov0, cov1 = coverage
    state, why = "play", "insufficient_evidence"
    spans = []
    cursor = cov0
    for index, moment in enumerate(clock):
        moment = float(moment)
        if moment > cursor:
            spans.append((cursor, moment, state, why))
        if advance[index] >= high_advance or cut[index] >= high_cut:
            state, why = "cover", "departure_evidence"
        elif returned[index] >= high_return:
            state, why = "play", "return_evidence"
        cursor = moment
    if cov1 > cursor:
        spans.append((cursor, cov1, state, why))
    return [(a, b, action, reason) for a, b, action, reason in spans if b > a]


def columns_for(name: str) -> list[int]:
    if name == "snapshot":
        return [20]
    if name == "subsecond":
        return [0, 4]
    if name == "context":
        return [1, 2, 3]
    if name == "history":
        return list(range(20))
    if name == "history_plus_pretrained":
        return list(range(21))
    raise KeyError(name)


def standardize(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = train.mean(axis=0)
    scale = train.std(axis=0)
    scale[scale < 1e-8] = 1.0
    return (train - center) / scale, (other - center) / scale


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    sessions, pods = v3.load_world()
    print("features", flush=True)
    acoustic = extract(sessions)
    holes = {}
    for sid in sessions:
        data = np.load(v3.CACHE / f"{sid}.npz")
        holes[sid] = list(zip(np.array(data["hole_a"]).tolist(), np.array(data["hole_b"]).tolist()))
    thursday = sum(b - a for a, b in holes.get("hush_20261008_205100", []))
    night = sum(b - a for a, b in holes.get("hush_20261011_204300", []))
    if abs(thursday - 240.0) > 0.05 or abs(night - 35.0) > 0.05:
        raise SystemExit(f"read failures do not match v1: thursday {thursday:.3f}, night {night:.3f}")
    for sid, bag in list(acoustic.items()):
        keep = []
        for index, moment in enumerate(bag["t"]):
            start = float(moment) - LOOKBACK
            end = float(moment)
            if any(start < right and end > left for left, right in holes.get(sid, [])):
                continue
            keep.append(index)
        chosen = np.asarray(keep, dtype=int)
        acoustic[sid] = {"t": bag["t"][chosen], "features": bag["features"][chosen], "holes": holes.get(sid, [])}
    print("frozen cnn", flush=True)
    cnn = frozen_probability(sessions, pods)
    designs = {}
    labels = {}
    for sid, bag in acoustic.items():
        probability = align_probability(bag["t"], cnn[sid][0], cnn[sid][1])
        designs[sid] = design_matrix(bag["t"], bag["features"], probability)
        labels[sid] = event_labels(bag["t"], sid, pods)
    train_ids = list(v3.TRAIN) + [v3.REDZONE]
    train_x = np.vstack([designs[sid] for sid in train_ids])
    train_y = [np.concatenate([labels[sid][head] for sid in train_ids]) for head in range(3)]
    counts = {
        "advance": int(train_y[0].sum()),
        "cut": int(train_y[1].sum()),
        "return": int(train_y[2].sum()),
        "rows": int(len(train_x)),
    }
    print("train", counts, flush=True)
    v1_rows = [json.loads(line) for line in v3.V1_DECISIONS.open(encoding="utf-8")]
    rank = {name: index for index, name in enumerate(ABLATION_ORDER)}
    ablations = {}
    chosen_name = None
    chosen_key = None
    for name in ABLATION_ORDER:
        cols = columns_for(name)
        scaled_train, _ = standardize(train_x[:, cols], train_x[:, cols])
        heads = [fit_logistic(scaled_train, train_y[head]) for head in range(3)]
        probabilities = {}
        for sid, matrix in designs.items():
            _train, scaled = standardize(train_x[:, cols], matrix[:, cols])
            probabilities[sid] = tuple(predict(scaled, beta) for beta in heads)
        frontier = []
        best = None
        best_key = None
        for high_advance in THRESHOLDS:
            for high_cut in THRESHOLDS:
                for high_return in THRESHOLDS:
                    action_map = {
                        sid: playback(sessions[sid]["coverage"], acoustic[sid]["t"], *probabilities[sid], high_advance, high_cut, high_return)
                        for sid in v3.CALIBRATE
                    }
                    scored = v3.score_block(v3.CALIBRATE, sessions, pods, holes, action_map)
                    point = {
                        "T_advance": high_advance,
                        "T_cut": high_cut,
                        "T_return": high_return,
                        "commercial_seconds_covered": scored["commercial_seconds_covered"],
                        "program_seconds_covered": scored["program_seconds_covered"],
                        "false_cover_incidents": scored["false_cover_incidents"],
                        "worst_program_interruption_s": scored["worst_program_interruption_s"],
                    }
                    frontier.append(point)
                    if point["program_seconds_covered"] <= PROGRAM_CAP_S:
                        key = (-point["commercial_seconds_covered"], point["false_cover_incidents"], -high_advance, -high_cut, -high_return)
                        if best_key is None or key < best_key:
                            best_key = key
                            best = point
        with_ads = [point for point in frontier if point["commercial_seconds_covered"] > 0]
        least = min(with_ads, key=lambda point: (point["program_seconds_covered"], -point["commercial_seconds_covered"])) if with_ads else None
        ablations[name] = {
            "probabilities": probabilities,
            "selected_on_calibration": best,
            "least_program_point_that_covers_any_commercial": least,
            "frontier_size": len(frontier),
        }
        commercial = 0.0 if best is None else best["commercial_seconds_covered"]
        incidents = 0 if best is None else best["false_cover_incidents"]
        # A point that covers no commercial audio is not an improvement.
        # Ties at zero stay with the preregistered full model.
        key = (0 if commercial > 0 else 1, -commercial, incidents, rank[name])
        if chosen_key is None or key < chosen_key:
            chosen_key = key
            chosen_name = name
        print(f"  {name} under_cap {best}", flush=True)
    winner = ablations[chosen_name]
    point = winner["selected_on_calibration"]
    if point is None or point["commercial_seconds_covered"] <= 0:
        high_advance, high_cut, high_return = 1.1, 1.1, 1.1
        fallback = "play"
        frontier_improved = False
    else:
        high_advance = point["T_advance"]
        high_cut = point["T_cut"]
        high_return = point["T_return"]
        fallback = None
        frontier_improved = True
    action_map = {
        sid: playback(sessions[sid]["coverage"], acoustic[sid]["t"], *winner["probabilities"][sid], high_advance, high_cut, high_return)
        for sid in sessions
    }
    football = [sid for sid, bag in sessions.items() if bag["content"] == "sports" and sid != v3.REDZONE]
    populations = {
        "calibration": v3.CALIBRATE,
        "evaluation": v3.EVAL,
        "redzone": (v3.REDZONE,),
        "football": tuple(football),
    }
    scored = {name: v3.score_block(sids, sessions, pods, holes, action_map) for name, sids in populations.items()}
    v1_map = {sid: v3.v1_actions(sid, sessions[sid]["coverage"], v1_rows) for sid in v3.EVAL}
    v1_eval = v3.score_block(v3.EVAL, sessions, pods, holes, v1_map)
    new_seconds = 0.0
    lost_seconds = 0.0
    by_network = {}
    for sid in v3.EVAL:
        commercial = v3.subtract([(pod["start"], pod["end"]) for pod in pods if pod["session"] == sid], holes.get(sid, []))
        got = v3.intersect(commercial, v3.covers(action_map[sid]))
        had = v3.intersect(commercial, v3.covers(v1_map[sid]))
        gained = sum(b - a for a, b in v3.subtract(got, had))
        dropped = sum(b - a for a, b in v3.subtract(had, got))
        new_seconds += gained
        lost_seconds += dropped
        bucket = by_network.setdefault(sessions[sid]["network"], {"newly_covered_s": 0.0, "lost_s": 0.0})
        bucket["newly_covered_s"] += gained
        bucket["lost_s"] += dropped
    for row in by_network.values():
        row["newly_covered_s"] = round(row["newly_covered_s"], 3)
        row["lost_s"] = round(row["lost_s"], 3)
        row["net_s"] = round(row["newly_covered_s"] - row["lost_s"], 3)
    net = new_seconds - lost_seconds
    positive = [name for name, row in by_network.items() if row["net_s"] > 0]
    gate_met = frontier_improved and net >= COMMERCIAL_GAIN_S and scored["evaluation"]["program_seconds_covered"] <= PROGRAM_CAP_S and len(positive) >= 2
    verdict = "PASS" if gate_met else "FAIL"
    transfers = {}
    for name, ablation in ablations.items():
        selected = ablation["selected_on_calibration"]
        if selected is None or selected["commercial_seconds_covered"] <= 0:
            continue
        trial = {
            sid: playback(
                sessions[sid]["coverage"],
                acoustic[sid]["t"],
                *ablation["probabilities"][sid],
                selected["T_advance"],
                selected["T_cut"],
                selected["T_return"],
            )
            for sid in v3.EVAL
        }
        transfers[name] = v3.score_block(v3.EVAL, sessions, pods, holes, trial)
    payload = {
        "system": "universal_v4_broadcast_sequence",
        "verdict": verdict,
        "frontier_improved_on_calibration": frontier_improved,
        "october_status": "already_inspected_not_blind",
        "fresh_recordings": 0,
        "selected_ablation_on_calibration": chosen_name,
        "selected_thresholds": {"T_advance": high_advance, "T_cut": high_cut, "T_return": high_return, "fallback": fallback},
        "gate": {
            "newly_covered_commercial_s": round(new_seconds, 3),
            "previously_covered_seconds_lost": round(lost_seconds, 3),
            "net_commercial_s_vs_v1": round(net, 3),
            "evaluation_program_seconds_covered": scored["evaluation"]["program_seconds_covered"],
            "false_cover_incidents": scored["evaluation"]["false_cover_incidents"],
            "broadcasters_with_a_net_gain": positive,
            "by_network": by_network,
            "met": gate_met,
        },
        "scored": scored,
        "v1_evaluation": v1_eval,
        "train_positive_seconds": counts,
        "redzone_used_as_training_negative": True,
        "gold_edited": False,
        "adjudication_judgments_applied": 0,
        "ablations": {
            name: {
                "selected_on_calibration": ablation["selected_on_calibration"],
                "least_program_point_that_covers_any_commercial": ablation["least_program_point_that_covers_any_commercial"],
            }
            for name, ablation in ablations.items()
        },
        "october_transfer_not_used_for_selection": transfers,
        "frozen_models_not_retuned": [
            "cnn14_10s_prototype",
            "cnn14_anomaly_distance",
            "mel_logistic",
            "fingerprint_count",
            "micro_dip_18db",
        ],
        "wall_s": round(time.perf_counter() - started, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "ablation": chosen_name, "frontier_improved": frontier_improved, "gate": payload["gate"]}, indent=2))


if __name__ == "__main__":
    main()
