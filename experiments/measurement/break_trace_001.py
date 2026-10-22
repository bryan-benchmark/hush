"""Walk every four-second step and write why it played or covered.

The sign-off watcher is a candidate only. The published count-200
fingerprint is the only cover. Holdouts are not opened.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402
from experiments.measurement.show_roster_001 import SESSION_SHOW  # noqa: E402
from experiments.measurement.verified_speaker_001 import (  # noqa: E402
    assign,
    latest_names,
    load_windows,
    prototype,
    spans_from,
)
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.break_trace import (  # noqa: E402
    BOOTH_LINE,
    MUSIC_HIGH,
    MUSIC_LOW,
    SignOff,
    changes,
    decide,
    pattern,
    sentence,
)
from hush.show_roster import SHOWS  # noqa: E402

OUT = REPO / "docs/ohush/research/BREAK_TRACE_001"
SCORES = REPO / "docs/ohush/research/SONG_TRANSITION_001/scores.jsonl"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
REDZONE = "hush_20260913_150934"


def booth_bank():
    spans = []
    for row in latest_names():
        spans.extend(spans_from(row))
    grouped = defaultdict(list)
    for span in spans:
        grouped[span["session"]].append(span)
    owned = []
    for session, group in grouped.items():
        path = REPO / "experiments/exp002" / session / "speaker_segments.parquet"
        if not path.exists():
            continue
        windows = load_windows(session)
        for row in assign(windows, group):
            name = person_name(row)
            if name:
                owned.append({**row, "person": name})
    built = {}
    for show, names in SHOWS.items():
        for name in names:
            people = [row for row in owned if row["person"] == name]
            proto = prototype(people)
            if proto is not None:
                built.setdefault(show, {})[name] = proto
    return built


def booth_series(session: str, bank: dict):
    path = REPO / "experiments/exp002" / session / "speaker_segments.parquet"
    if not path.exists() or not bank:
        return np.zeros(0), np.zeros(0), []
    windows = load_windows(session)
    names = list(bank)
    matrix = np.vstack([bank[name] for name in names])
    mids = (windows["start"] + windows["end"]) / 2
    scores = windows["vector"] @ matrix.T
    winner = np.argmax(scores, axis=1)
    best = scores[np.arange(len(scores)), winner]
    order = np.argsort(mids)
    return mids[order], best[order], [names[i] for i in winner[order]]


def lookup(mids, scores, names, t0, t1):
    if len(mids) == 0:
        return None, None, False
    left = int(np.searchsorted(mids, t0, side="left"))
    right = int(np.searchsorted(mids, t1, side="left"))
    if right <= left:
        return None, None, False
    slot = left + int(np.argmax(scores[left:right]))
    cosine = float(scores[slot])
    return names[slot], round(cosine, 3), cosine >= BOOTH_LINE


def cover_at():
    grouped = defaultdict(list)
    for line in DECISIONS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            grouped[row["session"]].append(row)
    intervals = defaultdict(list)
    for session, rows in grouped.items():
        rows.sort(key=lambda item: item["available_at"])
        for index, row in enumerate(rows):
            if row["score"] < 200 or row["same_session"]:
                continue
            end = rows[index + 1]["available_at"] if index + 1 < len(rows) else row["available_at"]
            intervals[session].append((row["available_at"], end))
    return intervals


def main():
    catalog = load_catalog()
    banks = booth_bank()
    covers = cover_at()
    by_session = defaultdict(list)
    for line in SCORES.read_text().splitlines():
        if not line:
            continue
        row = json.loads(line)
        if row.get("kind"):
            continue
        by_session[row["session"]].append(row)
    pods = defaultdict(list)
    for row in commercials(coverage()):
        if catalog.get(row["session"], {}).get("content_type") != "sports" or row["session"] == REDZONE:
            continue
        pods[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))
    OUT.mkdir(parents=True, exist_ok=True)
    decisions_path = OUT / "decisions.jsonl"
    events = []
    handle = decisions_path.open("w", encoding="utf-8")
    for session, rows in by_session.items():
        if catalog.get(session, {}).get("content_type") != "sports":
            continue
        rows.sort(key=lambda item: item["t"])
        show = SESSION_SHOW.get(session)
        mids, scores, names = booth_series(session, banks.get(show, {}))
        watcher = SignOff()
        previous = None
        for row in rows:
            t = float(row["t"])
            music = float(row["music"])
            speech = float(row["speech"])
            booth_name, cosine, over = lookup(mids, scores, names, t - 4, t)
            found = changes(previous, music, over)
            music_rose = "music_rose" in found
            mark = watcher.step(t, music, over, music_rose)
            authorized = any(left <= t < right for left, right in covers.get(session, []))
            decision = decide(found, authorized)
            if mark == "confirm":
                decision["candidates"] = list(decision["candidates"]) + ["sign_off_then_booth_under_the_line"]
                if decision["action"] == "play":
                    decision["blocked"] = list(decision["blocked"]) + [
                        "the sign-off sequence is not an authorized mute"
                    ]
            text = sentence(found, decision, booth_name)
            if mark:
                text = f"Sign-off {mark}. " + text
                events.append({"session": session, "t": t, "mark": mark, "show": show})
            state = pattern(music, over)
            handle.write(json.dumps({
                    "session": session,
                    "t": round(t, 3),
                    "show": show,
                    "speech": round(speech, 3),
                    "music": round(music, 3),
                    "booth": booth_name,
                    "cosine": cosine,
                    "booth_over_line": over,
                    "state": state,
                    "changes": found,
                    "sign_off": mark,
                    "action": decision["action"],
                    "authorized_by": decision["authorized_by"],
                    "candidates": decision["candidates"],
                    "blocked": decision["blocked"],
                    "because": text,
                }) + "\n")
            previous = {"music": music, "booth_over_line": over, "pattern": state}
        print("traced", session, flush=True)
    handle.close()
    confirms = [row for row in events if row["mark"] == "confirm"]
    credited = []
    false_confirms = []
    for event in confirms:
        intervals = pods.get(event["session"], [])
        t = event["t"]
        near = [(start, stop) for start, stop in intervals if start - 30 <= t <= start + 5]
        inside = any(start <= t <= stop for start, stop in intervals)
        if near:
            start = min(near, key=lambda item: abs(item[0] - t))[0]
            credited.append({**event, "boundary": round(start, 3), "lead_s": round(start - t, 3)})
        elif not inside:
            false_confirms.append(event)
    football_pods = [item for sid, intervals in pods.items() for item in intervals]
    payload = {
        "action_rule": "play unless universal v1 count 200 is covering",
        "sign_off": "music rises after the booth was over the line in the prior 20s; confirm when the booth is under the line within 30s while music stays high",
        "sign_off_is_a_mute": False,
        "arms": sum(1 for row in events if row["mark"] == "arm"),
        "confirms": len(confirms),
        "football_pods": len(football_pods),
        "pods_with_a_confirm_within_30s_before": len({(row["session"], row["boundary"]) for row in credited}),
        "confirm_lead_s": sorted(row["lead_s"] for row in credited),
        "confirms_during_play": len(false_confirms),
        "decisions": str(decisions_path),
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "confirm_lead_s"}, indent=2))
    leads = payload["confirm_lead_s"]
    if leads:
        print("lead median", leads[len(leads) // 2], "p20", leads[len(leads) // 5], "p80", leads[int(len(leads) * 0.8)])


if __name__ == "__main__":
    main()
