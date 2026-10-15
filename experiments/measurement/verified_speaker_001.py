"""Verified-speaker check. Not a mute.

A person already named these spans. This scores the existing ECAPA windows
against those names at the published SpeechBrain cosine line. It does not
fit a threshold, open a holdout, or read booth files.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.ledger import resolve_ledger  # noqa: E402
from hush.speaker_memory import MATCH_COSINE, MIN_SPEECH_S  # noqa: E402

NAMES = REPO / "docs/ohush/research/VOICE_ROSTER_001/names.jsonl"
TRUTH = REPO / "experiments/annotations/truth_events.jsonl"
EXP = REPO / "experiments/exp002"
OUT = REPO / "docs/ohush/research/VERIFIED_SPEAKER_001"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
REDZONE = "hush_20260913_150934"

CANON = {
    "scott hanson": "Scott Hanson",
    "broadcaster - scott hanson redzone": "Scott Hanson",
    "scott hanson redzone": "Scott Hanson",
    "mike tirico": "Mike Tirico",
    "chris collingsworth": "Cris Collinsworth",
    "cris collinsworth": "Cris Collinsworth",
    "joe buck": "Joe Buck",
    "broadaster joe buck - excited, td just scored": "Joe Buck",
    "joe buck after td": "Joe Buck",
    "troy aikman": "Troy Aikman",
    "al michaels": "Al Michaels",
    "kirk herbstreit": "Kirk Herbstreit",
    "herbstreit": "Kirk Herbstreit",
}

AD_MARKERS = (
    "commercial",
    " ad",
    "ad ",
    "shipstation",
    "chevy",
    "honda civic",
    "mcdonald",
    "subway",
    "verizon",
    "arbys",
    "bud light",
    "vyper",
    "operation smile",
    "collars",
    "traitors",
    "political ad",
    "rx ad",
)
NONSPEECH_MARKERS = (
    "crowd",
    "stream lag",
    "theme song",
    "music",
    "whistle",
    "hiking",
    "snap",
    "pause",
    "ambient",
)
PROMO_MARKERS = ("gray area", "outro", "intro music", "upcoming")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canon_name(text: str) -> str | None:
    return CANON.get(" ".join(text.lower().split()))


def span_kind(text: str) -> str:
    name = canon_name(text)
    if name:
        return "announcer"
    lowered = " " + " ".join(text.lower().split()) + " "
    if any(marker in lowered for marker in PROMO_MARKERS):
        return "promo"
    if any(marker in lowered for marker in AD_MARKERS):
        return "ad"
    if any(marker in lowered for marker in NONSPEECH_MARKERS):
        return "nonspeech"
    if text.strip():
        return "other_voice"
    return "blank"


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def latest_names() -> list[dict]:
    rows = []
    for line in NAMES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return [row for row in resolve_ledger(rows, "id") if row.get("role") != "not_broadcaster" or row.get("people")]


def spans_from(row: dict) -> list[dict]:
    duration = float(row.get("duration") or 0)
    people = list(row.get("people") or [])
    if not people and row.get("who"):
        people = [{"start_s": 0, "end_s": duration, "who": row["who"]}]
    full = [
        person
        for person in people
        if float(person["start_s"]) <= 0.05
        and float(person["end_s"]) >= duration - 0.05
        and duration > 0
    ]
    if len(people) > 1 and full:
        full_names = {canon_name(person.get("who") or "") for person in full}
        tighter = [
            person
            for person in people
            if person not in full and canon_name(person.get("who") or "") in full_names
        ]
        if tighter:
            people = [person for person in people if person not in full]
    origin = float(row["play_start"])
    chosen = []
    for person in people:
        text = person.get("who") or ""
        kind = span_kind(text)
        if kind == "blank":
            continue
        chosen.append(
            {
                "clip_id": row["id"],
                "session": row["session"],
                "start": origin + float(person["start_s"]),
                "end": origin + float(person["end_s"]),
                "who": text,
                "name": canon_name(text),
                "kind": kind,
            }
        )
    return chosen


def load_windows(session: str) -> dict:
    path = EXP / session / "speaker_segments.parquet"
    table = pq.read_table(
        path,
        columns=["row_kind", "window_start", "window_end", "embedding"],
    )
    frame = table.to_pandas()
    frame = frame[frame["row_kind"] == "embedding_window"]
    vectors = np.vstack([np.asarray(row, dtype=np.float32) for row in frame["embedding"]])
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return {
        "start": frame["window_start"].to_numpy(dtype=np.float64),
        "end": frame["window_end"].to_numpy(dtype=np.float64),
        "vector": vectors / norms,
        "path": path,
    }


def assign(windows: dict, spans: list[dict]) -> list[dict]:
    """A window belongs to the one span it overlaps by at least a second."""
    owned = []
    starts, ends = windows["start"], windows["end"]
    for index in range(len(starts)):
        best = None
        best_overlap = 0.0
        tied = False
        for span in spans:
            seconds = overlap(starts[index], ends[index], span["start"], span["end"])
            if seconds < MIN_SPEECH_S:
                continue
            if seconds > best_overlap + 1e-6:
                best = span
                best_overlap = seconds
                tied = False
            elif best is not None and abs(seconds - best_overlap) <= 1e-6:
                tied = True
        if best is None or tied:
            continue
        if best["kind"] == "announcer" and best["name"] is None:
            continue
        owned.append({**best, "index": index, "overlap": best_overlap, "vector": windows["vector"][index]})
    return owned


def vectors_of(owned: list[dict]) -> np.ndarray:
    if not owned:
        return np.zeros((0, 192), dtype=np.float32)
    return np.vstack([row["vector"] for row in owned])


def prototype(owned: list[dict]) -> np.ndarray | None:
    stack = vectors_of(owned)
    if len(stack) == 0:
        return None
    mean = stack.mean(axis=0)
    norm = np.linalg.norm(mean)
    if norm == 0:
        return None
    return mean / norm


def cosines(windows: dict, indices: list[int], proto: np.ndarray) -> np.ndarray:
    if not indices:
        return np.array([], dtype=np.float64)
    return windows["vector"][indices] @ proto


def cosines_of(owned: list[dict], proto: np.ndarray) -> np.ndarray:
    stack = vectors_of(owned)
    if len(stack) == 0:
        return np.array([], dtype=np.float64)
    return stack @ proto


def rate(values: np.ndarray) -> dict:
    if len(values) == 0:
        return {"n": 0, "at_or_above_line": 0, "rate": None, "median": None, "minimum": None}
    hits = int(np.sum(values >= MATCH_COSINE))
    return {
        "n": int(len(values)),
        "at_or_above_line": hits,
        "rate": hits / len(values),
        "median": float(np.median(values)),
        "minimum": float(np.min(values)),
    }


def leave_one_clip(owned: list[dict]) -> dict:
    by_clip: dict[str, list[dict]] = {}
    for row in owned:
        by_clip.setdefault(row["clip_id"], []).append(row)
    if len(by_clip) < 2:
        return {"available": False, "reason": "one labeled clip", "clips": len(by_clip), "per_clip": []}
    held = []
    per_clip = []
    for clip_id, rows in by_clip.items():
        others = [row for row in owned if row["clip_id"] != clip_id]
        proto = prototype(others)
        values = cosines_of(rows, proto)
        held.append(values)
        per_clip.append({"clip_id": clip_id, "session": rows[0]["session"], **rate(values)})
    return {"available": True, "clips": len(by_clip), "per_clip": per_clip, **rate(np.concatenate(held))}


def gold_commercials() -> list[dict]:
    rows = []
    for line in TRUTH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    kept = []
    for row in resolve_ledger(rows, "gold_id"):
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if row.get("session") in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        if row.get("event_class") != "commercial" or row.get("desired_action") != "mute":
            continue
        if row.get("confidence") == "unsure":
            continue
        if "start_seconds" not in row:
            continue
        kept.append(
            {
                "session": row["session"],
                "start": float(row["start_seconds"]),
                "end": float(row["end_seconds"]),
            }
        )
    return kept


def commercial_indices(windows: dict, commercials: list[dict]) -> list[int]:
    chosen = []
    for index, (start, end) in enumerate(zip(windows["start"], windows["end"])):
        mid = (start + end) / 2
        if any(item["start"] <= mid < item["end"] for item in commercials):
            chosen.append(index)
    return chosen


def merged_hits(windows: dict, indices: list[int], values: np.ndarray) -> list[tuple[float, float]]:
    spans = [
        (float(windows["start"][index]), float(windows["end"][index]))
        for index, value in zip(indices, values)
        if value >= MATCH_COSINE
    ]
    spans.sort()
    merged: list[list[float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def gap_report(hits: list[tuple[float, float]], horizon: float, origin: float = 0.0) -> dict:
    if not hits:
        return {"first_available_s": None, "n_runs": 0, "median_gap_s": None, "longest_gap_s": None}
    gaps = []
    if hits[0][0] > origin:
        gaps.append(hits[0][0] - origin)
    for previous, following in zip(hits, hits[1:]):
        gaps.append(max(0.0, following[0] - previous[1]))
    if hits[-1][1] < horizon:
        gaps.append(horizon - hits[-1][1])
    covered = sum(end - start for start, end in hits)
    return {
        "first_available_s": hits[0][1],
        "n_runs": len(hits),
        "covered_s": covered,
        "median_gap_s": float(np.median(gaps)) if gaps else 0.0,
        "longest_gap_s": float(np.max(gaps)) if gaps else 0.0,
        "gaps_over_30s": int(sum(gap > 30 for gap in gaps)),
        "gaps_over_60s": int(sum(gap > 60 for gap in gaps)),
    }


def main() -> None:
    assert span_kind("broadcaster - scott hanson redzone") == "announcer"
    assert span_kind("chevy commercial") == "ad"
    assert span_kind("ambient nfl crowd noise") == "nonspeech"
    assert canon_name("chris collingsworth") == "Cris Collinsworth"

    labeled = []
    for row in latest_names():
        if row["session"] in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        labeled.extend(spans_from(row))

    sessions = sorted({row["session"] for row in labeled})
    windows = {session: load_windows(session) for session in sessions}
    owned = {session: assign(windows[session], [row for row in labeled if row["session"] == session]) for session in sessions}
    commercials = gold_commercials()

    people = sorted({row["name"] for row in labeled if row["kind"] == "announcer" and row["name"]})
    people_report = []
    prototypes = {}
    for name in people:
        per_session = {}
        all_owned = []
        for session in sessions:
            rows = [row for row in owned[session] if row["kind"] == "announcer" and row["name"] == name]
            per_session[session] = rows
            all_owned.extend(rows)
        homes = [session for session, rows in per_session.items() if rows]
        proto = prototype(all_owned)
        prototypes[name] = proto
        same = leave_one_clip(all_owned)
        buckets: dict[str, list[np.ndarray]] = {
            "other_announcer": [],
            "other_voice": [],
            "ad": [],
            "promo": [],
            "nonspeech": [],
        }
        gold_values = []
        for session in sessions:
            bank = windows[session]
            grouped: dict[str, list[int]] = {key: [] for key in buckets}
            for row in owned[session]:
                if row["kind"] == "announcer" and row["name"] == name:
                    continue
                if row["kind"] == "announcer":
                    grouped["other_announcer"].append(row["index"])
                elif row["kind"] in grouped:
                    grouped[row["kind"]].append(row["index"])
            for key, indices in grouped.items():
                buckets[key].append(cosines(bank, indices, proto))
            enrollment_idx = {row["index"] for row in per_session[session]}
            gold_idx = [
                index
                for index in commercial_indices(bank, [row for row in commercials if row["session"] == session])
                if index not in enrollment_idx
            ]
            gold_values.append(cosines(bank, gold_idx, proto))
        people_report.append(
            {
                "name": name,
                "sessions": homes,
                "clips": sorted({row["clip_id"] for row in all_owned}),
                "windows": len(all_owned),
                "labeled_seconds": round(sum(row["end"] - row["start"] for row in labeled if row["name"] == name), 3),
                "leave_one_clip": same,
                "other_named_announcers": rate(np.concatenate(buckets["other_announcer"])),
                "other_program_voices": rate(np.concatenate(buckets["other_voice"])),
                "labeled_ads": rate(np.concatenate(buckets["ad"])),
                "labeled_promos": rate(np.concatenate(buckets["promo"])),
                "labeled_nonspeech": rate(np.concatenate(buckets["nonspeech"])),
                "gold_commercial_windows": rate(np.concatenate(gold_values)),
            }
        )

    hanson_rows = [row for row in owned[REDZONE] if row.get("name") == "Scott Hanson"]
    earlier_end = min(row["end"] for row in labeled if row.get("name") == "Scott Hanson")
    earlier_rows = [row for row in hanson_rows if row["end"] <= earlier_end + 1e-6]
    later_rows = [row for row in hanson_rows if row["start"] >= earlier_end]
    early_proto = prototype(earlier_rows)
    later_values = cosines_of(later_rows, early_proto)
    bank = windows[REDZONE]
    after_idx = [index for index, end in enumerate(bank["end"]) if end > earlier_end and index not in {row["index"] for row in earlier_rows}]
    after_values = cosines(bank, after_idx, early_proto)
    mistakes = []
    for session, rows in owned.items():
        for row in rows:
            if row.get("name") == "Scott Hanson":
                continue
            cosine = float(row["vector"] @ prototypes["Scott Hanson"])
            if cosine < MATCH_COSINE:
                continue
            if row["kind"] not in {"announcer", "other_voice", "ad", "promo"}:
                continue
            mistakes.append(
                {
                    "cosine": round(cosine, 3),
                    "kind": row["kind"],
                    "who": row["who"],
                    "clip_id": row["clip_id"],
                    "session": session,
                }
            )
    proto = prototypes["Scott Hanson"]
    enroll_idx = [row["index"] for row in hanson_rows]
    rest_idx = [index for index in range(len(bank["start"])) if index not in set(enroll_idx)]
    rest_values = cosines(bank, rest_idx, proto)
    scan_values = cosines(bank, list(range(len(bank["start"]))), proto)
    hits = merged_hits(bank, list(range(len(bank["start"]))), scan_values)
    rest_hits = merged_hits(bank, rest_idx, rest_values)
    redzone_gold = [row for row in commercials if row["session"] == REDZONE]

    payload = {
        "system": "verified_speaker_001",
        "mute_policy": False,
        "match_cosine": MATCH_COSINE,
        "minimum_overlap_s": MIN_SPEECH_S,
        "threshold_fit": False,
        "holdouts_opened": False,
        "booth_files_read": False,
        "redzone_session": REDZONE,
        "redzone_gold_commercials": len(redzone_gold),
        "redzone_note": "Zero gold commercials describe this recording only. They do not say every RedZone broadcast is ad-free.",
        "people": people_report,
        "hanson_second_example_from_first": rate(later_values),
        "hanson_after_first_example": rate(after_values),
        "hanson_after_first_example_runs": gap_report(
            merged_hits(bank, after_idx, after_values), 7200.0, origin=earlier_end
        ),
        "hanson_first_example_ends_s": earlier_end,
        "hanson_mistakes_at_published_line": mistakes,
        "hanson_rest_of_redzone": rate(rest_values),
        "hanson_identity_including_examples": gap_report(hits, 7200.0),
        "hanson_identity_outside_examples": gap_report(rest_hits, 7200.0),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(render(payload), encoding="utf-8")
    receipts = {
        "names_sha256": sha256(NAMES),
        "truth_sha256": sha256(TRUTH),
        "parquet_sha256": {session: sha256(windows[session]["path"]) for session in sessions},
        "results_sha256": sha256(OUT / "results.json"),
    }
    (OUT / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")
    hanson = next(row for row in people_report if row["name"] == "Scott Hanson")
    print(json.dumps({"people": [row["name"] for row in people_report], "hanson_leave": hanson["leave_one_clip"]}, indent=2))


def fmt_rate(block: dict) -> str:
    if not block["n"]:
        return "no windows"
    median = "n/a" if block["median"] is None else f"{block['median']:.3f}"
    return f"{block['at_or_above_line']}/{block['n']} at or above 0.25, median cosine {median}"


def render(payload: dict) -> str:
    hanson = next(row for row in payload["people"] if row["name"] == "Scott Hanson")
    held = hanson["leave_one_clip"]
    lines = [
        "# Verified speaker check",
        "",
        "Verdict: the two Scott Hanson examples match each other at the published line. That line also matches other announcers, other RedZone voices, and a few ads. It does not yet answer whether OHush recognizes him whenever he speaks.",
        "",
        "This is positive program evidence. It is not a mute. Playback stays PLAY. The match line is the published ECAPA cosine of 0.25. Nothing here was fit to these labels.",
        "",
        "A window counts only when a person-marked span covers at least one second of it. Anonymous cluster ids were not treated as names. The September 13 RedZone recording has "
        f"{payload['redzone_gold_commercials']} gold commercials. That is the truth for this recording. It does not say later RedZone broadcasts are ad-free.",
        "",
        "## Does one Hanson example recognize the other?",
        "",
    ]
    if not held["available"]:
        lines.append("Leave-one-clip-out is unavailable. Fewer than two clips survived.")
    else:
        weakest = min(clip["minimum"] for clip in held["per_clip"])
        lines.append(
            f"Holding out one labeled clip at a time: {fmt_rate(held)}. "
            f"The weakest held-out window is cosine {weakest:.3f}, just above the published line. "
            "Each prototype is the other clip only, so an example is not scored against itself."
        )
        for clip in held["per_clip"]:
            lines.append(f"- {clip['clip_id']}: {fmt_rate(clip)}")
        lines.append(
            f"Using only the earlier example, the later example scores {fmt_rate(payload['hanson_second_example_from_first'])}."
        )
    lines += [
        "",
        "## Does that voice match someone else?",
        "",
        "These are the other spans a person already marked, scored against both Hanson examples. A hit here would call that other audio Scott Hanson. Most of the pool sits far below the line. The crossings are the problem.",
        "",
        f"- Other named announcers: {fmt_rate(hanson['other_named_announcers'])}",
        f"- Other labeled program voices, including the other RedZone booths: {fmt_rate(hanson['other_program_voices'])}",
        f"- Labeled advertisements: {fmt_rate(hanson['labeled_ads'])}",
        f"- Labeled promos and outros: {fmt_rate(hanson['labeled_promos'])}",
        f"- Gold commercial windows in these recordings: {fmt_rate(hanson['gold_commercial_windows'])}",
        "",
        "Crowd, music, and stream-lag marks did not own an embedding window. A window is assigned to the span that covers the most of it, and only when that cover is at least one second.",
        "",
        "Crossings at or above 0.25:",
        "",
    ]
    shown = sorted(payload["hanson_mistakes_at_published_line"], key=lambda row: -row["cosine"])
    grouped: dict[str, list[float]] = {}
    for row in shown:
        grouped.setdefault(row["who"], []).append(row["cosine"])
    for who, scores in grouped.items():
        pretty = ", ".join(f"{score:.3f}" for score in scores)
        lines.append(f"- {who}: {pretty}")
    lines += [
        "",
        "## After the first verified example",
        "",
        "The examples sit in the middle of the recording. A match at the start of the file would be using a voice sample that had not been enrolled yet, so it is not an available identity.",
        "",
        f"The first labeled example ends at {payload['hanson_first_example_ends_s']:.1f} seconds. "
        f"After that, using only that example: {fmt_rate(payload['hanson_after_first_example'])}.",
        "",
    ]
    after = payload["hanson_after_first_example_runs"]
    if after["n_runs"]:
        lines.append(
            f"The next match is available at {after['first_available_s']:.1f} seconds. "
            f"There are {after['n_runs']} runs after enrollment, the median gap is {after['median_gap_s']:.1f} seconds, "
            f"and the longest gap is {after['longest_gap_s']:.1f} seconds. "
            f"{after['gaps_over_30s']} gaps are longer than 30 seconds and {after['gaps_over_60s']} are longer than 60. "
            "A gap means the match went quiet. It does not mean an advertisement started."
        )
    lines += [
        "",
        f"An offline scan that is allowed to use both examples, including time before either example existed, marks {fmt_rate(payload['hanson_rest_of_redzone'])} outside those examples. Those passes are not verified Hanson speech.",
        "",
    ]
    lines += ["", "## The other named announcers", "", "Same published line. One labeled clip cannot be held out.", ""]
    lines.append("| Person | Clips | Windows | Held-out match | Other named announcers | Labeled ads |")
    lines.append("| --- | ---: | ---: | --- | --- | --- |")
    for row in payload["people"]:
        held_text = fmt_rate(row["leave_one_clip"]) if row["leave_one_clip"].get("available") else "one clip"
        lines.append(
            f"| {row['name']} | {len(row['clips'])} | {row['windows']} | {held_text} | {fmt_rate(row['other_named_announcers'])} | {fmt_rate(row['labeled_ads'])} |"
        )
    lines += [
        "",
        "## What this does not decide",
        "",
        "Recognizing a named voice is a reason to remember which program is playing. It is not a reason to mute, and losing the voice is not a reason to infer an ad. This recording cannot test RedZone commercials, because its gold ledger has none. Kirk Herbstreit was typed once and then cleared, so he has no enrollment.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
