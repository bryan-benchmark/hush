"""Break the new voice matrix into real stretches. Not a mute."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.measurement.show_roster_001 import SESSION_SHOW  # noqa: E402
from experiments.measurement.verified_speaker_001 import load_windows  # noqa: E402
from experiments.measurement.voice_enroll_score_001 import (  # noqa: E402
    CAST,
    KEEP,
    MODEL,
    clip_16k,
    latest_labels,
    prototype,
)
from hush.experiment002 import _embed_windows, _load_encoder  # noqa: E402
from hush.speaker_memory import SR  # noqa: E402

OUT = REPO / "docs/ohush/research/VOICE_ENROLL_001"
LINE = 0.25


def main() -> None:
    labels = [row for row in latest_labels() if row.get("condition") in KEEP and row.get("who")]
    encoder = _load_encoder(MODEL, "cpu")
    grouped: dict[str, list] = defaultdict(list)
    for row in labels:
        audio = clip_16k(row["session"], float(row["play_start"]), float(row["duration"]))
        vector = _embed_windows(audio, [(0.0, len(audio) / SR)], encoder, "cpu", 8)[0]
        grouped[row["who"]].append(vector)
    voices = {name: prototype(vectors) for name, vectors in grouped.items()}

    receipts = [
        json.loads(line)
        for line in (REPO / "docs/ohush/research/START_END_001/receipts.jsonl").read_text().splitlines()
        if line.strip()
    ]
    pods: dict[str, list[tuple[float, float]]] = defaultdict(list)
    network = {}
    for row in receipts:
        if row["network"] in {"NBC", "ESPN", "Prime", "Prime Video"}:
            pods[row["session"]].append((float(row["start"]), float(row["end"])))
            network[row["session"]] = row["network"]
    for session in pods:
        pods[session].sort()

    def in_ad(session: str, t: float) -> bool:
        return any(start <= t <= end for start, end in pods[session])

    def gap_after_last_ad(session: str, t: float) -> float | None:
        ends = [end for _, end in pods[session] if end <= t]
        if not ends:
            return None
        return t - max(ends)

    decisions: dict[str, list[dict]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/BREAK_TRACE_001/decisions.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["session"] in pods:
                decisions[row["session"]].append(row)

    checks = []
    for session, rows in decisions.items():
        rows.sort(key=lambda row: row["t"])
        show = SESSION_SHOW.get(session)
        names = [name for name in CAST.get(show, []) if name in voices]
        if not names:
            continue
        windows = load_windows(session)
        mids = (windows["start"] + windows["end"]) / 2
        order = np.argsort(mids)
        mids = mids[order]
        matrix = np.vstack([voices[name] for name in names])
        raw = windows["vector"][order] @ matrix.T
        times = [float(row["t"]) for row in rows]
        step = []
        for row in rows:
            left = int(np.searchsorted(mids, float(row["t"]) - 4, side="left"))
            right = int(np.searchsorted(mids, float(row["t"]), side="left"))
            if right <= left:
                step.append((None, None))
            else:
                block = raw[left:right]
                flat = int(block.argmax())
                slot, who = divmod(flat, block.shape[1])
                step.append((float(block[slot, who]), names[who]))
        cursor = 0
        for index, row in enumerate(rows):
            t = float(row["t"])
            while times[cursor] < t - 30:
                cursor += 1
            if t - times[cursor] < 26:
                continue
            best = None
            who = None
            for score, name in step[cursor : index + 1]:
                if score is None:
                    continue
                if best is None or score > best:
                    best, who = score, name
            checks.append(
                {
                    "session": session,
                    "network": network[session],
                    "t": t,
                    "ad": in_ad(session, t),
                    "peak": best,
                    "who": who,
                    "speech": row.get("speech"),
                    "music": row.get("music"),
                }
            )

    def stretches(want_ad: bool, under: bool, line: float) -> list[dict]:
        runs = []
        run = None
        for row in checks:
            hit = row["ad"] is want_ad and row["peak"] is not None and ((row["peak"] < line) if under else (row["peak"] >= line))
            if hit and run and run["session"] == row["session"] and row["t"] - run["end"] <= 6:
                run["end"] = row["t"]
                run["n"] += 1
                run["peaks"].append(row["peak"])
                run["whos"].append(row["who"])
                run["speech"].append(row["speech"])
                run["music"].append(row["music"])
            elif hit:
                if run:
                    runs.append(run)
                run = {
                    "session": row["session"],
                    "network": row["network"],
                    "start": row["t"],
                    "end": row["t"],
                    "n": 1,
                    "peaks": [row["peak"]],
                    "whos": [row["who"]],
                    "speech": [row["speech"]],
                    "music": [row["music"]],
                }
            elif run:
                runs.append(run)
                run = None
        if run:
            runs.append(run)
        for run in runs:
            run["seconds"] = run["n"] * 4
            run["peak_max"] = max(run["peaks"])
            speech = [x for x in run["speech"] if x is not None]
            music = [x for x in run["music"] if x is not None]
            run["speech_med"] = sorted(speech)[len(speech) // 2] if speech else None
            run["music_med"] = sorted(music)[len(music) // 2] if music else None
            run["who"] = max(set(run["whos"]), key=run["whos"].count)
        return runs

    game_off = stretches(False, True, LINE)
    ad_on = stretches(True, False, LINE)
    game_off_low = stretches(False, True, 0.10)

    def place(run: dict) -> str:
        last = pods[run["session"]][-1][1]
        first = pods[run["session"]][0][0]
        if run["start"] > last + 30:
            return "after the last labeled commercial"
        if run["end"] < first:
            return "before the first labeled commercial"
        # touches an ad within 8s
        gap = 9e9
        for start, end in pods[run["session"]]:
            if end < run["start"]:
                gap = min(gap, run["start"] - end)
            elif start > run["end"]:
                gap = min(gap, start - run["end"])
            else:
                gap = 0
        if gap <= 8:
            return "sitting on the edge of a labeled commercial"
        return "in the labeled game"

    print(f"GAME SOUND OFF at {LINE}: {len(game_off)} stretches, {sum(r['seconds'] for r in game_off)}s")
    from collections import Counter
    print(Counter(place(r) for r in game_off))
    print("by nearest voice seconds", Counter())
    who_seconds = Counter()
    for run in game_off:
        who_seconds[run["who"]] += run["seconds"]
    print(dict(who_seconds))
    print("\nLONGEST game-off stretches")
    for run in sorted(game_off, key=lambda r: -r["seconds"])[:18]:
        print(
            f"  {run['seconds']:5}s {run['network']:12} {run['start']:.0f}-{run['end']:.0f} "
            f"peak {run['peak_max']:.3f} nearest {run['who']} speech {run['speech_med']:.2f} music {run['music_med']:.2f} "
            f"| {place(run)}"
        )

    print(f"\nGAME SOUND OFF at 0.10: {len(game_off_low)} stretches, {sum(r['seconds'] for r in game_off_low)}s")
    for run in sorted(game_off_low, key=lambda r: -r["seconds"]):
        print(
            f"  {run['seconds']:5}s {run['network']:12} {run['start']:.0f}-{run['end']:.0f} "
            f"peak {run['peak_max']:.3f} nearest {run['who']} | {place(run)}"
        )

    bleed = deep = 0
    bleed_s = deep_s = 0
    names_deep = Counter()
    for run in ad_on:
        # a stretch is bleed if it starts within 30s of an ad start
        starts = [start for start, end in pods[run["session"]] if start - 4 <= run["start"] <= end]
        near_open = any(0 <= run["start"] - start <= 30 for start, _end in pods[run["session"]])
        if near_open and run["seconds"] <= 34:
            bleed += 1
            bleed_s += run["seconds"]
        else:
            deep += 1
            deep_s += run["seconds"]
            names_deep[run["who"]] += run["seconds"]
    print(f"\nAD SOUND ON at {LINE}: {len(ad_on)} stretches, {sum(r['seconds'] for r in ad_on)}s")
    print(f"  first 30s of an ad: {bleed} stretches, {bleed_s}s")
    print(f"  still on deeper in the ad: {deep} stretches, {deep_s}s")
    print("  deeper, by voice", dict(names_deep))

    from collections import Counter

    seconds_by_place = Counter()
    for run in game_off:
        seconds_by_place[place(run)] += run["seconds"]
    print("game-off seconds by place", dict(seconds_by_place))

    import pyarrow.parquet as pq

    words = {}
    for path in (REPO / "experiments/exp005").glob("*/words.parquet"):
        table = pq.read_table(path, columns=["start", "end", "text"])
        words[path.parent.name] = list(
            zip(table.column("start").to_pylist(), table.column("end").to_pylist(), table.column("text").to_pylist())
        )

    def quote(session: str, t0: float, t1: float) -> str:
        rows = words.get(session) or []
        text = " ".join(
            (txt or "").strip()
            for start, end, txt in rows
            if end >= t0 - 1 and start <= t1 + 1
        )
        text = " ".join(text.split())
        return text[:180]

    deep_runs = []
    for run in ad_on:
        near_open = any(0 <= run["start"] - start <= 30 for start, _end in pods[run["session"]])
        if not (near_open and run["seconds"] <= 34):
            deep_runs.append(run)

    print("\nIN THE LABELED GAME, sound off, with words")
    for run in sorted(game_off, key=lambda r: -r["seconds"]):
        if place(run) != "in the labeled game" or run["seconds"] < 28:
            continue
        print(
            f"  {run['seconds']:4}s {run['network']:12} {run['session'][-6:]} {run['start']:.0f}-{run['end']:.0f} "
            f"peak {run['peak_max']:.2f} {run['who']} | {quote(run['session'], run['start'], run['end'])}"
        )

    payload = {
        "game_off": [
            {
                "session": run["session"],
                "network": run["network"],
                "start": run["start"],
                "end": run["end"],
                "seconds": run["seconds"],
                "peak": round(run["peak_max"], 3),
                "who": run["who"],
                "place": place(run),
                "words": quote(run["session"], run["start"], run["end"]),
            }
            for run in game_off
        ],
        "ad_on_deep": [
            {
                "session": run["session"],
                "network": run["network"],
                "start": run["start"],
                "end": run["end"],
                "seconds": run["seconds"],
                "peak": round(run["peak_max"], 3),
                "who": run["who"],
                "words": quote(run["session"], run["start"], run["end"]),
            }
            for run in deep_runs
        ],
    }
    (OUT / "atomic.json").write_text(json.dumps(payload, indent=2) + "\n")
    print("wrote", len(payload["game_off"]), "game-off", len(payload["ad_on_deep"]), "deep ad-on")
    for run in sorted(deep_runs, key=lambda r: -r["seconds"])[:12]:
        print(
            f"  {run['seconds']:4}s {run['network']:12} {run['session'][-6:]} {run['start']:.0f}-{run['end']:.0f} "
            f"peak {run['peak_max']:.2f} {run['who']} | {quote(run['session'], run['start'], run['end'])}"
        )


if __name__ == "__main__":
    main()
