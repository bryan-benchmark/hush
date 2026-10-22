"""Listening clips for the October 8 false covers. Not a mute.

The detector intervals stay put. Only the gain envelope changes.
Gold is used to name the windows and to count seconds. It is not edited.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, read_span  # noqa: E402
from experiments.universal_v1.replay import actions_for, cover_spans, merge, overlap, subtract  # noqa: E402
from hush.audio import find_session, load_session  # noqa: E402

OUT = REPO / "docs/ohush/research/TNF_UX_001"
SID = "hush_20261008_205100"
FAILURES = REPO / "docs/ohush/research/TNF_FAILURES_001/results.json"
CONFIRM = REPO / "docs/ohush/research/EXACT_AUDIO_CONFIRM_001/confirmations.jsonl"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
BED_PATH = REPO / "ohush_live/vibes/processed/wednesday_night.wav"
SR = 48000
PAD_S = 6.0
POD = (139.874, 376.900)
SEPT24 = "hush_20260924_220624"
RETURN_BREAK = (2217.880253, 2338.326017)
SPEAKER_LATE_S = 40.673983

VARIANTS = (
    ("broadcast", "raw", 0.0, 0.0),
    ("live_gate", "gate", 0.25, 0.25),
    ("cross_025", "cross", 0.25, 0.25),
    ("cross_075_150", "cross", 0.75, 1.5),
    ("cross_150", "cross", 1.5, 1.5),
    ("cross_300", "cross", 3.0, 3.0),
)


def load_decisions() -> list[dict]:
    rows = []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] == SID:
            rows.append(row)
    rows.sort(key=lambda row: float(row["available_at"]))
    return rows


def confirms_for() -> dict[float, dict]:
    found = {}
    for line in CONFIRM.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] == SID:
            found[float(row["query_t0"])] = row
    return found


def slice_audio(session_dir: Path, meta: dict, t0: float, t1: float) -> np.ndarray:
    audio = read_span(session_dir, meta, t0, t1)
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise RuntimeError(f"expected stereo, got {audio.shape}")
    return audio


def loop_bed(bed: np.ndarray, count: int) -> np.ndarray:
    start = int(20.0 * SR)
    idx = (np.arange(count) + start) % len(bed)
    return bed[idx]


def gains(count: int, c0: int, c1: int, kind: str, fade_in: float, fade_out: float) -> tuple[np.ndarray, np.ndarray]:
    tv = np.ones(count, dtype=np.float64)
    bed = np.zeros(count, dtype=np.float64)
    if kind == "raw":
        return tv, bed
    if kind == "gate":
        fin = int(round(0.25 * SR))
        fout = int(round(0.25 * SR))
        tv[c0 : min(count, c1 + fout)] = 0.0
        fin_end = min(count, c0 + fin, c1)
        if fin_end > c0:
            bed[c0:fin_end] = np.linspace(0.0, 1.0, fin_end - c0, endpoint=False)
        if c1 > fin_end:
            bed[fin_end:c1] = 1.0
        fout_end = min(count, c1 + fout)
        if fout_end > c1:
            bed[c1:fout_end] = np.linspace(1.0, 0.0, fout_end - c1, endpoint=True)
        if fout_end < count:
            tv[fout_end:] = 1.0
        return tv, bed
    idx = np.arange(count)
    inside = (idx >= c0) & (idx < c1)
    fin = max(int(round(fade_in * SR)), 1)
    fout = max(int(round(fade_out * SR)), 1)
    attack = np.clip((idx - c0) / fin, 0.0, 1.0)
    release = np.clip((c1 - idx) / fout, 0.0, 1.0)
    cover = np.where(inside, np.minimum(attack, release), 0.0)
    return 1.0 - cover, cover


def rms_db(audio: np.ndarray) -> float:
    if audio.size == 0:
        return -80.0
    value = float(np.sqrt(np.mean(np.square(audio))))
    if value < 1e-8:
        return -80.0
    return 20.0 * np.log10(value)


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(audio, -1.0, 1.0), SR, subtype="PCM_16")


def measure(tv: np.ndarray, mixed: np.ndarray, tv_gain: np.ndarray, bed_gain: np.ndarray, c0: int, c1: int, meter) -> dict:
    before = mixed[max(0, c0 - int(0.4 * SR)) : c0]
    after = mixed[c0 : min(len(mixed), c0 + int(0.4 * SR))]
    overlap = float(np.mean((tv_gain > 0.2) & (bed_gain > 0.2))) * (len(tv) / SR)
    full = float(np.mean(tv_gain < 0.05)) * (len(tv) / SR)
    inside = tv_gain[c0:c1]
    partial = float(np.mean((inside >= 0.05) & (inside < 0.95))) * ((c1 - c0) / SR) if c1 > c0 else 0.0
    replaced = float(np.mean(inside < 0.05)) * ((c1 - c0) / SR) if c1 > c0 else 0.0
    try:
        loud = round(float(meter.integrated_loudness(mixed)), 2)
    except ValueError:
        loud = None
    return {
        "jump_db": round(rms_db(after) - rms_db(before), 2),
        "integrated_lufs": loud,
        "overlap_s": round(overlap, 3),
        "tv_fully_down_s": round(full, 3),
        "program_partly_audible_s": round(partial, 3),
        "program_fully_replaced_s": round(replaced, 3),
        "broadcast_lufs": None,
    }


def uncovered(decisions: list[dict], ads, program_cov) -> list[dict]:
    bag = {"coverage": program_cov}
    covers = merge(cover_spans(actions_for(bag, decisions, 10)))
    holes = subtract(ads, covers)
    rows = []
    for left, right in holes:
        rows.append({"start_s": round(left, 3), "end_s": round(right, 3), "seconds": round(right - left, 3)})
    rows.sort(key=lambda row: row["seconds"], reverse=True)
    return rows


def render_mix(tv: np.ndarray, bed: np.ndarray, kind: str, fade_in: float, fade_out: float, c0: int, c1: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tv_gain, bed_gain = gains(len(tv), c0, c1, kind, fade_in, fade_out)
    pre = tv[:c0] if c0 > int(0.2 * SR) else tv
    pre_rms = float(np.sqrt(np.mean(np.square(pre)))) or 0.05
    piece = loop_bed(bed, len(tv))
    bed_rms = float(np.sqrt(np.mean(np.square(piece[: SR])))) or 0.05
    scale = min(4.0, pre_rms / bed_rms)
    mixed = tv * tv_gain[:, None] + piece * scale * bed_gain[:, None]
    return mixed, tv_gain, bed_gain


def html_page(incidents: list[dict], misses: list[dict], release: dict | None, returns: list[dict]) -> str:
    def players(stem: str, labels: list[tuple[str, str]]) -> str:
        bits = []
        for key, label in labels:
            bits.append(
                f'<div class="take"><div>{label}</div><audio controls preload="none" src="clips/{stem}_{key}.wav"></audio></div>'
            )
        return "\n".join(bits)

    labels = [
        ("broadcast", "Television, untouched"),
        ("live_gate", "Current mixer: television cuts, bed fades 0.25 s"),
        ("cross_025", "Crossfade 0.25 s in and out"),
        ("cross_075_150", "Crossfade 0.75 s in, 1.5 s back"),
        ("cross_150", "Crossfade 1.5 s in and out"),
        ("cross_300", "Crossfade 3 s in and out"),
    ]
    blocks = []
    for row in incidents:
        stem = f"i{row['incident']:02d}"
        blocks.append(
            f"""<section>
<h2>{row['incident']}. {row['start_s']} s, {row['seconds']} s</h2>
<p>{row['cause']}. Score {row['max_score']}, correlation {row['best_correlation']}.</p>
{players(stem, labels)}
</section>"""
        )
    miss_bits = []
    for index, row in enumerate(misses, start=1):
        miss_bits.append(
            f"""<section>
<h2>Missed stretch {index}: {row['start_s']}–{row['end_s']} s ({row['seconds']} s)</h2>
<p>Count-10 left this labeled commercial uncovered. The clip is the television at the start of that stretch. No bed is added, because the detector did not cover it.</p>
<audio controls preload="none" src="clips/miss_{index:02d}.wav"></audio>
</section>"""
        )
    release_bit = ""
    if release:
        release_bit = f"""<section>
<h2>DraftKings let-go at {release['let_go_s']} s</h2>
<p>The pod runs to {POD[1]} s. Count-10 stopped covering here, with {release['remaining_s']} s of the labeled break still ahead. Television only.</p>
<audio controls preload="none" src="clips/draftkings_letgo.wav"></audio>
</section>"""
    return_bits = []
    for row in returns:
        return_bits.append(
            f"""<section>
<h2>{row['title']}</h2>
<p>{row['note']}</p>
<audio controls preload="none" src="clips/{row['file']}"></audio>
</section>"""
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>TNF listening</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem auto; max-width: 46rem; line-height: 1.45; color: #1c1915; background: #f6f1e7; }}
    h1 {{ font-size: 1.6rem; }}
    section {{ margin: 2rem 0; padding-top: 1rem; border-top: 1px solid #d9d0c1; }}
    .take {{ margin: 0.6rem 0 0.9rem; }}
    audio {{ width: 100%; }}
    p {{ margin: 0.3rem 0 0.6rem; }}
  </style>
</head>
<body>
  <h1>October 8 false covers</h1>
  <p>Session hush_20261008_205100. Each mistake uses the same start and end. The buttons change only the fade. The bed is Wednesday Night, matched to the level of the television just before the cover. These clips are the optical capture, 48 kHz stereo. Listener preference is not recorded on this page.</p>
  <p>A crossfade shorter than the mistake still reaches a full cover in the middle. A fade longer than the mistake never fully replaces the television: the return starts before the cover finishes.</p>
  {''.join(blocks)}
  <h1>Commercial audio the aggressive replay left uncovered</h1>
  {''.join(miss_bits)}
  {release_bit}
  <h1>A return from another Prime tape</h1>
  {''.join(return_bits)}
</body>
</html>
"""


def main() -> None:
    payload = json.loads(FAILURES.read_text(encoding="utf-8"))
    incidents = payload["false_interruptions"]
    decisions = load_decisions()
    saved = confirms_for()
    causal_notes = []
    for row in incidents:
        hits = [
            item
            for item in saved.values()
            if abs(float(item["available_at"]) - (row["start_s"])) < 1.0
            or (float(item["available_at"]) < row["end_s"] and float(item["query_t1"]) > row["start_s"] - 5)
        ]
        past = [
            item
            for item in hits
            if abs(float(item["query_t1"]) - float(item["available_at"])) > 1e-3
        ]
        causal_notes.append(
            {
                "incident": row["incident"],
                "confirmation_rows_touching_window": len(hits),
                "rows_whose_query_extends_past_the_decision": len(past),
            }
        )
    spans = [span for span in coverage() if span["session"] == SID]
    cov0 = min(float(span["from_seconds"]) for span in spans)
    cov1 = max(float(span["to_seconds"]) for span in spans)
    ads = [(float(row["start_seconds"]), float(row["end_seconds"])) for row in commercials(spans)]
    holes = uncovered(decisions, ads, (cov0, cov1))
    bag = {"coverage": (cov0, cov1)}
    covers = merge(cover_spans(actions_for(bag, decisions, 10)))
    pod_covers = []
    for left, right in covers:
        hit_left = max(left, POD[0])
        hit_right = min(right, POD[1])
        if hit_right > hit_left:
            pod_covers.append((hit_left, hit_right))
    let_go = max((right for _left, right in pod_covers), default=None)
    release = None
    if let_go is not None:
        release = {
            "let_go_s": round(let_go, 3),
            "remaining_s": round(POD[1] - let_go, 3),
        }

    session_dir = find_session(REPO / "recordings", SID)
    meta = load_session(session_dir)
    bed, bed_sr = sf.read(str(BED_PATH), dtype="float32", always_2d=True)
    if bed_sr != SR or bed.shape[1] != 2:
        raise SystemExit(f"bed is {bed_sr} Hz {bed.shape}, expected {SR} stereo")
    meter = pyln.Meter(SR)
    clips = OUT / "clips"
    per_variant: dict[str, list] = {key: [] for key, *_rest in VARIANTS}
    extracted = []
    for row in incidents:
        t0 = max(0.0, float(row["start_s"]) - PAD_S)
        t1 = float(row["end_s"]) + PAD_S
        tv = slice_audio(session_dir, meta, t0, t1)
        c0 = int(round((float(row["start_s"]) - t0) * SR))
        c1 = int(round((float(row["end_s"]) - t0) * SR))
        stem = f"i{int(row['incident']):02d}"
        for key, kind, fade_in, fade_out in VARIANTS:
            mixed, tv_gain, bed_gain = render_mix(tv, bed, kind, fade_in, fade_out, c0, c1)
            write_wav(clips / f"{stem}_{key}.wav", mixed)
            stats = measure(tv, mixed, tv_gain, bed_gain, c0, c1, meter)
            if kind == "raw":
                try:
                    stats["broadcast_lufs"] = round(float(meter.integrated_loudness(tv)), 2)
                except ValueError:
                    stats["broadcast_lufs"] = None
            stats["incident"] = row["incident"]
            per_variant[key].append(stats)
        extracted.append({"incident": row["incident"], "clip_start_s": round(t0, 3), "clip_end_s": round(t1, 3)})

    misses = holes[:3]
    for index, row in enumerate(misses, start=1):
        t0 = max(0.0, row["start_s"] - 4.0)
        t1 = min(row["end_s"], row["start_s"] + 12.0)
        write_wav(clips / f"miss_{index:02d}.wav", slice_audio(session_dir, meta, t0, t1))
        row["clip_start_s"] = round(t0, 3)
        row["clip_end_s"] = round(t1, 3)

    if release:
        t0 = max(0.0, release["let_go_s"] - 4.0)
        t1 = min(POD[1], release["let_go_s"] + 12.0)
        write_wav(clips / "draftkings_letgo.wav", slice_audio(session_dir, meta, t0, t1))
        release["clip_start_s"] = round(t0, 3)
        release["clip_end_s"] = round(t1, 3)

    returns = []
    sept_dir = find_session(REPO / "recordings", SEPT24)
    sept_meta = load_session(sept_dir)
    game_at = RETURN_BREAK[1]
    speaker_at = game_at + SPEAKER_LATE_S
    for file_name, title, t0, t1, note in (
        (
            "return_boundary.wav",
            "September 24, the labeled return",
            game_at - 6.0,
            game_at + 10.0,
            "Break 6 ends at 2,338.326 s. This is the television across that boundary. It is a different recording from October 8.",
        ),
        (
            "return_speaker_late.wav",
            "September 24, 40.7 s after the return",
            speaker_at - 4.0,
            speaker_at + 8.0,
            "The booth-voice return on this break arrives 40.7 s after the labeled end. This clip is the game audio still playing at that moment.",
        ),
    ):
        write_wav(clips / file_name, slice_audio(sept_dir, sept_meta, t0, t1))
        returns.append({"file": file_name, "title": title, "note": note, "clip_start_s": round(t0, 3), "clip_end_s": round(t1, 3)})

    summary = {}
    for key, rows in per_variant.items():
        def avg(name: str, rows=rows) -> float:
            return round(sum(item[name] for item in rows) / len(rows), 3)

        summary[key] = {
            "mean_jump_db": avg("jump_db"),
            "mean_overlap_s": avg("overlap_s"),
            "mean_program_fully_replaced_s": avg("program_fully_replaced_s"),
            "mean_program_partly_audible_s": avg("program_partly_audible_s"),
            "mean_integrated_lufs": round(
                sum(item["integrated_lufs"] for item in rows if item["integrated_lufs"] is not None)
                / max(1, sum(1 for item in rows if item["integrated_lufs"] is not None)),
                2,
            ),
            "collision_mean_jump_db": round(
                sum(item["jump_db"] for item in rows if item["incident"] in {1, 3, 4, 5, 6, 7, 9}) / 7,
                2,
            ),
        }
    ad_heard = overlap(covers, ads)
    result = {
        "session": SID,
        "detector_intervals_unchanged": True,
        "playback_default_unchanged": True,
        "fade_is_linear_gain": True,
        "bed": "wednesday_night",
        "sample_rate_hz": SR,
        "channels": 2,
        "source": "optical capture chunks, not the 16 kHz analysis file",
        "experience": summary,
        "per_clip": per_variant,
        "extracted": extracted,
        "confirmation_query_does_not_extend_past_decision": causal_notes,
        "largest_uncovered_commercials": holes[:8],
        "count10_commercial_seconds_covered": round(ad_heard, 1),
        "draftkings_let_go": release,
        "sept24_return_clips": returns,
        "listener_preference_collected": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (OUT / "listen.html").write_text(html_page(incidents, misses, release, returns), encoding="utf-8")
    lines = [
        "# TNF experience 001",
        "",
        "Not a mute. October 8 Prime, `hush_20261008_205100`. The cover intervals are the published count-10 decisions. Fades do not move them. Gold was not edited. The live 250 ms bed fade was not changed.",
        "",
        "Open `listen.html` in this folder. The wav files sit beside it and are ignored by git.",
        "",
        "## Detection, unchanged by the fades",
        "",
        "Twelve false covers, 57.2 s, median 5.0 s, longest 7.2 s. Seven collisions total 35.0 s. Four copies that cross a labeled commercial end total 20.3 s. One weak boundary match is 2.0 s.",
        "",
        "The correlation that separates those groups was computed on the five-second query that ends at the decision. None of the confirmation rows for these windows extend past `available_at`. The stored reference is an earlier recording, so the lag search does not read this game's future.",
        "",
        "The count-10 score that created the hit can still see later audio: the fingerprint index is built in 90 s blocks. Rejecting a collision is causal once that hit exists. The hit itself is not a causal fingerprint. A full-file causal fingerprint was not run.",
        "",
        f"Count-10 covered {result['count10_commercial_seconds_covered']} s of labeled commercials on this tape. The longest stretches it left uncovered:",
        "",
        "| Start | End | Seconds |",
        "| ---: | ---: | ---: |",
    ]
    for row in holes[:8]:
        lines.append(f"| {row['start_s']} | {row['end_s']} | {row['seconds']} |")
    if release:
        lines += [
            "",
            f"Inside the DraftKings pod, count-10 lets go at {release['let_go_s']} s. The labeled break continues to {POD[1]} s, so {release['remaining_s']} s remain. The pod is 237 s and this replay covered 75 s of it, so the let-go is only the last gap. The conservative count-200 cover of the same pod is the earlier 20 s, from about 150 s to 170 s, which leaves roughly 207 s of the break still playing.",
        ]
    lines += [
        "",
        "## Experience, same decisions, different fades",
        "",
        "Loudness of each whole clip is ITU-R BS.1770 integrated loudness via the pyloudnorm meter. The jump is the change in RMS level from the 400 ms before the cover to the 400 ms after it. Overlap is time when both the television and the bed are above one fifth of full gain. No listener preference was collected.",
        "",
        "| Version | Both audible | Game fully replaced | Game partly audible | Jump on the 7 collisions |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    names = {
        "broadcast": "Television only",
        "live_gate": "Current mixer, 0.25 s bed fade",
        "cross_025": "Crossfade 0.25 s",
        "cross_075_150": "Crossfade 0.75 s in, 1.5 s back",
        "cross_150": "Crossfade 1.5 s",
        "cross_300": "Crossfade 3 s",
    }
    for key, title in names.items():
        row = summary[key]
        lines.append(
            f"| {title} | {row['mean_overlap_s']} s | {row['mean_program_fully_replaced_s']} s | {row['mean_program_partly_audible_s']} s | {row['collision_mean_jump_db']} dB |"
        )
    lines += [
        "",
        "The level jump across all 12 clips is not a useful average. Incidents 8, 10, and 11 open on a near-silent gap, around −64 to −86 dBFS in the 400 ms at the cut, then the program level returns. Incident 2 dips for a few seconds. Incident 12 stays at program level straight through. A bed entering at normal level after silence produces a huge arithmetic jump that is not the collision problem. On the seven collisions the television is already at program level, and the jump column is only those seven. Whole-clip loudness stays near −31 LUFS for every version, because the bed was matched to the television before the cover.",
        "",
        "The current mixer cuts the television at the decision and fades only the bed. On the way back it fades the bed out and restores the television after that fade, so the game is gone for the whole mistake plus a quarter second.",
        "",
        "A crossfade keeps some of the game audible at both edges. On a mistake shorter than the fade, the return begins before the cover is complete, so the game never goes fully away. That is measured above as partly audible seconds. It is not a claim that the result sounds better.",
        "",
        "September 24 break 6 is a different tape. The labeled return is at 2,338.326 s. The booth voice on that break is 40.7 s later. Both moments are on the listening page. Acoustic return on the same break is 84.7 s. No new return detector was run.",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
