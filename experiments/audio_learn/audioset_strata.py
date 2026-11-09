"""E2: AudioSet Speech/Music/Crowd/Jingle on frozen confusion strata.

Uses the existing AST 5s cache + audioset classifier. Full-tape audit on
FP_desk vs TP_ad, plus raw sample receipts. Frozen / live untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.studio_fit import DESK_SPANS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals
from experiments.nfl75.persist import WINDOW_S
from experiments.nfl75.voice_ad_detect import WATCH, _classify, _top
from tools.gpu_lab.learning_net.data import load_cache

TANDEM = Path(r"C:\OHushData\gpu_lab\audio_learn\tandem_latch")
FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
CLASSIFIER = Path(r"C:\OHushData\gpu_lab\models\ast_audioset_classifier.npz")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts\audioset_strata")
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
SAMPLE_N = 60
SEED = 13

FOCUS = (
    "Speech",
    "Music",
    "Background music",
    "Theme music",
    "Jingle (music)",
    "Crowd",
    "Applause",
    "Cheering",
    "Narration, monologue",
    "Male speech, man speaking",
    "Female speech, woman speaking",
)


def _in(t: float, spans) -> bool:
    return any(a0 <= t < a1 for a0, a1 in spans)


def load_session_probs(session: str, pack: dict, labels: list[str]):
    cached = load_cache(session, WINDOW_S)
    times = np.asarray(cached["t"], dtype=np.float64)
    emb = np.asarray(cached["emb"], dtype=np.float32)
    probs = _classify(emb, pack)
    index = {name: i for i, name in enumerate(labels)}
    watch = {name: probs[:, index[name]].astype(np.float64) for name in FOCUS if name in index}
    return times, probs, watch, labels


def nearest_causal(times: np.ndarray, t: float) -> int:
    i = int(np.searchsorted(times, t, side="right") - 1)
    if i < 0:
        return 0
    return i


def collect(session_data):
    buckets = {"FP_desk": [], "TP_ad": [], "FP_other": [], "TN_prog": []}
    for session in SESSIONS:
        times, probs, watch, labels = session_data[session]
        t_h = np.load(TANDEM / f"{session}_tandem.npz")["t"]
        p = np.load(FROZEN / f"{session}.npz")["p"]
        ads = target_commercials(active_intervals(session))
        desks = DESK_SPANS.get(session, [])
        for i in range(len(t_h)):
            tt = float(t_h[i])
            pp = float(p[i])
            in_ad = _in(tt, ads)
            in_desk = _in(tt, desks)
            if in_desk and pp >= 0.9:
                key = "FP_desk"
            elif in_ad and pp >= 0.9:
                key = "TP_ad"
            elif (not in_ad) and (not in_desk) and pp >= 0.9:
                key = "FP_other"
            elif (not in_ad) and (not in_desk) and pp < 0.5:
                key = "TN_prog"
            else:
                continue
            j = nearest_causal(times, tt)
            row = {
                "session": session,
                "t": tt,
                "frozen_p": pp,
                "ast_t": float(times[j]),
                **{f"p_{name}": float(watch[name][j]) for name in watch},
                "top": _top(probs[j], labels, n=5),
            }
            # composites
            row["p_music_family"] = float(
                max(row.get("p_Music", 0), row.get("p_Background music", 0), row.get("p_Theme music", 0), row.get("p_Jingle (music)", 0))
            )
            row["p_crowd_family"] = float(max(row.get("p_Crowd", 0), row.get("p_Applause", 0), row.get("p_Cheering", 0)))
            row["speech_minus_music"] = float(row.get("p_Speech", 0) - row["p_music_family"])
            row["narration"] = float(row.get("p_Narration, monologue", 0))
            buckets[key].append(row)
    return buckets


def summarize(buckets):
    feats = [
        "p_Speech",
        "p_Music",
        "p_Background music",
        "p_Jingle (music)",
        "p_Crowd",
        "p_music_family",
        "p_crowd_family",
        "speech_minus_music",
        "narration",
        "p_Male speech, man speaking",
        "p_Female speech, woman speaking",
    ]
    summary = {}
    for key, rows in buckets.items():
        summary[key] = {"n": len(rows)}
        if not rows:
            continue
        for feat in feats:
            vals = np.asarray([r[feat] for r in rows], dtype=np.float64)
            summary[key][feat] = {
                "median": round(float(np.median(vals)), 4),
                "p10": round(float(np.percentile(vals, 10)), 4),
                "p90": round(float(np.percentile(vals, 90)), 4),
                "frac_ge_0.20": round(float((vals >= 0.20).mean()), 4),
                "frac_ge_0.35": round(float((vals >= 0.35).mean()), 4),
            }
        print(f"\n{key} n={len(rows)}", flush=True)
        for feat in ("p_Speech", "p_Music", "p_music_family", "p_Jingle (music)", "p_Crowd", "speech_minus_music", "narration"):
            s = summary[key][feat]
            print(
                f"  {feat:22} med={s['median']:.3f} [{s['p10']:.3f},{s['p90']:.3f}] "
                f">=0.20={s['frac_ge_0.20']:.3f} >=0.35={s['frac_ge_0.35']:.3f}",
                flush=True,
            )
    return summary


def rule_audit(buckets):
    rules = {
        "music_family>=0.20": lambda r: r["p_music_family"] >= 0.20,
        "music_family>=0.35": lambda r: r["p_music_family"] >= 0.35,
        "jingle>=0.15": lambda r: r["p_Jingle (music)"] >= 0.15,
        "music>=0.20": lambda r: r["p_Music"] >= 0.20,
        "speech>=0.50": lambda r: r["p_Speech"] >= 0.50,
        "speech_minus_music>=0.30": lambda r: r["speech_minus_music"] >= 0.30,
        "speech_minus_music>=0.45": lambda r: r["speech_minus_music"] >= 0.45,
        "crowd_family>=0.15": lambda r: r["p_crowd_family"] >= 0.15,
        "narration>=0.10": lambda r: r["narration"] >= 0.10,
        # desk-force candidates: high speech, low music
        "speech>=0.40 & music_fam<=0.10": lambda r: r["p_Speech"] >= 0.40 and r["p_music_family"] <= 0.10,
        "speech>=0.35 & music_fam<=0.08": lambda r: r["p_Speech"] >= 0.35 and r["p_music_family"] <= 0.08,
        "speech_minus_music>=0.40 & jingle<=0.05": lambda r: r["speech_minus_music"] >= 0.40 and r["p_Jingle (music)"] <= 0.05,
        "narration>=0.08 & music_fam<=0.15": lambda r: r["narration"] >= 0.08 and r["p_music_family"] <= 0.15,
        # ad-hold candidates: music present while frozen hot
        "music_fam>=0.15 | jingle>=0.10": lambda r: r["p_music_family"] >= 0.15 or r["p_Jingle (music)"] >= 0.10,
    }
    audit = {}
    print("\n=== FULL-TAPE RULE AUDIT ===", flush=True)
    for name, pred in rules.items():
        hits = {}
        for key, rows in buckets.items():
            if not rows:
                hits[key] = {"n": 0, "hit": 0, "frac": None}
                continue
            n_hit = sum(1 for r in rows if pred(r))
            hits[key] = {"n": len(rows), "hit": n_hit, "frac": round(n_hit / len(rows), 4)}
        audit[name] = hits
        print(
            f"{name:45} desk {hits['FP_desk']['frac']} ad {hits['TP_ad']['frac']} "
            f"otherFP {hits['FP_other']['frac']} TN {hits['TN_prog']['frac']}",
            flush=True,
        )
    return audit


def rank_desk_vs_ad(buckets):
    from experiments.audio_learn.crowd_pattern_mine import overlap_score

    desk = buckets["FP_desk"]
    ad = buckets["TP_ad"]
    feats = [
        "p_Speech",
        "p_Music",
        "p_Background music",
        "p_Jingle (music)",
        "p_Crowd",
        "p_music_family",
        "p_crowd_family",
        "speech_minus_music",
        "narration",
        "p_Male speech, man speaking",
        "p_Female speech, woman speaking",
    ]
    scored = []
    for feat in feats:
        sep = overlap_score([r[feat] for r in desk], [r[feat] for r in ad])
        scored.append({"feature": feat, **sep})
    scored.sort(key=lambda r: (-r["accuracy"], r["overlap"]))
    print("\n=== RANKED FP_desk vs TP_ad (full tape) ===", flush=True)
    for row in scored[:12]:
        print(
            f"  {row['feature']:28} acc={row['accuracy']:.3f} thr={row['thr']} "
            f"high={row['high_group']} desk{row['first_range']} ad{row['second_range']} ov={row['overlap']}",
            flush=True,
        )
    return scored


def sample_rows(buckets):
    rng = np.random.default_rng(SEED)
    rows = []
    for key, hops in buckets.items():
        if not hops:
            continue
        idx = rng.choice(len(hops), size=min(SAMPLE_N, len(hops)), replace=False)
        for i in sorted(idx):
            r = dict(hops[i])
            r["stratum"] = key
            rows.append(r)
            top = ",".join(f"{t['class']}:{t['p']:.2f}" for t in r["top"][:3])
            print(
                f"{key:10} {r['session'][-6:]} t={r['t']:8.1f} "
                f"S={r['p_Speech']:.2f} Mfam={r['p_music_family']:.2f} "
                f"J={r['p_Jingle (music)']:.2f} C={r['p_Crowd']:.2f} "
                f"S-M={r['speech_minus_music']:.2f} | {top}",
                flush=True,
            )
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pack = dict(np.load(CLASSIFIER, allow_pickle=False))
    labels = [str(name) for name in pack["labels"].tolist()]
    session_data = {}
    for session in SESSIONS:
        print(f"classify {session}", flush=True)
        session_data[session] = load_session_probs(session, pack, labels)
    print("collect confusion hops", flush=True)
    buckets = collect(session_data)
    summary = summarize(buckets)
    ranked = rank_desk_vs_ad(buckets)
    audit = rule_audit(buckets)
    print("\n=== SAMPLE RAW ===", flush=True)
    samples = sample_rows(buckets)

    # decision-change style: if force-play when speech high & music low while frozen hot
    print("\n=== FORCE-PLAY IMPACT (speech>=0.40 & music_fam<=0.10, frozen already hot) ===", flush=True)
    pred = lambda r: r["p_Speech"] >= 0.40 and r["p_music_family"] <= 0.10
    for key in ("FP_desk", "TP_ad", "FP_other"):
        rows = buckets[key]
        hit = sum(1 for r in rows if pred(r))
        print(f"  {key}: would force-open {hit}/{len(rows)} ({hit/len(rows):.3f})", flush=True)

    payload = {
        "contrast": "audioset_on_frozen_confusion",
        "ast_window_s": WINDOW_S,
        "watch": list(FOCUS),
        "full_counts": {k: len(v) for k, v in buckets.items()},
        "summary": summary,
        "ranked_desk_vs_ad": ranked,
        "rule_audit": audit,
        "sample_rows": samples,
    }
    (OUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (OUT / "sample_rows.jsonl").open("w", encoding="utf-8") as fh:
        for row in samples:
            fh.write(json.dumps(row) + "\n")
    # dump compact full-tape watch vectors for later (not full top lists)
    compact = []
    for key, rows in buckets.items():
        for r in rows:
            compact.append(
                {
                    "stratum": key,
                    "session": r["session"],
                    "t": r["t"],
                    "frozen_p": round(r["frozen_p"], 4),
                    "p_Speech": round(r["p_Speech"], 4),
                    "p_Music": round(r["p_Music"], 4),
                    "p_Background music": round(r["p_Background music"], 4),
                    "p_Jingle (music)": round(r["p_Jingle (music)"], 4),
                    "p_Crowd": round(r["p_Crowd"], 4),
                    "p_music_family": round(r["p_music_family"], 4),
                    "speech_minus_music": round(r["speech_minus_music"], 4),
                    "narration": round(r["narration"], 4),
                }
            )
    with (OUT / "full_watch.jsonl").open("w", encoding="utf-8") as fh:
        for row in compact:
            fh.write(json.dumps(row) + "\n")
    print("wrote", OUT / "result.json", flush=True)
    print("wrote", OUT / "sample_rows.jsonl", flush=True)
    print("wrote", OUT / "full_watch.jsonl", "rows", len(compact), flush=True)


if __name__ == "__main__":
    main()
