"""Two scores for every labeled football break. Not a mute.

Start: did a cover begin during the pod, and how late.
End: did play resume at the gold end, or did a cover let go inside the ad.

The 79% blended second-count is not either of these. Play catches no start.
A policy that never mutes has no unmute to score.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402

OUT = REPO / "docs/ohush/research/START_END_001"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
DSP = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/starts.csv"
SONG = REPO / "docs/ohush/research/SONG_TRANSITION_001/events.json"
REDZONE = "hush_20260913_150934"
COUNT = 200


def actions_for(decisions, cov0, cov1, count):
    if not decisions:
        return [(cov0, cov1, "play")]
    spans = [(cov0, decisions[0]["available_at"], "play")]
    for index, row in enumerate(decisions):
        start = row["available_at"]
        end = cov1 if index + 1 == len(decisions) else decisions[index + 1]["available_at"]
        action = "cover" if row["score"] >= count and not row["same_session"] else "play"
        spans.append((start, end, action))
    return [(left, right, action) for left, right, action in spans if right > left]


def main():
    catalog = load_catalog()
    spans = {row["session"]: (float(row["from_seconds"]), float(row["to_seconds"])) for row in coverage()}
    decisions = defaultdict(list)
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            decisions[row["session"]].append(row)
    for rows in decisions.values():
        rows.sort(key=lambda row: row["available_at"])
    dsp = {}
    if DSP.exists():
        for row in csv.DictReader(DSP.open(encoding="utf-8")):
            if row["content"] != "sports":
                continue
            dsp[(row["session"], round(float(row["boundary_s"]), 3))] = row
    song = {}
    if SONG.exists():
        payload = json.loads(SONG.read_text(encoding="utf-8"))
        for row in payload.get("credited", []):
            song[(row["session"], round(float(row["boundary"]), 3))] = row["lead_s"]

    receipts = []
    for gold in commercials(coverage()):
        sid = gold["session"]
        if catalog.get(sid, {}).get("content_type") != "sports" or sid == REDZONE:
            continue
        start = float(gold["start_seconds"])
        end = float(gold["end_seconds"])
        cov0, cov1 = spans[sid]
        timeline = actions_for(decisions.get(sid, []), cov0, cov1, COUNT)
        covers = [(left, right) for left, right, action in timeline if action == "cover"]
        first = None
        covered_s = 0.0
        for left, right in covers:
            lo, hi = max(start, left), min(end, right)
            if hi > lo:
                covered_s += hi - lo
                if first is None:
                    first = lo
        heard_before = 0.0 if first is None else max(0.0, first - start)
        heard_after = 0.0
        saw = False
        end_kind = "no_mute"
        program_after = 0.0
        if first is None:
            end_kind = "no_mute"
        else:
            for left, right, action in timeline:
                lo, hi = max(left, start), min(right, end)
                if hi <= lo:
                    continue
                if action == "cover":
                    saw = True
                elif saw:
                    heard_after += hi - lo
                    end_kind = "let_go_inside_the_ad"
            holding = any(action == "cover" and left <= end - 1e-6 < right for left, right, action in timeline)
            if holding:
                nxt = next((left for left, _right, action in timeline if action == "play" and left >= end - 1e-9), None)
                if nxt is None:
                    end_kind = "still_covered_at_annotation_end"
                else:
                    program_after = nxt - end
                    end_kind = "unmuted_after_the_game_returned"
        dsp_row = None
        best = None
        for key, row in dsp.items():
            if key[0] != sid:
                continue
            gap = abs(key[1] - start)
            if best is None or gap < best:
                best = gap
                dsp_row = row
        if best is None or best > 0.05:
            dsp_row = None
        song_lead = None
        best_song = None
        for key, lead in song.items():
            if key[0] != sid:
                continue
            gap = abs(key[1] - start)
            if best_song is None or gap < best_song:
                best_song = gap
                song_lead = lead
        if best_song is None or best_song > 0.05:
            song_lead = None
        receipts.append({
            "session": sid,
            "network": catalog.get(sid, {}).get("network_or_service") or "unknown",
            "start": round(start, 3),
            "end": round(end, 3),
            "length_s": round(end - start, 3),
            "start_caught": first is not None,
            "start_delay_s": None if first is None else round(first - start, 3),
            "commercial_seconds_covered": round(covered_s, 3),
            "commercial_seconds_heard_before_the_mute": round(heard_before, 3) if first is not None else round(end - start, 3),
            "end_kind": end_kind,
            "ad_seconds_heard_after_let_go": round(heard_after, 3),
            "program_seconds_still_muted_after_the_end": round(program_after, 3),
            "dsp_delay_s": None if dsp_row is None or dsp_row["or_delay_s"] == "" else float(dsp_row["or_delay_s"]),
            "dsp_within_3s": False if dsp_row is None else dsp_row["or_within_3"] == "True",
            "dsp_within_30s": False if dsp_row is None else dsp_row["or_within_30"] == "True",
            "song_rise_lead_s": song_lead,
        })

    def rate(flag):
        return sum(1 for row in receipts if row[flag])

    caught = [row for row in receipts if row["start_caught"]]
    by_net = defaultdict(lambda: {"pods": 0, "starts_caught": 0, "let_go": 0, "dsp_within_3s": 0})
    for row in receipts:
        bag = by_net[row["network"]]
        bag["pods"] += 1
        bag["starts_caught"] += int(row["start_caught"])
        bag["let_go"] += int(row["end_kind"] == "let_go_inside_the_ad")
        bag["dsp_within_3s"] += int(row["dsp_within_3s"])
    lengths = {"under_60s": 0, "60_to_180s": 0, "over_180s": 0}
    for row in receipts:
        if row["start_caught"]:
            continue
        if row["length_s"] < 60:
            lengths["under_60s"] += 1
        elif row["length_s"] <= 180:
            lengths["60_to_180s"] += 1
        else:
            lengths["over_180s"] += 1
    payload = {
        "what_79_percent_was": {
            "program_seconds_heard": 67428.0,
            "commercial_seconds_muted": 0.0,
            "corpus_seconds": 85076.4,
            "percent": 79.26,
            "meaning": "Share of corpus seconds that are programming, under a policy that mutes nothing. Not a start rate. Not an unmute rate.",
        },
        "pods": len(receipts),
        "start": {
            "caught": len(caught),
            "missed": len(receipts) - len(caught),
            "caught_within_3s": sum(1 for row in caught if row["start_delay_s"] is not None and row["start_delay_s"] <= 3),
            "delays_on_the_ones_caught_s": sorted(row["start_delay_s"] for row in caught),
            "commercial_seconds_covered": round(sum(row["commercial_seconds_covered"] for row in receipts), 1),
        },
        "end": {
            "unmuted_at_the_gold_end": sum(1 for row in receipts if row["end_kind"] == "unmuted_after_the_game_returned" and row["program_seconds_still_muted_after_the_end"] == 0),
            "let_go_inside_the_ad": sum(1 for row in receipts if row["end_kind"] == "let_go_inside_the_ad"),
            "no_mute_so_no_unmute": sum(1 for row in receipts if row["end_kind"] == "no_mute"),
            "program_seconds_still_muted_after_the_end": round(sum(row["program_seconds_still_muted_after_the_end"] for row in receipts), 1),
            "ad_seconds_heard_after_let_go": round(sum(row["ad_seconds_heard_after_let_go"] for row in receipts), 1),
        },
        "dsp_alarm_not_a_mute": {
            "within_3s": rate("dsp_within_3s"),
            "within_30s": rate("dsp_within_30s"),
        },
        "song_rise_before_the_start": sum(1 for row in receipts if row["song_rise_lead_s"] is not None),
        "missed_starts_by_length": lengths,
        "by_network": {key: dict(value) for key, value in sorted(by_net.items())},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (OUT / "receipts.jsonl").open("w", encoding="utf-8") as handle:
        for row in receipts:
            handle.write(json.dumps(row) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
