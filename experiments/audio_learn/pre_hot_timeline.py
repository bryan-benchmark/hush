"""Why some desk FPs are already hot before the labeled span.

Build second-resolution p timelines for:
  - already-hot desks (Odell, Palmer, Whitworth, welcome, ...)
  - sudden-rise desks (injury, ...)
  - the two ad mid leaks from p_shape (rise rule)
  - a few ordinary ad mids as control

Also pull AudioSet Speech/Music on the same stamps when available.
Raw receipts. Frozen / live untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.studio_fit import DESK_SPANS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals
from experiments.nfl75.persist import WINDOW_S
from experiments.nfl75.voice_ad_detect import _classify
from tools.gpu_lab.learning_net.data import load_cache

FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
CLASSIFIER = Path(r"C:\OHushData\gpu_lab\models\ast_audioset_classifier.npz")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts\pre_hot_timeline")
LOOKBACK_S = 60.0
LOOKAHEAD_S = 15.0

# Named foci from prior receipts
CASES = [
    # already hot at onset (p_start>0.7 @ pre5)
    {"id": "desk_odell", "session": "hush_20260924_220624", "t": 7035.0, "kind": "desk_already_hot", "span": (7035.0, 7095.2)},
    {"id": "desk_palmer", "session": "hush_20260924_220624", "t": 6180.7, "kind": "desk_already_hot", "span": (6180.7, 6207.8)},
    {"id": "desk_whitworth", "session": "hush_20260924_220624", "t": 7406.8, "kind": "desk_soft_hot", "span": (7406.8, 7436.2)},
    {"id": "desk_welcome", "session": "hush_20261008_205100", "t": 3434.0, "kind": "desk_already_hot", "span": (3434.0, 3443.0)},
    {"id": "desk_hl", "session": "hush_20260924_220624", "t": 5026.8, "kind": "desk_already_hot", "span": (5026.8, 5046.5)},
    {"id": "desk_7492", "session": "hush_20260924_220624", "t": 7491.8, "kind": "desk_already_hot", "span": (7491.8, 7515.4)},
    # sudden rise hits
    {"id": "desk_injury", "session": "hush_20260924_220624", "t": 6267.8, "kind": "desk_sudden_rise", "span": (6267.8, 6287.2)},
    {"id": "desk_6315", "session": "hush_20260924_220624", "t": 6315.2, "kind": "desk_sudden_rise", "span": (6315.2, 6336.5)},
    {"id": "desk_6614", "session": "hush_20260924_220624", "t": 6614.0, "kind": "desk_sudden_rise", "span": (6614.0, 6629.2)},
    {"id": "desk_7370", "session": "hush_20260924_220624", "t": 7370.2, "kind": "desk_sudden_rise", "span": (7370.2, 7379.8)},
    {"id": "desk_1750", "session": "hush_20261008_205100", "t": 1749.8, "kind": "desk_sudden_rise", "span": (1749.8, 1760.8)},
    # ad rise leaks from p_shape
    {"id": "ad_leak_1818", "session": "hush_20260924_220624", "t": 1818.69, "kind": "ad_rise_leak", "span": None},
    {"id": "ad_leak_4919", "session": "hush_20261008_205100", "t": 4919.11, "kind": "ad_rise_leak", "span": None},
    # ordinary ad mids (control)
    {"id": "ad_ctrl_chilis", "session": "hush_20260924_220624", "t": 2990.0, "kind": "ad_control", "span": None},
    {"id": "ad_ctrl_amex", "session": "hush_20261008_205100", "t": 3405.0, "kind": "ad_control", "span": None},
    {"id": "ad_ctrl_dk", "session": "hush_20261008_205100", "t": 168.0, "kind": "ad_control", "span": None},
]


def _load_ast(session: str, pack, labels):
    cached = load_cache(session, WINDOW_S)
    times = np.asarray(cached["t"], dtype=np.float64)
    probs = _classify(np.asarray(cached["emb"], dtype=np.float32), pack)
    index = {name: i for i, name in enumerate(labels)}
    return times, probs, index


def _nearest(times: np.ndarray, t: float) -> int:
    i = int(np.searchsorted(times, t, side="right") - 1)
    return max(0, i)


def _gold_at(session: str, t: float, ads, desks) -> str:
    if any(a0 <= t < a1 for a0, a1 in ads):
        return "gold_ad"
    if any(a0 <= t < a1 for a0, a1 in desks):
        return "named_desk"
    return "other_program"


def timeline_for(session: str, t_anchor: float, times, probs, ast_t, ast_p, index, ads, desks):
    left = t_anchor - LOOKBACK_S
    right = t_anchor + LOOKAHEAD_S
    m = (times >= left) & (times <= right)
    t = times[m]
    p = probs[m]
    # downsample to ~0.5s for readable receipt
    if len(t) == 0:
        return []
    step = max(1, int(round(0.5 / float(np.median(np.diff(t))))))
    rows = []
    for i in range(0, len(t), step):
        tt = float(t[i])
        pp = float(p[i])
        j = _nearest(ast_t, tt)
        speech = float(ast_p[j, index["Speech"]])
        music = float(ast_p[j, index["Music"]])
        rows.append(
            {
                "t": round(tt, 2),
                "rel_s": round(tt - t_anchor, 2),
                "frozen_p": round(pp, 4),
                "gold": _gold_at(session, tt, ads, desks),
                "speech": round(speech, 4),
                "music": round(music, 4),
                "speech_minus_music": round(speech - music, 4),
            }
        )
    return rows


def summarize_timeline(points: list[dict], t_anchor: float) -> dict:
    if not points:
        return {}
    arr_p = np.asarray([r["frozen_p"] for r in points])
    rel = np.asarray([r["rel_s"] for r in points])
    # when did p first hit 0.9 in the lookback?
    pre = [(r["rel_s"], r["frozen_p"], r["gold"]) for r in points if r["rel_s"] <= 0]
    first_hot = next((r for r in pre if r[1] >= 0.9), None)
    # longest trailing hot run ending at anchor
    hot_run = 0.0
    for r in reversed(pre):
        if r[1] >= 0.9:
            hot_run = -r[0] if hot_run == 0 else hot_run
            # actually count continuous
        else:
            break
    # better hot-run: from end of pre backwards
    run = 0.0
    prev_t = 0.0
    for r in reversed(pre):
        if r[1] >= 0.9:
            run = prev_t - r[0] if run == 0 else (0.0 - r[0])
            prev_t = r[0]
        else:
            break
    # continuous duration
    run_s = 0.0
    for i in range(len(pre) - 1, -1, -1):
        if pre[i][1] >= 0.9:
            run_s = 0.0 - pre[i][0]
        else:
            break
    gold_at_first_hot = None
    if first_hot:
        gold_at_first_hot = first_hot[2]
        first_hot_rel = first_hot[0]
    else:
        first_hot_rel = None
    # gold composition in last 20s before anchor while p>=0.9
    hot_pre20 = [r for r in points if -20 <= r["rel_s"] <= 0 and r["frozen_p"] >= 0.9]
    gold_counts = {}
    for r in hot_pre20:
        gold_counts[r["gold"]] = gold_counts.get(r["gold"], 0) + 1
    # speech/music at -30,-10,-2,0,+5
    def at(rel):
        if not points:
            return None
        i = int(np.argmin(np.abs(rel - np.asarray([r["rel_s"] for r in points]))))
        r = points[i]
        return {
            "rel_s": r["rel_s"],
            "p": r["frozen_p"],
            "gold": r["gold"],
            "speech": r["speech"],
            "music": r["music"],
            "sm": r["speech_minus_music"],
        }

    return {
        "p_at_anchor": round(float(arr_p[np.argmin(np.abs(rel))]), 4),
        "first_hot_rel_s": first_hot_rel,
        "gold_when_first_hot": gold_at_first_hot,
        "hot_run_before_anchor_s": round(run_s, 2),
        "hot_pre20_gold_counts": gold_counts,
        "snap": {str(k): at(k) for k in (-30, -20, -10, -5, -2, 0, 5, 10)},
        "p_mean_pre60": round(float(np.mean([r["frozen_p"] for r in points if r["rel_s"] <= 0])), 4),
        "music_mean_pre20_hot": round(
            float(np.mean([r["music"] for r in hot_pre20])), 4
        )
        if hot_pre20
        else None,
        "speech_mean_pre20_hot": round(
            float(np.mean([r["speech"] for r in hot_pre20])), 4
        )
        if hot_pre20
        else None,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pack = dict(np.load(CLASSIFIER, allow_pickle=False))
    labels = [str(x) for x in pack["labels"].tolist()]
    cache = {}
    cases_out = []
    for case in CASES:
        session = case["session"]
        if session not in cache:
            times, probs = np.load(FROZEN / f"{session}.npz")["t"], np.load(FROZEN / f"{session}.npz")["p"]
            times = times.astype(np.float64)
            probs = probs.astype(np.float64)
            ast_t, ast_p, index = _load_ast(session, pack, labels)
            ads = target_commercials(active_intervals(session))
            desks = DESK_SPANS.get(session, [])
            cache[session] = (times, probs, ast_t, ast_p, index, ads, desks)
        times, probs, ast_t, ast_p, index, ads, desks = cache[session]
        points = timeline_for(session, case["t"], times, probs, ast_t, ast_p, index, ads, desks)
        summary = summarize_timeline(points, case["t"])
        # preceding gold ad end if any
        prev_ad = None
        for a0, a1 in ads:
            if a1 <= case["t"] and case["t"] - a1 <= 90:
                if prev_ad is None or a1 > prev_ad[1]:
                    prev_ad = (a0, a1)
        rec = {
            **case,
            "prev_gold_ad": None
            if prev_ad is None
            else {"start": prev_ad[0], "end": prev_ad[1], "gap_s": round(case["t"] - prev_ad[1], 2)},
            "summary": summary,
            "timeline": points,
        }
        cases_out.append(rec)
        s = summary
        print(
            f"{case['id']:18} kind={case['kind']:18} "
            f"first_hot={s.get('first_hot_rel_s')} ({s.get('gold_when_first_hot')}) "
            f"hot_run={s.get('hot_run_before_anchor_s')}s "
            f"prev_ad_gap={None if prev_ad is None else round(case['t']-prev_ad[1],1)} "
            f"pre20_gold={s.get('hot_pre20_gold_counts')} "
            f"snap-10={s['snap'].get('-10')} snap0={s['snap'].get('0')}",
            flush=True,
        )

    # pattern table: already_hot desks — was first_hot inside a gold ad?
    print("\n=== PATTERN: already-hot desks — origin of heat ===", flush=True)
    for rec in cases_out:
        if "desk" not in rec["kind"]:
            continue
        s = rec["summary"]
        print(
            f"  {rec['id']:18} first_hot_at {s.get('first_hot_rel_s')} on {s.get('gold_when_first_hot')} "
            f"| gap_from_prev_ad={None if rec['prev_gold_ad'] is None else rec['prev_gold_ad']['gap_s']} "
            f"| hot_run={s.get('hot_run_before_anchor_s')}s",
            flush=True,
        )

    print("\n=== PATTERN: ad rise leaks vs ad controls @ -10/0 ===", flush=True)
    for rec in cases_out:
        if rec["kind"] not in ("ad_rise_leak", "ad_control"):
            continue
        s = rec["summary"]
        print(
            f"  {rec['id']:18} first_hot={s.get('first_hot_rel_s')} "
            f"hot_run={s.get('hot_run_before_anchor_s')} "
            f"-10={s['snap'].get('-10')} 0={s['snap'].get('0')}",
            flush=True,
        )

    # cross-case: does already_hot mean "carry from prior gold ad"?
    already = [r for r in cases_out if r["kind"] == "desk_already_hot"]
    sudden = [r for r in cases_out if r["kind"] == "desk_sudden_rise"]
    carry = sum(
        1
        for r in already
        if r["summary"].get("gold_when_first_hot") == "gold_ad"
        or (r["prev_gold_ad"] and r["prev_gold_ad"]["gap_s"] <= 5 and r["summary"].get("hot_run_before_anchor_s", 0) >= 5)
    )
    print(
        f"\ncarry_score already_hot: {carry}/{len(already)} look like ad-carry or continuous hot from ad",
        flush=True,
    )
    sudden_from_prog = sum(1 for r in sudden if r["summary"].get("gold_when_first_hot") in (None, "other_program", "named_desk"))
    print(f"sudden_rise first_hot on program/desk/none: {sudden_from_prog}/{len(sudden)}", flush=True)

    payload = {"lookback_s": LOOKBACK_S, "lookahead_s": LOOKAHEAD_S, "cases": cases_out}
    (OUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # also write one jsonl point stream
    with (OUT / "points.jsonl").open("w", encoding="utf-8") as fh:
        for rec in cases_out:
            for pt in rec["timeline"]:
                fh.write(json.dumps({"case": rec["id"], "kind": rec["kind"], "session": rec["session"], **pt}) + "\n")
    print("wrote", OUT / "result.json", flush=True)
    print("wrote", OUT / "points.jsonl", flush=True)


if __name__ == "__main__":
    main()
