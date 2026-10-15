"""Write the 13 Oct research registry, segment-12 evidence, and booth excerpts.

Does not modify gold, Exp001–005, or the frozen Thursday track.
"""

from __future__ import annotations

import hashlib
import json
import wave
from collections import Counter, defaultdict
from pathlib import Path

from experiments.measurement.metrics import Interval, Span, score_timeline

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research"
FROZEN = REPO / "docs/ohush/experiments/LIVE_RECOVERY_001/inputs/session_2026-10-08-tnf"
LIVE = REPO / "ohush_live/sessions/2026-10-08-tnf"
CLIPS = OUT / "booth_excerpts"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def segment(rows: list[dict], key: str) -> list[list[dict]]:
    runs: list[list[dict]] = []
    cur: list[dict] = []
    prev = None
    for row in rows:
        t = float(row.get(key) or 0)
        if prev is not None and t + 1e-6 < prev:
            if cur:
                runs.append(cur)
            cur = []
        cur.append(row)
        prev = t
    if cur:
        runs.append(cur)
    return runs


def wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            if rate <= 0:
                return None
            return handle.getnframes() / float(rate)
    except (wave.Error, EOFError):
        return None


def active_truth(rows: list[dict]) -> list[dict]:
    superseded = {row.get("supersedes") for row in rows if row.get("supersedes")}
    out = []
    for row in rows:
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if row.get("gold_id") in superseded:
            continue
        if "start_seconds" not in row or "end_seconds" not in row:
            continue
        out.append(row)
    return out


def slice_wav(src: Path, start_s: float, dur_s: float, dest: Path) -> dict:
    with wave.open(str(src), "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        total = handle.getnframes()
        start = max(0, int(start_s * rate))
        count = int(dur_s * rate)
        if start >= total:
            raise ValueError(f"{src.name} has no audio at {start_s}")
        count = min(count, total - start)
        handle.setpos(start)
        frames = handle.readframes(count)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return {
        "file": str(dest.relative_to(REPO)),
        "source": str(src.relative_to(REPO)),
        "start_s": round(start / rate, 3),
        "duration_s": round(count / rate, 3),
        "sha256": sha256(dest),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen_track = load_jsonl(FROZEN / "track.jsonl")
    runs = segment(frozen_track, "t")
    wavs = []
    for path in sorted(LIVE.glob("audio_*.wav")):
        wavs.append({"name": path.name, "bytes": path.stat().st_size, "duration_s": wav_duration(path)})

    alignments = []
    for index, run in enumerate(runs):
        t_end = float(run[-1]["t"])
        ranked = []
        for wav in wavs:
            dur = wav["duration_s"]
            if dur is None:
                continue
            ranked.append((abs(dur - t_end), wav["name"], dur))
        ranked.sort()
        near = [item for item in ranked if item[0] <= 2.0]
        alignments.append(
            {
                "track_run": f"run{index:02d}",
                "rows": len(run),
                "t_end": round(t_end, 3),
                "nearest_wav": None if not ranked else ranked[0][1],
                "nearest_abs_delta_s": None if not ranked else round(ranked[0][0], 3),
                "wavs_within_2s": [
                    {"name": name, "duration_s": round(dur, 3), "abs_delta_s": round(delta, 3)}
                    for delta, name, dur in near
                ],
                "status": "unique_duration_candidate"
                if len(near) == 1 and near[0][0] <= 1.5
                else "unresolved",
            }
        )

    decisions = load_jsonl(FROZEN / "decisions.jsonl")
    states = [row for row in decisions if row.get("state") and not row.get("noop")]
    state_runs = segment(states, "t")
    segment_index = 11 if len(state_runs) > 11 else None
    join = None
    if segment_index is not None:
        seg = state_runs[segment_index]
        run29 = runs[29]
        matches = []
        for event in seg:
            if event.get("score_kind") != "return" and event.get("state") != "REPLACEMENT_TO_PROGRAM":
                continue
            t = float(event["t"])
            score = event.get("audio_world_score")
            hit = None
            for row in run29:
                if abs(float(row["t"]) - t) > 0.05:
                    continue
                audio = row.get("audio") or {}
                departure = audio.get("departure") if isinstance(audio, dict) else None
                if score is None or departure is None:
                    continue
                if abs(float(departure) - float(score)) <= 0.002:
                    speaker = row.get("speaker") or {}
                    hit = {
                        "decision_t": t,
                        "track_t": float(row["t"]),
                        "audio_world_score": score,
                        "track_audio_departure": departure,
                        "decision_source": event.get("decision_source"),
                        "state": event.get("state"),
                        "speaker_score": event.get("speaker_score"),
                        "booth_present": speaker.get("booth_present") if isinstance(speaker, dict) else None,
                        "similarity_to_booth": speaker.get("similarity_to_booth") if isinstance(speaker, dict) else None,
                        "cluster_id": speaker.get("cluster_id") if isinstance(speaker, dict) else None,
                        "booth_ids": speaker.get("booth_ids") if isinstance(speaker, dict) else None,
                        "hearing": row.get("hearing"),
                        "machine": row.get("machine"),
                    }
                    break
            matches.append(hit)
        join = {
            "decision_segment_zero_based": segment_index,
            "decision_segment_label_in_handoff": segment_index + 1,
            "track_run": "run29",
            "note": "Joined by timestamp within 0.05s and audio distance within 0.002. Not by segment index.",
            "decision_events": len(seg),
            "matched_return_rows": [row for row in matches if row],
            "unmatched_returns": sum(1 for row in matches if row is None),
        }

    truth_path = REPO / "experiments/annotations/truth_events.jsonl"
    truth = active_truth(load_jsonl(truth_path))
    by_session: dict[str, list[dict]] = defaultdict(list)
    for row in truth:
        by_session[row["session"]].append(row)

    closed = {
        "hush_20260914_212529": (0, 6899, "development", "GOLD_DEV_V1"),
        "hush_20260924_220624": (0, 7600, "replication", "GOLD_REPLICATION_V1"),
        "hush_20260827_135935": (300, 7200, "replication", "GOLD_REPLICATION_V1"),
        "hush_20261007_220650": (20, 11751, "dataset", "GOLD_DATASET_20261013"),
    }
    harness = []
    for session, (start, end, role, manifest) in closed.items():
        intervals = [
            Interval(
                float(row["start_seconds"]),
                float(row["end_seconds"]),
                str(row.get("event_class") or ""),
                str(row.get("desired_action") or ""),
                str(row.get("confidence") or ""),
            )
            for row in by_session.get(session, [])
            if start <= float(row["start_seconds"]) and float(row["end_seconds"]) <= end + 1e-6
        ]
        never = score_timeline((start, end), intervals, [Span(start, end, "program")])
        always = score_timeline((start, end), intervals, [Span(start, end, "covered")])
        harness.append(
            {
                "session": session,
                "role": role,
                "manifest": manifest,
                "coverage": [start, end],
                "active_intervals_inside_coverage": len(intervals),
                "never_cover": never,
                "always_cover": always,
                "live_algorithm": "not scored — no causal replay of ohush_live against this recording",
            }
        )

    booth = json.loads((FROZEN / ".booth.json").read_text(encoding="utf-8"))
    excerpts = []
    source = LIVE / "audio_0044.wav"
    requests = [
        ("c0001", 24.021, "highest similarity for c0001 inside run29"),
        ("c0002", 762.027, "highest similarity for c0002 inside run29"),
        ("c0015", 277.035, "similarity 1.0 for c0015 inside run29; id is in frozen .booth.json and not in that row's booth_ids"),
        ("c0017", 375.040, "only c0017 speech row in run29"),
        ("c0013_t221", 221.013, "suspicious uncover: booth_present true, similarity 0.148, cluster not in booth_ids"),
        ("c0016_t285", 285.013, "high similarity 0.87 on cluster c0016, which is not a trusted id"),
        ("c0010_t621", 621.013, "similarity 0.705 during the one-second human-cover flap"),
    ]
    if source.exists():
        for name, at, why in requests:
            dest = CLIPS / f"run29_{name}.wav"
            meta = slice_wav(source, max(0.0, at - 1.0), 10.0, dest)
            meta["track_run"] = "run29"
            meta["track_t"] = at
            meta["why"] = why
            meta["alignment"] = "duration candidate only: audio_0044.wav is 0.13s from run29 t_end. Not a sample-locked join."
            excerpts.append(meta)

    registry = {
        "written": "2026-10-13",
        "scientific_authority": False,
        "frozen_track_sha256": sha256(FROZEN / "track.jsonl"),
        "frozen_track_rows": len(frozen_track),
        "frozen_track_runs": len(runs),
        "live_track_bytes": (LIVE / "track.jsonl").stat().st_size if (LIVE / "track.jsonl").exists() else None,
        "live_track_runs": len(segment(load_jsonl(LIVE / "track.jsonl"), "t")) if (LIVE / "track.jsonl").exists() else None,
        "note": "The live session folder continued after the frozen audit copy. Defect evidence uses the frozen track. WAV files live only in the session folder.",
        "truth_events_sha256": sha256(truth_path),
        "truth_events_sha256_at_replication_freeze": "6e489a863d765c1333d2759210acccc2d18d239494ce95a1107ab20ec5184249",
        "truth_ledger_hash_matches_freeze": sha256(truth_path)
        == "6e489a863d765c1333d2759210acccc2d18d239494ce95a1107ab20ec5184249",
        "replication_manifest_sha256": sha256(REPO / "experiments/gold/GOLD_REPLICATION_V1.json"),
        "booth_json_ids": booth.get("ids"),
        "thursday_wavs": len(wavs),
        "thursday_alignments": alignments,
        "closed_gold_sessions": list(closed),
        "partial_truth_not_closed": {
            "hush_20260909_213047": len(by_session.get("hush_20260909_213047", [])),
        },
    }
    (OUT / "recording_registry.json").write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    (OUT / "segment12_evidence.json").write_text(json.dumps(join, indent=2) + "\n", encoding="utf-8")
    (OUT / "gold_harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
    (CLIPS / "manifest.json").write_text(
        json.dumps(
            {
                "alignment": "unverified duration candidate",
                "source_wav": "ohush_live/sessions/2026-10-08-tnf/audio_0044.wav",
                "track": "frozen run29",
                "do_not_treat_as_identity_proof": True,
                "excerpts": excerpts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "runs": len(runs),
        "unique_duration_candidates": sum(1 for row in alignments if row["status"] == "unique_duration_candidate"),
        "unresolved": sum(1 for row in alignments if row["status"] == "unresolved"),
        "matched_returns": None if join is None else len(join["matched_return_rows"]),
        "unmatched_returns": None if join is None else join["unmatched_returns"],
        "excerpts": len(excerpts),
        "truth_hash_matches_freeze": registry["truth_ledger_hash_matches_freeze"],
    }, indent=2))


if __name__ == "__main__":
    main()
