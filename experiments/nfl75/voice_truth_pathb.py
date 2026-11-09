"""Score the owner's speech boxes with the frozen ECAPA model.

    py -3.13 -m experiments.nfl75.voice_truth_pathb

Path A is a pipeline window that already existed. Path B is the box the
owner drew. The bounds are retrospective, so this is not a real-time result.
Enrollment and the 0.25 line stay as they were.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.nfl75.protect_embed import (
    MODEL,
    OUT as CACHE,
    _clip,
    _embed_windows,
    _enroll,
    _load_encoder,
    _match,
)
from experiments.nfl75.voice_truth import ALLOW, MARGIN, owner_names
from hush.speaker_memory import MATCH_COSINE

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs" / "ohush" / "research"
NAMES = RESEARCH / "VOICE_ROSTER_001" / "names.jsonl"
QUEUE = RESEARCH / "OHUSH_VOICE_FN_ATOMIC_001" / "queue.jsonl"
DEST = RESEARCH / "OHUSH_VOICE_TRUTH_002"
MIN_BOX_S = 0.4


def _latest_names() -> dict[str, dict]:
    found = {}
    for line in NAMES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            found[row["id"]] = row
    return found


def _queue() -> dict[str, dict]:
    found = {}
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if str(row["id"]).startswith("fn") and row.get("split") == "dev":
                found[row["id"]] = row
    return found


def _owner(person: dict) -> tuple[str, list[str]]:
    text = (person.get("who") or person.get("what") or "").strip()
    names = owner_names(text)
    if len(names) == 1:
        return names[0], names
    if len(names) > 1:
        return "mixed", names
    return "unnamed", []


def _path_a(bundle, names: list[str], start: float, end: float) -> dict:
    win_start = np.asarray(bundle["start"], dtype=np.float64)
    win_end = np.asarray(bundle["end"], dtype=np.float64)
    people = np.asarray(bundle["people"], dtype=np.float64)
    overlap = (win_end > start) & (win_start < end)
    hits = []
    for index in np.flatnonzero(overlap):
        row = people[index]
        finite = [(names[slot], float(row[slot])) for slot in range(len(names)) if row[slot] == row[slot]]
        if len(finite) < 2:
            continue
        finite.sort(key=lambda item: item[1], reverse=True)
        gap = finite[0][1] - finite[1][1]
        hits.append(
            {
                "end_s": round(float(win_end[index]), 3),
                "name": finite[0][0],
                "cosine": round(finite[0][1], 4),
                "second": finite[1][0],
                "gap": round(gap, 4),
                "accepted": finite[0][1] >= MATCH_COSINE,
                "finished_inside": float(win_end[index]) <= end + 1e-6,
            }
        )
    finished = [hit for hit in hits if hit["finished_inside"]]
    return {
        "windows": len(hits),
        "finished_inside": len(finished),
        "best": max(hits, key=lambda hit: hit["cosine"]) if hits else None,
        "best_finished": max(finished, key=lambda hit: hit["cosine"]) if finished else None,
    }


def _one_score(people_row: np.ndarray, names: list[str]) -> dict:
    finite = [(names[slot], float(people_row[slot])) for slot in range(len(names)) if people_row[slot] == people_row[slot]]
    if len(finite) < 2:
        return {"name": None, "cosine": None, "second": None, "gap": None, "accepted": False, "passes_guard": False}
    finite.sort(key=lambda item: item[1], reverse=True)
    gap = finite[0][1] - finite[1][1]
    name, cosine = finite[0]
    return {
        "name": name,
        "cosine": round(cosine, 4),
        "second": finite[1][0],
        "gap": round(gap, 4),
        "accepted": cosine >= MATCH_COSINE,
        "passes_guard": name in ALLOW and cosine >= MATCH_COSINE and gap + 1e-12 >= MARGIN,
    }


def main() -> None:
    labels = _latest_names()
    queue = _queue()
    wanted = [row for row in queue.values() if row["id"] in labels]
    by_session: dict[str, list[dict]] = {}
    for row in wanted:
        by_session.setdefault(row["session"], []).append(row)
    encoder = _load_encoder(MODEL)
    records = []
    for session, rows in by_session.items():
        print("enroll", session, flush=True)
        vectors, ready, _used = _enroll(encoder, session)
        names = [name for name in (
            "Al Michaels",
            "Kirk Herbstreit",
            "Clarissa Thompson",
            "Ryan Fitzpatrick",
            "Andrew Whitworth",
            "Tony Gonzalez",
        ) if name in vectors]
        bundle = np.load(CACHE / f"{session}.npz")
        boxes = []
        for row in rows:
            label = labels[row["id"]]
            origin = float(label["play_start"])
            for person in label["people"]:
                start = float(person["start_s"])
                end = float(person["end_s"])
                if end - start < MIN_BOX_S:
                    owner, names_heard = _owner(person)
                    records.append(
                        {
                            "id": row["id"],
                            "session": session,
                            "abs_start_s": round(origin + start, 3),
                            "abs_end_s": round(origin + end, 3),
                            "owner": owner,
                            "owner_names": names_heard,
                            "owner_text": person.get("who") or person.get("what") or "",
                            "path_b": None,
                            "reason": "box shorter than 0.4s",
                            "realtime": False,
                        }
                    )
                    continue
                boxes.append((row, person, origin + start, origin + end))
        if not boxes:
            continue
        audio_rows = []
        spans = []
        for _row, _person, start, end in boxes:
            audio_rows.append(_clip(session, start, end - start))
            spans.append((0.0, end - start))
        # Each box has its own length, so embed one at a time to keep the window aligned.
        units = []
        for audio, span in zip(audio_rows, spans):
            units.append(_embed_windows(audio, [span], encoder, 1)[0])
        units = np.stack(units)
        ends = np.asarray([end for _row, _person, _start, end in boxes], dtype=np.float64)
        _cosine, people = _match(units, ends, vectors, ready, names)
        for index, (row, person, start, end) in enumerate(boxes):
            owner, names_heard = _owner(person)
            path_b = _one_score(people[index], names)
            path_a = _path_a(bundle, list(json.loads((CACHE / f"{session}.json").read_text(encoding="utf-8"))["names"]), start, end)
            same = owner in names and path_b["accepted"] and path_b["name"] == owner
            records.append(
                {
                    "id": row["id"],
                    "session": session,
                    "abs_start_s": round(start, 3),
                    "abs_end_s": round(end, 3),
                    "seconds": round(end - start, 3),
                    "owner": owner,
                    "owner_names": names_heard,
                    "owner_text": person.get("who") or person.get("what") or "",
                    "path_b": path_b,
                    "path_a": path_a,
                    "human_box_matches_owner": same,
                    "reason": "owner bounds, not a live window",
                    "realtime": False,
                }
            )
            print(row["id"], owner, path_b["name"], path_b["cosine"], "match" if same else "", flush=True)
    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / "pathb.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row) + "\n")
    named = [row for row in records if row["owner"] not in {"unnamed", "mixed"} and row.get("path_b")]
    ads = [row for row in records if row["id"] >= "fn0101" and row.get("path_b") and row["path_b"]["passes_guard"]]
    print(
        "boxes",
        len(records),
        "owner named",
        len(named),
        "agreed",
        sum(1 for row in named if row["human_box_matches_owner"]),
        "ads still passing",
        len(ads),
    )


if __name__ == "__main__":
    main()
