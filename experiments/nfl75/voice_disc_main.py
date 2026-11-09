"""Why a Thursday cosine accepts Joe Buck, and whether scoring or another model separates him.

    py -3.13 -m experiments.nfl75.voice_disc_main

Frozen ECAPA at 0.25 is reproduced from the saved embeddings. The margin is
0.15 and is not searched. TitaNet is scored only when its own npz is present.
The pause rule is not built. Gold labels are not rewritten.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from experiments.nfl75.protect_embed import _clip, _latest_labels
from experiments.nfl75.voice_disc import MARGIN, margin_decision, max_over_references, symmetric_snorm
from experiments.nfl75.voice_id import DURATIONS, TNF, enrollment_rows, outcome, probe_bucket
from experiments.nfl75.voice_id_main import OCTOBER, PRIME, _build, _embed_all, _prototype, _record, _scores
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals
from hush.audio import write_mono_wav
from hush.speaker_memory import MATCH_COSINE, SR

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "OHUSH_VOICE_DISCRIMINATION_002"
MODES = (
    ("cross_published", True, False),
    ("cross_clean", True, True),
    ("same_published", False, False),
    ("same_clean", False, True),
)
FOCUS = {"Joe Buck", "Tony Gonzalez", "Andrew Whitworth"}


def _clock(vectors, clip_id, duration):
    return vectors.get(f"{clip_id}|clock|{duration}")


def _groups(refs, vectors, duration):
    grouped = defaultdict(list)
    meta = defaultdict(list)
    for row in refs:
        vector = _clock(vectors, row["id"], duration)
        if vector is None:
            continue
        grouped[row["who"]].append(vector)
        meta[row["who"]].append(row)
    return grouped, meta


def _snorm_scores(probe, prototypes, grouped) -> dict[str, float]:
    scored = {}
    for name, proto in prototypes.items():
        cohort = [vector for other, rows in grouped.items() if other != name for vector in rows]
        if len(cohort) < 2:
            continue
        raw = float(probe @ proto)
        enroll = [float(proto @ vector) for vector in cohort]
        test = [float(probe @ vector) for vector in test_vectors(probe, cohort)]
        scored[name] = symmetric_snorm(raw, enroll, test)
    return scored


def test_vectors(_probe, cohort):
    return cohort


def _commercials() -> dict[str, list[tuple[float, float]]]:
    found = {}
    sessions = {row["session"] for row in _latest_labels()}
    for session in sessions:
        try:
            found[session] = target_commercials(active_intervals(session))
        except Exception:
            found[session] = []
    return found


def _ground(row, commercials) -> str:
    start = float(row["play_start"])
    end = start + float(row["duration"])
    overlap = 0.0
    for left, right in commercials.get(row["session"], []):
        overlap += max(0.0, min(end, right) - max(start, left))
    if overlap >= 0.5:
        return "commercial_speech"
    who = row.get("who") or ""
    if who in TNF:
        return "enrolled_broadcaster"
    if who:
        return "other_broadcaster"
    return "unlabeled"


def _variant_outcome(row, names, accepted, rank1) -> str:
    return outcome(row.get("who") or "", accepted, rank1, probe_bucket(row, names))


def _summarize(rows: list[dict]) -> dict:
    counts = Counter(row["outcome"] for row in rows)
    return {"n": len(rows), "outcomes": dict(counts)}


def _export_wavs(labels) -> None:
    manifest = []
    folder = OUT / "wavs"
    folder.mkdir(parents=True, exist_ok=True)
    for row in labels:
        audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
        for duration in DURATIONS:
            need = int(round(duration * SR))
            path = folder / f"{row['id']}_{int(duration)}.wav"
            write_mono_wav(path, np.asarray(audio[:need], dtype=np.float32), SR)
            manifest.append({"key": f"{row['id']}|clock|{duration}", "wav": str(path.relative_to(REPO))})
        print(f"wav {row['id']}", flush=True)
    (OUT / "titanet_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _load_titanet() -> dict[str, np.ndarray] | None:
    index = OUT / "titanet_embeddings.json"
    cache = OUT / "titanet_embeddings.npz"
    if not index.is_file() or not cache.is_file():
        return None
    saved = json.loads(index.read_text(encoding="utf-8"))
    bundle = np.load(cache)
    return {key: np.asarray(bundle["vector"][i], dtype=np.float32) for i, key in enumerate(saved["keys"])}


def _queue(labels, vectors) -> list[dict]:
    from experiments.nfl75.voice_fn_main import _commercials as _ads
    from experiments.nfl75.voice_fn_main import _load_windows

    marked = []
    for row in labels:
        marked.append((row["session"], float(row["play_start"]), float(row["play_start"]) + float(row["duration"])))
    chosen = []
    for session in PRIME:
        _names, windows = _load_windows(session)
        ads = _ads(session)
        high = []
        low = []
        pair = []
        band = []
        for window in windows:
            mid = (window["start"] + window["end"]) / 2.0
            if any(start - 20.0 <= mid <= end + 20.0 for sess, start, end in marked if sess == session):
                continue
            ordered = sorted(window["scores"].items(), key=lambda item: item[1], reverse=True)
            if not ordered:
                continue
            top, score = ordered[0]
            in_ad = any(left <= mid < right for left, right in ads)
            if in_ad and score >= MATCH_COSINE:
                high.append((mid, window, top, score))
            elif in_ad and score < 0.15:
                low.append((mid, window, top, score))
            elif not in_ad and top in ("Andrew Whitworth", "Tony Gonzalez") and score >= 0.25:
                pair.append((mid, window, top, score))
            elif not in_ad and top == "Kirk Herbstreit" and 0.25 <= score <= 0.50:
                band.append((mid, window, top, score))
        for reason, rows, cap in (
            ("commercial_high_cosine", high, 8),
            ("commercial_low_cosine", low, 8),
            ("program_whitworth_or_gonzalez", pair, 6),
            ("program_herbstreit_in_the_buck_band", band, 6),
        ):
            last = -1e9
            taken = 0
            for mid, window, top, score in rows:
                if mid < last + 150.0:
                    continue
                last = mid
                taken += 1
                chosen.append((session, window["start"], reason, top, score))
                if taken >= cap:
                    break
    queue = []
    for index, (session, start, reason, top, score) in enumerate(chosen, start=1):
        try:
            audio = _clip(session, start, 3.0)
        except Exception as exc:
            print(f"skip queue {session} {start}: {exc}", flush=True)
            continue
        path = OUT / "queue" / session / f"dq{index:04d}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_mono_wav(path, audio, SR)
        queue.append(
            {
                "id": f"dq{index:04d}",
                "split": "diagnose",
                "session": session,
                "wav": str(path.relative_to(REPO)),
                "clip_start_s": round(start, 3),
                "clip_end_s": round(start + 3.0, 3),
                "why_queued": {
                    "reason": reason,
                    "model_top_name": top,
                    "model_cosine": round(float(score), 4),
                    "note": "The model name is why this clip was picked. It is not the label.",
                },
                "label": {
                    "role": None,
                    "speaker": None,
                    "background": None,
                    "overlap": None,
                    "certainty": None,
                    "speech_start_s": None,
                    "speech_end_s": None,
                },
            }
        )
    return queue


def main() -> None:
    if MATCH_COSINE != 0.25 or MARGIN != 0.15:
        raise RuntimeError("refusing a moved line or a searched margin")
    labels = _latest_labels()
    if any(float(row["duration"]) != 3.0 for row in labels):
        raise RuntimeError("an owner mark is not 3 seconds")
    vectors, speech_s = _embed_all(labels)
    commercials = _commercials()
    frozen = []
    variants = []
    atomic = []
    for row in labels:
        if row["session"] not in PRIME and (row.get("who") or "") in ("", *TNF):
            continue
        row = dict(row)
        row["ground"] = _ground(row, commercials)
        for mode, cross, clean in MODES:
            test_session = OCTOBER if (row.get("who") or "") not in TNF else row["session"]
            if (row.get("who") or "") not in TNF and row["session"] in PRIME:
                test_session = row["session"]
            refs = enrollment_rows(labels, test_session, cross_tape=cross, clean=clean, exclude_ids={row["id"]})
            if not refs:
                continue
            for duration in DURATIONS:
                prototypes = _build(labels, vectors, refs, "clock", duration)
                probe = _clock(vectors, row["id"], duration)
                frozen.append(_record(row, "clock", duration, mode, prototypes, probe) | {"ground": row["ground"]})
                if probe is None or not prototypes:
                    continue
                names = set(prototypes)
                raw = _scores(prototypes, probe)
                margin = margin_decision(raw)
                grouped, meta = _groups(refs, vectors, duration)
                pooled = max_over_references(probe, grouped)
                from experiments.nfl75.voice_id import identify

                pooled_decision = identify(pooled)
                snorm = _snorm_scores(probe, prototypes, grouped)
                snorm_order = sorted(snorm.items(), key=lambda item: item[1], reverse=True)
                snorm_top = snorm_order[0][0] if snorm_order else None
                snorm_raw = raw.get(snorm_top) if snorm_top else None
                snorm_accepted = snorm_top if snorm_raw is not None and snorm_raw + 1e-9 >= MATCH_COSINE else None
                variants.append(
                    {
                        "id": row["id"],
                        "session": row["session"],
                        "who": row.get("who"),
                        "condition": row.get("condition"),
                        "ground": row["ground"],
                        "mode": mode,
                        "duration_s": duration,
                        "bucket": probe_bucket(row, names),
                        "frozen_outcome": _variant_outcome(row, names, identify(raw)["accepted"], identify(raw)["rank1"]),
                        "margin_outcome": _variant_outcome(row, names, margin["accepted"], margin["rank1"]),
                        "margin_reason": margin["reason"],
                        "margin": None if margin["margin"] is None else round(margin["margin"], 4),
                        "maxref_outcome": _variant_outcome(row, names, pooled_decision["accepted"], pooled_decision["rank1"]),
                        "maxref_accepted": pooled_decision["accepted"],
                        "maxref_best": None if pooled_decision["best"] is None else round(pooled_decision["best"], 4),
                        "snorm_rank1": snorm_top,
                        "snorm_top": None if not snorm_order else round(snorm_order[0][1], 4),
                        "snorm_second": None if len(snorm_order) < 2 else round(snorm_order[1][1], 4),
                        "snorm_gated_outcome": _variant_outcome(row, names, snorm_accepted, snorm_top),
                        "speech_s": speech_s.get(row["id"]),
                    }
                )
                if duration == 3.0 and mode in ("cross_published", "same_clean") and row.get("who") in FOCUS:
                    nearest = []
                    for name, people in meta.items():
                        for person, vector in zip(people, grouped[name]):
                            nearest.append(
                                {
                                    "id": person["id"],
                                    "who": person["who"],
                                    "condition": person.get("condition"),
                                    "cosine": round(float(probe @ vector), 4),
                                }
                            )
                    nearest.sort(key=lambda item: item["cosine"], reverse=True)
                    atomic.append(
                        {
                            "id": row["id"],
                            "session": row["session"],
                            "mode": mode,
                            "who": row.get("who"),
                            "condition": row.get("condition"),
                            "speech_s": speech_s.get(row["id"]),
                            "prototype": {name: round(value, 4) for name, value in sorted(raw.items(), key=lambda item: item[1], reverse=True)},
                            "margin": None if margin["margin"] is None else round(margin["margin"], 4),
                            "margin_reason": margin["reason"],
                            "nearest_references": nearest[:8],
                        }
                    )
    _check(frozen)
    titanet = _load_titanet()
    titanet_rows = []
    if titanet is not None:
        titanet_rows = _score_foreign(labels, titanet, commercials)
    if not (OUT / "titanet_manifest.json").is_file():
        _export_wavs(labels)
    queue = _queue(labels, vectors)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "frozen.jsonl").write_text("".join(json.dumps(row) + "\n" for row in frozen), encoding="utf-8")
    (OUT / "variants.jsonl").write_text("".join(json.dumps(row) + "\n" for row in variants), encoding="utf-8")
    (OUT / "atomic.jsonl").write_text("".join(json.dumps(row) + "\n" for row in atomic), encoding="utf-8")
    if titanet_rows:
        (OUT / "titanet.jsonl").write_text("".join(json.dumps(row) + "\n" for row in titanet_rows), encoding="utf-8")
    (OUT / "queue.jsonl").write_text("".join(json.dumps(row) + "\n" for row in queue), encoding="utf-8")
    document = {
        "experiment": "OHUSH_VOICE_DISCRIMINATION_002",
        "television_changed": False,
        "pause_rule_built": False,
        "gold_changed": False,
        "line": MATCH_COSINE,
        "margin": MARGIN,
        "margin_was": "declared before the count, not searched",
        "snorm": "symmetric cohort z-score against the other enrolled speakers' reference clips; no accept line was fit to it",
        "titanet": "present" if titanet is not None else "embeddings not ready",
        "ground": dict(Counter(row["ground"] for row in frozen if row["duration_s"] == 3.0 and row["mode"] == "cross_published")),
        "queue": len(queue),
        "untouched_eval": "the next recorded game. Not September 24, not October 8, and not the sealed holdouts.",
    }
    (OUT / "results.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    _print(frozen, variants, titanet_rows)
    print("queue", len(queue), "titanet", document["titanet"])


def _score_foreign(labels, vectors, commercials) -> list[dict]:
    rows = []
    for row in labels:
        if row["session"] not in PRIME and (row.get("who") or "") in ("", *TNF):
            continue
        row = dict(row)
        row["ground"] = _ground(row, commercials)
        for mode, cross, clean in MODES:
            test_session = OCTOBER if (row.get("who") or "") not in TNF else row["session"]
            if (row.get("who") or "") not in TNF and row["session"] in PRIME:
                test_session = row["session"]
            refs = enrollment_rows(labels, test_session, cross_tape=cross, clean=clean, exclude_ids={row["id"]})
            if not refs:
                continue
            for duration in DURATIONS:
                prototypes = {}
                grouped = defaultdict(list)
                for ref in refs:
                    vector = _clock(vectors, ref["id"], duration)
                    if vector is not None:
                        grouped[ref["who"]].append(vector)
                for name, items in grouped.items():
                    prototypes[name] = _prototype(items)
                probe = _clock(vectors, row["id"], duration)
                if probe is None or not prototypes:
                    continue
                raw = _scores(prototypes, probe)
                from experiments.nfl75.voice_id import identify

                decision = identify(raw)
                margin = margin_decision(raw)
                names = set(prototypes)
                rows.append(
                    {
                        "id": row["id"],
                        "session": row["session"],
                        "who": row.get("who"),
                        "condition": row.get("condition"),
                        "ground": row["ground"],
                        "mode": mode,
                        "duration_s": duration,
                        "bucket": probe_bucket(row, names),
                        "frozen_outcome": _variant_outcome(row, names, decision["accepted"], decision["rank1"]),
                        "accepted": decision["accepted"],
                        "best": None if decision["best"] is None else round(decision["best"], 4),
                        "second": None if decision["second"] is None else round(decision["second"], 4),
                        "true_cosine": None if row.get("who") not in raw else round(raw[row["who"]], 4),
                        "margin_outcome": _variant_outcome(row, names, margin["accepted"], margin["rank1"]),
                        "margin": None if margin["margin"] is None else round(margin["margin"], 4),
                    }
                )
    return rows


def _check(frozen: list[dict]) -> None:
    def take(**want):
        return [row for row in frozen if all(row.get(key) == value for key, value in want.items())]

    clear = take(session=OCTOBER, mode="cross_clean", audio="clock", duration_s=3.0, bucket="clear")
    correct = sum(row["outcome"] == "correct" for row in clear)
    wrong = sum(row["outcome"] == "wrong_person" for row in clear)
    if (correct, wrong, len(clear)) != (7, 1, 8):
        raise RuntimeError(f"October clear cross-tape clean was {correct}/{wrong}/{len(clear)}, expected 7/1/8")
    other = take(mode="cross_published", audio="clock", duration_s=3.0, bucket="other_show")
    accepted = sum(row["outcome"] == "false_match" for row in other)
    if (accepted, len(other)) != (25, 74):
        raise RuntimeError(f"other-show accepts were {accepted}/{len(other)}, expected 25/74")
    buck = [row for row in other if row["who"] == "Joe Buck"]
    buck_yes = sum(row["outcome"] == "false_match" for row in buck)
    if (buck_yes, len(buck)) != (17, 19):
        raise RuntimeError(f"Buck accepts were {buck_yes}/{len(buck)}, expected 17/19")
    gonzalez = [
        row
        for row in frozen
        if row["id"] == "e0156" and row["mode"] == "cross_clean" and row["duration_s"] == 3.0 and row["audio"] == "clock"
    ]
    if not gonzalez or gonzalez[0]["outcome"] != "wrong_person" or gonzalez[0]["accepted"] != "Andrew Whitworth":
        raise RuntimeError("e0156 did not reproduce as Whitworth")
    print("reproduced 7/8 clear, 25/74 other-show, 17/19 Buck, e0156 Whitworth", flush=True)


def _print(frozen, variants, titanet) -> None:
    def show(title, rows, key):
        print(title)
        for row in rows:
            print(f"  {row['who'] or row['bucket']} {key} {row}")

    interesting = [
        row
        for row in variants
        if row["duration_s"] == 3.0
        and row["mode"] in ("cross_published", "cross_clean")
        and (row["who"] in FOCUS or row["bucket"] in ("clear", "other_show"))
    ]
    groups = defaultdict(list)
    for row in interesting:
        groups[(row["mode"], row["bucket"], row.get("who") if row["bucket"] == "other_show" else row["bucket"])].append(row)
    for key in sorted(groups, key=lambda item: str(item)):
        rows = groups[key]
        if key[1] == "clear" or key[2] in ("Joe Buck", "Tony Gonzalez"):
            print(
                key,
                "n",
                len(rows),
                "frozen",
                dict(Counter(row["frozen_outcome"] for row in rows)),
                "margin",
                dict(Counter(row["margin_outcome"] for row in rows)),
                "maxref",
                dict(Counter(row["maxref_outcome"] for row in rows)),
                "snorm",
                dict(Counter(row["snorm_gated_outcome"] for row in rows)),
            )


if __name__ == "__main__":
    main()
