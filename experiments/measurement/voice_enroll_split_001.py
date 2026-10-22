"""Split host-read ads out of the voice matrix. Not a mute.

A labeled commercial where the saved broadcaster is actually talking is a
second pile. It is not a game second and it is not a narrator who only
scores like the booth.
"""

from __future__ import annotations

import json
import re
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
    LINES,
    MODEL,
    clip_16k,
    latest_labels,
    prototype,
)
from hush.experiment002 import _embed_windows, _load_encoder  # noqa: E402
from hush.speaker_memory import EMBEDDING_MODEL_ID, SR  # noqa: E402

OUT = REPO / "docs/ohush/research/VOICE_ENROLL_001"

PRODUCT = re.compile(
    r"honda|chevy|chevrolet|nissan|toyota|tiktok|netflix|chipotle|mcdonald|nugget|"
    r"wi-?fi|xfinity|insurance|cash back|iphone|t-mobile|best buy|pixel|"
    r"limited time|a1c|billionaire|prescription|hyundai|geico|allstate|"
    r"interest on|price guarantee|drive 20|for just|percent cash|3 %|"
    r"chicken|sandwich|internet|download",
    re.I,
)
BOOTH = re.compile(
    r"first down|touchdown|interception|we'll be right back|we will be right back|"
    r"welcome back|thursday night|sunday night|monday night|peacock|"
    r"end zone|quarterback|timeout|field goal|join us|brought to you|"
    r"thanks, kirk|see you sunday",
    re.I,
)


def words_by_session() -> dict[str, list[tuple[float, float, str]]]:
    import pyarrow.parquet as pq

    found = {}
    for path in (REPO / "experiments/exp005").glob("*/words.parquet"):
        table = pq.read_table(path, columns=["start", "end", "text"])
        found[path.parent.name] = list(
            zip(
                table.column("start").to_pylist(),
                table.column("end").to_pylist(),
                table.column("text").to_pylist(),
            )
        )
    return found


def quote(rows: list[tuple[float, float, str]], t0: float, t1: float) -> str:
    text = " ".join(
        (txt or "").strip() for start, end, txt in rows if end >= t0 and start <= t1
    )
    return " ".join(text.split())


def kind(text: str) -> str:
    if not text:
        return "no_words"
    product = bool(PRODUCT.search(text))
    booth = bool(BOOTH.search(text))
    if product and not booth:
        return "narrator"
    if booth and not product:
        return "broadcaster"
    if product and booth:
        return "mixed"
    return "unclear"


def build_checks() -> tuple[list[dict], dict[str, list[tuple[float, float]]]]:
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
    for row in receipts:
        if row["network"] in {"NBC", "ESPN", "Prime", "Prime Video"}:
            pods[row["session"]].append((float(row["start"]), float(row["end"])))
    for session in pods:
        pods[session].sort()

    fixes = json.loads((OUT / "label_fixes.json").read_text())["fixes"]
    fix_spans = [
        (row["session"], float(row["start"]) - 2, float(row["end"]) + 2) for row in fixes
    ]
    transcripts = words_by_session()

    def in_ad(session: str, t: float) -> bool:
        return any(start <= t <= end for start, end in pods[session])

    def near_open(session: str, t: float) -> bool:
        return any(0 <= t - start <= 30 for start, _end in pods[session])

    def region(session: str, t: float) -> str:
        if in_ad(session, t):
            return "ad"
        if any(name == session and start <= t <= end for name, start, end in fix_spans):
            return "not_game"
        first = pods[session][0][0]
        last = pods[session][-1][1]
        if t < first or t > last + 30:
            return "not_game"
        return "game"

    decisions: dict[str, list[dict]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/BREAK_TRACE_001/decisions.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["session"] in pods:
                decisions[row["session"]].append(row)

    checks = []
    for session, rows in decisions.items():
        show = SESSION_SHOW.get(session)
        names = [name for name in CAST.get(show, []) if name in voices]
        if not names:
            continue
        rows.sort(key=lambda row: row["t"])
        windows = load_windows(session)
        mids = (windows["start"] + windows["end"]) / 2
        order = np.argsort(mids)
        mids = mids[order]
        matrix = np.vstack([voices[name] for name in names])
        raw = windows["vector"][order] @ matrix.T
        times = [float(row["t"]) for row in rows]
        bins_score: list[float | None] = []
        bins_who: list[str | None] = []
        for row in rows:
            left = int(np.searchsorted(mids, float(row["t"]) - 4, side="left"))
            right = int(np.searchsorted(mids, float(row["t"]), side="left"))
            if right <= left:
                bins_score.append(None)
                bins_who.append(None)
                continue
            chunk = raw[left:right]
            spot = np.unravel_index(int(chunk.argmax()), chunk.shape)
            bins_score.append(float(chunk[spot]))
            bins_who.append(names[int(spot[1])])
        cursor = 0
        spoken = transcripts.get(session, [])
        for index, row in enumerate(rows):
            while times[cursor] < float(row["t"]) - 30:
                cursor += 1
            if float(row["t"]) - times[cursor] < 26:
                continue
            slots = [slot for slot in range(cursor, index + 1) if bins_score[slot] is not None]
            t = float(row["t"])
            if not slots:
                checks.append({"session": session, "t": t, "region": region(session, t), "score": None})
                continue
            best = max(slots, key=lambda slot: bins_score[slot] or -1)
            text = quote(spoken, t - 6, t)
            checks.append(
                {
                    "session": session,
                    "t": t,
                    "region": region(session, t),
                    "score": bins_score[best],
                    "now": bins_score[index],
                    "who": bins_who[index] if bins_score[index] is not None else bins_who[best],
                    "near_open": near_open(session, t),
                    "speech": row.get("speech"),
                    "music": row.get("music"),
                    "kind": kind(text),
                    "words": text[:140],
                }
            )
    return checks, pods


def main() -> None:
    checks, pods = build_checks()

    lines = {}
    for line in LINES:
        cells = {
            "ad_off": 0,
            "game_off": 0,
            "ad_on": 0,
            "game_on": 0,
            "not_game": 0,
            "no_sample": 0,
            "ad_on_broadcaster": 0,
            "ad_on_narrator": 0,
            "ad_on_lookback": 0,
            "ad_on_other": 0,
            "ad_off_broadcaster": 0,
        }
        for row in checks:
            if row["score"] is None:
                cells["no_sample"] += 4
                continue
            if row["region"] == "not_game":
                cells["not_game"] += 4
                continue
            on = row["score"] >= line
            if row["region"] == "ad" and not on:
                cells["ad_off"] += 4
                if row["kind"] == "broadcaster":
                    cells["ad_off_broadcaster"] += 4
            elif row["region"] == "game" and not on:
                cells["game_off"] += 4
            elif row["region"] == "ad" and on:
                cells["ad_on"] += 4
                if row["near_open"]:
                    cells["ad_on_lookback"] += 4
                elif row["kind"] == "broadcaster":
                    cells["ad_on_broadcaster"] += 4
                elif row["kind"] == "narrator":
                    cells["ad_on_narrator"] += 4
                else:
                    cells["ad_on_other"] += 4
            elif row["region"] == "game" and on:
                cells["game_on"] += 4
        lines[f"{line:.2f}"] = cells

    payload = {
        "system": "voice_enroll_split_001",
        "model": EMBEDDING_MODEL_ID,
        "mute_policy": False,
        "note": "Host-read seconds are a second pile. not_game left the four cells. Original commercial marks were not edited.",
        "lines": lines,
    }
    (OUT / "split.json").write_text(json.dumps(payload, indent=2) + "\n")
    promo = re.compile(
        r"peacock|thursday night|sunday night|monday night|we'll be right back|"
        r"welcome back|brought to you|postgame|nfl plus|traitors|tonight show",
        re.I,
    )
    spot = re.compile(
        r"honda|chevy|chevrolet|nissan|toyota|tiktok|netflix|chipotle|mcdonald|chili|"
        r"nugget|draftkings|geico|t-mobile|iphone|applebee|xfinity|wifi|wi-fi|"
        r"insurance|cash back|best buy|pixel|hyundai|loan|dealer|a1c|prescription|"
        r"\$\d|% |percent",
        re.I,
    )
    deep_now = [row for row in checks if row["region"] == "ad" and row.get("now") is not None and row["now"] >= 0.10 and not row["near_open"]]
    buckets = {"spot": 0, "promo": 0, "booth": 0, "other": 0, "silent": 0}
    examples = []
    for row in deep_now:
        text = row.get("words") or ""
        if not text:
            buckets["silent"] += 4
            label = "silent"
        elif spot.search(text):
            buckets["spot"] += 4
            label = "spot"
        elif promo.search(text) or row["kind"] == "broadcaster":
            buckets["promo"] += 4
            label = "promo"
        else:
            buckets["other"] += 4
            label = "other"
        if label == "other" and row["now"] >= 0.20:
            examples.append(row)
    print("DEEP AD, this 4s window itself >= 0.10, past the first 30s")
    print("seconds", sum(buckets.values()), buckets)
    examples.sort(key=lambda row: -row["now"])
    shown = 0
    last = ("", -999.0)
    for row in examples:
        if row["session"] == last[0] and row["t"] - last[1] < 40:
            continue
        print(f"  {row['now']:.2f} {row['who']} {row['session'][-6:]} {row['t']:.0f} | {row['words'][:110]}")
        last = (row["session"], row["t"])
        shown += 1
        if shown >= 12:
            break

    def bounds(session: str, t: float) -> tuple[float, float] | None:
        for start, end in pods[session]:
            if start <= t <= end:
                return start, end
        return None

    ordered = sorted(deep_now, key=lambda row: (row["session"], row["t"]))
    stretches = []
    run = None
    for row in ordered:
        if run and run["session"] == row["session"] and row["t"] - run["end"] <= 6:
            run["end"] = row["t"]
            run["n"] += 1
            run["music"].append(row.get("music"))
            run["speech"].append(row.get("speech"))
            run["nows"].append(row["now"])
        else:
            if run:
                stretches.append(run)
            edge = bounds(row["session"], row["t"])
            run = {
                "session": row["session"],
                "start": row["t"],
                "end": row["t"],
                "n": 1,
                "music": [row.get("music")],
                "speech": [row.get("speech")],
                "nows": [row["now"]],
                "pod": edge,
            }
    if run:
        stretches.append(run)

    def mid(values: list[float | None]) -> float | None:
        kept = sorted(value for value in values if value is not None)
        if not kept:
            return None
        return kept[len(kept) // 2]

    place_s = {"just after the first 30s": 0, "middle of the ad": 0, "last 12s of the ad": 0}
    music_s = {"song": 0, "quiet": 0, "in between": 0}
    length_s = {"4s": 0, "8-12s": 0, "16s or more": 0}
    for item in stretches:
        seconds = item["n"] * 4
        start, end = item["pod"] if item["pod"] else (item["start"], item["end"])
        into = item["start"] - start
        left = end - item["end"]
        if left <= 12:
            place_s["last 12s of the ad"] += seconds
        elif into <= 46:
            place_s["just after the first 30s"] += seconds
        else:
            place_s["middle of the ad"] += seconds
        music = mid(item["music"])
        if music is None:
            pass
        elif music >= 0.70:
            music_s["song"] += seconds
        elif music < 0.30:
            music_s["quiet"] += seconds
        else:
            music_s["in between"] += seconds
        if item["n"] == 1:
            length_s["4s"] += seconds
        elif item["n"] <= 3:
            length_s["8-12s"] += seconds
        else:
            length_s["16s or more"] += seconds
        item["music_mid"] = music
        item["left"] = left

    by_session: dict[str, list[dict]] = defaultdict(list)
    for row in checks:
        if row.get("now") is not None:
            by_session[row["session"]].append(row)

    song_cut = quiet_hold = blip = late = 0
    for item in stretches:
        seconds = item["n"] * 4
        if item["music_mid"] is not None and item["music_mid"] >= 0.70:
            song_cut += seconds
        if item["music_mid"] is not None and item["music_mid"] < 0.30 and item["n"] >= 3:
            quiet_hold += seconds
        if item["n"] == 1:
            blip += seconds
        if item["left"] <= 12:
            late += seconds

    returns = 0
    returns_song = 0
    returns_quiet = 0
    returns_heard = 0
    lag_quiet = []
    for session, edges in pods.items():
        rows = by_session.get(session, [])
        for _start, end in edges:
            window = [row for row in rows if end < row["t"] <= end + 60 and row["region"] == "game"]
            first = [row for row in window if row["t"] <= end + 12]
            if not first:
                continue
            returns += 1
            music = mid([row.get("music") for row in first])
            heard = any(row["now"] >= 0.10 for row in first)
            if heard:
                returns_heard += 1
            if music is not None and music >= 0.70:
                returns_song += 1
            if music is not None and music < 0.30 and heard:
                returns_quiet += 1
            over = next((row for row in window if row["now"] >= 0.10), None)
            quiet = next(
                (
                    row
                    for row in window
                    if row["now"] >= 0.10 and row.get("music") is not None and row["music"] < 0.30
                ),
                None,
            )
            if over and quiet:
                lag_quiet.append(quiet["t"] - over["t"])
            elif over and not quiet:
                lag_quiet.append(None)

    waited = [lag for lag in lag_quiet if lag is not None]
    never = sum(1 for lag in lag_quiet if lag is None)
    within = lambda limit: sum(1 for lag in waited if lag <= limit)

    before_song = 0
    for item in stretches:
        seconds = item["n"] * 4
        earlier = [
            row
            for row in by_session.get(item["session"], [])
            if item["start"] - 12 <= row["t"] < item["start"]
        ]
        music = mid([row.get("music") for row in earlier])
        if music is not None and music >= 0.70:
            before_song += seconds
    print("WHERE the 5556 seconds sit")
    print(" ", place_s)
    print(" music under them", music_s)
    print(f" the 12s before the match is already a song for {before_song}s")
    print(" how long the match lasts", length_s)
    print(
        f" a song is playing under {song_cut}s; a 4s blip is {blip}s; "
        f"the labeled ad ends within 12s for {late}s"
    )
    print(
        f" still there if we only trust a quiet stretch of 12s or more: {quiet_hold}s"
    )
    print(
        f" real returns in the 12s after a labeled ad: {returns} ads, "
        f"{returns_heard} already over 0.10, {returns_song} have a song, "
        f"{returns_quiet} are quiet and over 0.10"
    )
    print(
        f" after the voice is already back, the song is gone within "
        f"0s {within(0)}, 4s {within(4)}, 12s {within(12)}, 30s {within(30)} "
        f"of {len(waited)} returns; {never} still have the song 60s later"
    )
    print("GAME OFF stretches at 0.15")
    run = None
    runs15 = []
    for row in checks:
        hit = row["region"] == "game" and row["score"] is not None and row["score"] < 0.15
        if hit and run and run["session"] == row["session"] and row["t"] - run["end"] <= 6:
            run["end"] = row["t"]
            run["n"] += 1
            run["peak"] = max(run["peak"], row["score"])
            run["words"] = (run["words"] + " " + (row.get("words") or ""))[-160:]
        elif hit:
            if run:
                runs15.append(run)
            run = {
                "session": row["session"],
                "start": row["t"],
                "end": row["t"],
                "n": 1,
                "peak": row["score"],
                "who": row.get("who"),
                "words": row.get("words") or "",
            }
        elif run:
            runs15.append(run)
            run = None
    if run:
        runs15.append(run)
    for run in sorted(runs15, key=lambda item: -item["n"]):
        print(
            f"  {run['n']*4:4}s {run['session'][-6:]} {run['start']:.0f} peak {run['peak']:.3f} {run['who']} | {run['words'][:100]}"
        )
    print("stretches", len(runs15), "seconds", sum(item["n"] * 4 for item in runs15))
    print("GAME OFF stretches at 0.20")
    run = None
    runs = []
    for row in checks:
        hit = row["region"] == "game" and row["score"] is not None and row["score"] < 0.20
        if hit and run and run["session"] == row["session"] and row["t"] - run["end"] <= 6:
            run["end"] = row["t"]
            run["n"] += 1
            run["peak"] = max(run["peak"], row["score"])
            run["words"] = (run["words"] + " " + (row.get("words") or ""))[-180:]
        elif hit:
            if run:
                runs.append(run)
            run = {
                "session": row["session"],
                "start": row["t"],
                "end": row["t"],
                "n": 1,
                "peak": row["score"],
                "who": row.get("who"),
                "words": row.get("words") or "",
            }
        elif run:
            runs.append(run)
            run = None
    if run:
        runs.append(run)
    for run in sorted(runs, key=lambda item: -item["n"])[:18]:
        print(
            f"  {run['n']*4:4}s {run['session'][-6:]} {run['start']:.0f} peak {run['peak']:.3f} {run['who']} | {run['words'][:110]}"
        )
    print("stretches", len(runs), "seconds", sum(item["n"] * 4 for item in runs))
    print("GAME OFF at 0.10")
    for row in checks:
        if row["region"] == "game" and row["score"] is not None and row["score"] < 0.10:
            print(f"  {row['session']} {row['t']:.0f} {row['score']:.3f} {row.get('who')} | {row.get('words')}")
    print("AD ON other at 0.25, samples")
    shown = 0
    last_t = -999.0
    last_session = ""
    for row in checks:
        if row["region"] != "ad" or row["score"] is None or row["score"] < 0.25:
            continue
        if row["near_open"] or row["kind"] in {"broadcaster", "narrator"}:
            continue
        if row["session"] == last_session and row["t"] - last_t < 40:
            continue
        print(f"  {row['kind']:10} {row['session'][-6:]} {row['t']:.0f} {row['score']:.2f} {row.get('who')} | {row.get('words')}")
        last_t = row["t"]
        last_session = row["session"]
        shown += 1
        if shown >= 24:
            break
    print(f"{'line':>6} {'ad off':>8} {'game off':>9} {'ad on':>8} {'game on':>8} {'host on':>8} {'narr on':>8} {'memory':>8} {'other':>8}")
    for line in LINES:
        cells = lines[f"{line:.2f}"]
        print(
            f"{line:6.2f} {cells['ad_off']:8} {cells['game_off']:9} {cells['ad_on']:8} "
            f"{cells['game_on']:8} {cells['ad_on_broadcaster']:8} {cells['ad_on_narrator']:8} "
            f"{cells['ad_on_lookback']:8} {cells['ad_on_other']:8}"
        )


if __name__ == "__main__":
    main()
