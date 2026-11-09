"""Open-set watchlist test on owner speech boxes.

    py -3.13 -m experiments.nfl75.voice_openset

Gallery is the TNF cast. A probe is either a gallery positive or a known
non-gallery negative. Decision: below the reject line -> unknown; else the
top name. The frozen 0.25 line is reported first. No mute rule changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.nfl75.protect_embed import (
    MODEL,
    _clip,
    _embed_windows,
    _enroll,
    _load_encoder,
    _match,
)
from experiments.nfl75.voice_truth import owner_names
from hush.speaker_memory import MATCH_COSINE
from ohush_live.enroll_floor import CAST

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs" / "ohush" / "research"
NAMES = RESEARCH / "VOICE_ROSTER_001" / "names.jsonl"
QUEUE = RESEARCH / "OHUSH_VOICE_FN_ATOMIC_001" / "queue.jsonl"
ENROLL = RESEARCH / "VOICE_ENROLL_001" / "labels.jsonl"
DEST = RESEARCH / "OHUSH_VOICE_OPENSET_001"
MIN_BOX_S = 0.4
GALLERY = tuple(CAST["tnf"])
LINES = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)

_NEGATIVE_ALIASES = (
    ("billy bob", "Billy Bob Thornton"),
    ("will arnett", "Will Arnett"),
    ("jordan love", "Jordan Love"),
    ("richard sherman", "Richard Sherman"),
    ("joe buck", "Joe Buck"),
)


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


def _negative_names(text: str) -> list[str]:
    low = " ".join(text.lower().split())
    found = []
    for alias, canon in _NEGATIVE_ALIASES:
        if alias in low and canon not in found:
            found.append(canon)
    return found


def _truth(person: dict) -> dict | None:
    """Gallery positive, known negative, or skip."""
    who = (person.get("who") or "").strip()
    what = (person.get("what") or "").strip()
    text = f"{who} {what}".strip()
    low = " ".join(text.lower().split())
    gallery = [name for name in owner_names(text) if name in GALLERY]
    other = _negative_names(text)
    unknown = any(
        marker in low
        for marker in (
            "unknown",
            "not a booth",
            "football player speaking",
            "active player",
        )
    )
    music_only = any(
        marker in low
        for marker in (
            "outro music",
            "intro music",
            "no one speaking",
            "locker room",
            "lockerroom",
            "locekrnoom",
            "injury report",
        )
    ) and not gallery and not other and not unknown

    if music_only:
        return None
    if len(gallery) == 1 and not other and not unknown:
        return {
            "role": "positive",
            "truth_name": gallery[0],
            "truth_kind": "gallery",
            "same_voice_ad": "doing the ad" in low or (gallery[0] and "commercial" in low and gallery[0].lower() in low),
        }
    if len(gallery) > 1:
        return None
    if other and not gallery:
        return {
            "role": "negative",
            "truth_name": other[0] if len(other) == 1 else "mixed_other",
            "truth_kind": "named_other",
            "same_voice_ad": False,
        }
    if unknown and not gallery:
        return {
            "role": "negative",
            "truth_name": "unknown",
            "truth_kind": "unknown_other",
            "same_voice_ad": False,
        }
    return None


def _score_row(people_row: np.ndarray, names: list[str]) -> dict:
    finite = [(names[slot], float(people_row[slot])) for slot in range(len(names)) if people_row[slot] == people_row[slot]]
    if not finite:
        return {
            "top_name": None,
            "cosine": None,
            "second_name": None,
            "second_cosine": None,
            "gap": None,
            "gallery_ready": names,
            "ready_count": 0,
        }
    finite.sort(key=lambda item: item[1], reverse=True)
    top_name, cosine = finite[0]
    if len(finite) == 1:
        return {
            "top_name": top_name,
            "cosine": round(cosine, 4),
            "second_name": None,
            "second_cosine": None,
            "gap": None,
            "gallery_ready": names,
            "ready_count": 1,
        }
    return {
        "top_name": top_name,
        "cosine": round(cosine, 4),
        "second_name": finite[1][0],
        "second_cosine": round(finite[1][1], 4),
        "gap": round(cosine - finite[1][1], 4),
        "gallery_ready": names,
        "ready_count": len(finite),
    }


def _decide(score: dict, line: float) -> dict:
    cosine = score.get("cosine")
    if cosine is None or cosine + 1e-12 < line:
        return {"decision": "unknown", "name": None, "line": line}
    return {"decision": "accept", "name": score["top_name"], "line": line}


def _metrics(rows: list[dict], line: float) -> dict:
    positives = [row for row in rows if row["role"] == "positive"]
    negatives = [row for row in rows if row["role"] == "negative"]
    false_reject = 0
    wrong_id = 0
    true_accept = 0
    for row in positives:
        verdict = _decide(row["score"], line)
        if verdict["decision"] == "unknown":
            false_reject += 1
        elif verdict["name"] == row["truth_name"]:
            true_accept += 1
        else:
            wrong_id += 1
    false_accept = 0
    true_reject = 0
    for row in negatives:
        verdict = _decide(row["score"], line)
        if verdict["decision"] == "accept":
            false_accept += 1
        else:
            true_reject += 1
    n_pos = len(positives)
    n_neg = len(negatives)
    return {
        "line": line,
        "positives": n_pos,
        "negatives": n_neg,
        "false_reject": false_reject,
        "false_reject_rate": None if n_pos == 0 else round(false_reject / n_pos, 4),
        "wrong_id": wrong_id,
        "true_accept": true_accept,
        "id_accuracy_when_accepted": None
        if (true_accept + wrong_id) == 0
        else round(true_accept / (true_accept + wrong_id), 4),
        "false_accept": false_accept,
        "false_accept_rate": None if n_neg == 0 else round(false_accept / n_neg, 4),
        "true_reject": true_reject,
    }


def _buck_negatives() -> list[dict]:
    """Joe Buck clear marks from enrollment: known non-TNF voices."""
    rows = []
    for line in ENROLL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("who") != "Joe Buck" or row.get("condition") != "clear":
            continue
        if float(row.get("duration") or 0) < MIN_BOX_S:
            continue
        rows.append(
            {
                "id": row["id"],
                "session": row["session"],
                "abs_start_s": float(row["play_start"]),
                "abs_end_s": float(row["play_start"]) + float(row["duration"]),
                "owner_text": "Joe Buck clear enroll",
                "role": "negative",
                "truth_name": "Joe Buck",
                "truth_kind": "named_other",
                "same_voice_ad": False,
                "source": "VOICE_ENROLL_001",
            }
        )
    return rows


def _fn_probes() -> list[dict]:
    labels = _latest_names()
    queue = _queue()
    probes = []
    for row in queue.values():
        label = labels.get(row["id"])
        if not label:
            continue
        origin = float(label["play_start"])
        for person in label.get("people") or []:
            start = float(person["start_s"])
            end = float(person["end_s"])
            if end - start < MIN_BOX_S:
                continue
            truth = _truth(person)
            if truth is None:
                continue
            probes.append(
                {
                    "id": row["id"],
                    "session": row["session"],
                    "abs_start_s": origin + start,
                    "abs_end_s": origin + end,
                    "owner_text": person.get("who") or person.get("what") or "",
                    "source": "VOICE_ROSTER_001",
                    **truth,
                }
            )
    return probes


def main() -> None:
    # Joe Buck enroll marks sit on ESPN tapes with no prior TNF gallery.
    # Keep them out of v1; the fn negatives already cover known other voices.
    probes = _fn_probes()
    _ = _buck_negatives  # available for a later cross-show gallery run
    by_session: dict[str, list[dict]] = {}
    for row in probes:
        by_session.setdefault(row["session"], []).append(row)

    encoder = _load_encoder(MODEL)
    scored = []
    for session, rows in sorted(by_session.items()):
        print("enroll", session, "probes", len(rows), flush=True)
        vectors, ready, _used = _enroll(encoder, session)
        names = [name for name in GALLERY if name in vectors]
        units = []
        ends = []
        keep = []
        for row in rows:
            start = float(row["abs_start_s"])
            end = float(row["abs_end_s"])
            audio = _clip(session, start, end - start)
            units.append(_embed_windows(audio, [(0.0, end - start)], encoder, 1)[0])
            ends.append(end)
            keep.append(row)
        if not keep:
            continue
        units = np.stack(units)
        ends_arr = np.asarray(ends, dtype=np.float64)
        _cosine, people = _match(units, ends_arr, vectors, ready, names)
        for index, row in enumerate(keep):
            score = _score_row(people[index], names)
            at_025 = _decide(score, MATCH_COSINE)
            record = {
                **row,
                "abs_start_s": round(float(row["abs_start_s"]), 3),
                "abs_end_s": round(float(row["abs_end_s"]), 3),
                "seconds": round(float(row["abs_end_s"]) - float(row["abs_start_s"]), 3),
                "score": score,
                "at_0_25": at_025,
                "correct_at_0_25": (
                    at_025["decision"] == "accept" and at_025["name"] == row["truth_name"]
                    if row["role"] == "positive"
                    else at_025["decision"] == "unknown"
                ),
                "realtime": False,
            }
            scored.append(record)
            print(
                row["role"],
                row["id"],
                row["truth_name"],
                "->",
                at_025["decision"],
                at_025["name"],
                score["cosine"],
                "ok" if record["correct_at_0_25"] else "MISS",
                flush=True,
            )

    curve = [_metrics(scored, float(line)) for line in LINES]
    frozen = next(item for item in curve if abs(item["line"] - MATCH_COSINE) < 1e-12)
    false_accepts = [
        {
            "id": row["id"],
            "truth_name": row["truth_name"],
            "decision_name": row["at_0_25"]["name"],
            "cosine": row["score"]["cosine"],
            "gap": row["score"]["gap"],
            "owner_text": row["owner_text"],
        }
        for row in scored
        if row["role"] == "negative" and row["at_0_25"]["decision"] == "accept"
    ]
    false_rejects = [
        {
            "id": row["id"],
            "truth_name": row["truth_name"],
            "cosine": row["score"]["cosine"],
            "top_name": row["score"]["top_name"],
            "owner_text": row["owner_text"],
            "same_voice_ad": row["same_voice_ad"],
        }
        for row in scored
        if row["role"] == "positive" and row["at_0_25"]["decision"] == "unknown"
    ]
    same_voice_ads = [
        {
            "id": row["id"],
            "truth_name": row["truth_name"],
            "decision": row["at_0_25"],
            "cosine": row["score"]["cosine"],
            "correct": row["correct_at_0_25"],
            "owner_text": row["owner_text"],
        }
        for row in scored
        if row["same_voice_ad"]
    ]

    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / "openset.jsonl").open("w", encoding="utf-8") as handle:
        for row in scored:
            handle.write(json.dumps(row) + "\n")
    summary = {
        "gallery": list(GALLERY),
        "model": str(MODEL),
        "frozen_line": MATCH_COSINE,
        "realtime": False,
        "n_probes": len(scored),
        "n_positive": sum(1 for row in scored if row["role"] == "positive"),
        "n_negative": sum(1 for row in scored if row["role"] == "negative"),
        "frozen_0_25": frozen,
        "curve": curve,
        "false_accepts_at_0_25": false_accepts,
        "false_rejects_at_0_25": false_rejects,
        "same_voice_ads_at_0_25": same_voice_ads,
        "mute_unchanged": True,
    }
    (DEST / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        "probes",
        len(scored),
        "pos",
        summary["n_positive"],
        "neg",
        summary["n_negative"],
        "FAR",
        frozen["false_accept_rate"],
        "FRR",
        frozen["false_reject_rate"],
        "id_acc",
        frozen["id_accuracy_when_accepted"],
        flush=True,
    )


if __name__ == "__main__":
    main()
