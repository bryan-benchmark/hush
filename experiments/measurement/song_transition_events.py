"""Turn the causal music scores into transition events, then compare to gold.

Detection does not read labels. The comparison below is a separate step.
Lines are unchanged from song_transition_001: low music under 0.30, high music
at least 0.70, speech at least 0.50, a low window 8 to 24 seconds before the
high window. A new event waits until music has been low again.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402

SCORES = REPO / "docs/ohush/research/SONG_TRANSITION_001/scores.jsonl"
OUT = REPO / "docs/ohush/research/SONG_TRANSITION_001/events.json"
LOW = 0.30
HIGH = 0.70
SPEECH = 0.50
LOOK_LO = 8.0
LOOK_HI = 24.0
CREDIT_BEFORE = 30.0
CREDIT_AFTER = 2.0
REDZONE = "hush_20260913_150934"


def events_for(rows):
    """rows are one session, sorted by t."""
    fired = []
    latched = False
    for i, row in enumerate(rows):
        music = row["music"]
        speech = row["speech"]
        if music < LOW:
            latched = False
        high = music >= HIGH and speech >= SPEECH
        if not high or latched:
            continue
        t = row["t"]
        prior = None
        for prev in reversed(rows[:i]):
            gap = t - prev["t"]
            if gap < LOOK_LO:
                continue
            if gap > LOOK_HI:
                break
            if prev["music"] < LOW and prev["speech"] >= SPEECH:
                prior = prev
                break
        if prior is None:
            continue
        latched = True
        fired.append({
            "session": row["session"],
            "t": t,
            "music": music,
            "speech": speech,
            "low_t": prior["t"],
            "low_music": prior["music"],
        })
    return fired


def main():
    catalog = load_catalog()
    by_session = defaultdict(list)
    done = []
    for line in SCORES.read_text().splitlines():
        if not line:
            continue
        row = json.loads(line)
        if row.get("kind") == "session_done":
            done.append(row["session"])
            continue
        by_session[row["session"]].append(row)
    found = []
    for sid, rows in by_session.items():
        rows.sort(key=lambda r: r["t"])
        found.extend(events_for(rows))
    sports = [r for r in commercials(coverage()) if catalog.get(r["session"], {}).get("content_type") == "sports"]
    breaks = [r for r in sports if r["session"] != REDZONE]
    zone_breaks = [r for r in sports if r["session"] == REDZONE]
    pods = defaultdict(list)
    for row in sports:
        pods[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))

    def nearest(row, horizon):
        t = float(row["start_seconds"])
        sid = row["session"]
        hits = [e for e in found if e["session"] == sid and t - horizon <= e["t"] <= t + CREDIT_AFTER]
        if not hits:
            return None
        best = min(hits, key=lambda e: abs(t - e["t"]))
        return {"session": sid, "boundary": round(t, 3), "event_t": best["t"], "lead_s": round(t - best["t"], 3)}

    # 30 seconds is the credit. 60 seconds is only the lead distribution, the same minute already measured.
    credited = []
    missed = []
    leads_60 = []
    for row in breaks:
        hit = nearest(row, CREDIT_BEFORE)
        far = nearest(row, 60.0)
        if far:
            leads_60.append(far["lead_s"])
        if hit:
            credited.append(hit)
        else:
            missed.append({"session": row["session"], "boundary": round(float(row["start_seconds"]), 3)})
    zone_credited = [nearest(row, CREDIT_BEFORE) for row in zone_breaks]
    zone_credited = [row for row in zone_credited if row]

    program = []
    zone_program = []
    inside = []
    near = []
    for event in found:
        intervals = pods.get(event["session"], [])
        t = event["t"]
        bucket = zone_program if event["session"] == REDZONE else program
        if any(a <= t <= b for a, b in intervals):
            inside.append(event)
        elif any(a - CREDIT_BEFORE <= t <= a for a, b in intervals):
            near.append(event)
        else:
            bucket.append(event)

    def hours(session_filter):
        total = 0.0
        for span in coverage():
            if not span.get("fully_annotated"):
                continue
            sid = span["session"]
            if sid not in by_session:
                continue
            if session_filter(sid):
                total += float(span["to_seconds"]) - float(span["from_seconds"])
        return total / 3600.0

    def is_redzone(sid):
        return sid == REDZONE

    def is_game(sid):
        return sid != REDZONE and catalog.get(sid, {}).get("content_type") == "sports"

    game_hours = hours(is_game)
    zone_hours = hours(is_redzone)
    football_pod_s = sum(b - a for sid, iv in pods.items() if sid != REDZONE for a, b in iv)
    play_hours = max(game_hours - football_pod_s / 3600.0, 1e-6)

    def net_name(sid):
        if sid == REDZONE:
            return "FOX RedZone"
        return catalog.get(sid, {}).get("network_or_service") or "unknown"

    by_net = defaultdict(lambda: {"program_events": 0, "credited_breaks": 0, "breaks": 0, "span_s": 0.0, "pod_s": 0.0})
    for span in coverage():
        sid = span["session"]
        if sid not in by_session or catalog.get(sid, {}).get("content_type") != "sports":
            continue
        by_net[net_name(sid)]["span_s"] += float(span["to_seconds"]) - float(span["from_seconds"])
    for row in sports:
        by_net[net_name(row["session"])]["breaks"] += 1
        by_net[net_name(row["session"])]["pod_s"] += float(row["end_seconds"]) - float(row["start_seconds"])
    for event in program + zone_program:
        by_net[net_name(event["session"])]["program_events"] += 1
    for row in credited + zone_credited:
        by_net[net_name(row["session"])]["credited_breaks"] += 1
    for name, row in by_net.items():
        play_s = max(row["span_s"] - row["pod_s"], 0.0)
        row["play_hours"] = round(play_s / 3600.0, 2)
        row["program_events_per_play_hour"] = round(row["program_events"] / max(play_s / 3600.0, 1e-6), 2)
        row["span_s"] = round(row["span_s"], 1)
        row["pod_s"] = round(row["pod_s"], 1)

    # Universal v1. A cover decision applies until the next decision. Requiring a transition can only keep or drop those seconds.
    v1_intervals = []
    receipt = REPO / "docs/ohush/research/UNIVERSAL_V1/receipts.jsonl"
    if receipt.exists():
        by_receipt = defaultdict(list)
        for line in receipt.read_text().splitlines():
            row = json.loads(line)
            if catalog.get(row["session"], {}).get("content_type") != "sports" or row["session"] == REDZONE:
                continue
            by_receipt[row["session"]].append(row)
        for sid, rows in by_receipt.items():
            rows.sort(key=lambda r: float(r["t_decision"]))
            for i, row in enumerate(rows):
                if row.get("action") != "cover":
                    continue
                t0 = float(row["t_decision"])
                t1 = float(rows[i + 1]["t_decision"]) if i + 1 < len(rows) else t0
                preceded = any(e["session"] == sid and t0 - 30 <= e["t"] <= t0 for e in found)
                v1_intervals.append({"session": sid, "t0": t0, "t1": t1, "seconds": round(t1 - t0, 3), "transition_in_prior_30s": preceded})

    leads = sorted(c["lead_s"] for c in credited)
    leads_60 = sorted(leads_60)

    def pct(xs, q):
        if not xs:
            return None
        k = int(round((len(xs) - 1) * q))
        return xs[k]

    v1_seconds = round(sum(row["seconds"] for row in v1_intervals), 3)
    v1_kept = round(sum(row["seconds"] for row in v1_intervals if row["transition_in_prior_30s"]), 3)
    payload = {
        "rule": {
            "low_music": LOW,
            "high_music": HIGH,
            "speech": SPEECH,
            "lookback_s": [LOOK_LO, LOOK_HI],
            "credit_before_s": CREDIT_BEFORE,
            "credit_after_s": CREDIT_AFTER,
            "lead_horizon_s": 60.0,
            "hop_s": 4.0,
            "window_s": 4.0,
        },
        "sessions_scanned": done,
        "events": len(found),
        "breaks": len(breaks),
        "redzone_breaks": len(zone_breaks),
        "breaks_with_an_event_in_the_30s_before": len(credited),
        "breaks_without": len(missed),
        "breaks_with_an_event_in_the_prior_60s": len(leads_60),
        "lead_s_when_credited_inside_30s": {"median": pct(leads, 0.5), "p20": pct(leads, 0.2), "p80": pct(leads, 0.8)},
        "lead_s_nearest_inside_60s": {"median": pct(leads_60, 0.5), "p20": pct(leads_60, 0.2), "p80": pct(leads_60, 0.8)},
        "redzone_breaks_with_an_event": len(zone_credited),
        "events_inside_commercials": len(inside),
        "events_in_the_30s_before_a_start": len(near),
        "program_events": len(program),
        "redzone_program_events": len(zone_program),
        "game_hours": round(game_hours, 2),
        "football_commercial_hours": round(football_pod_s / 3600.0, 2),
        "play_hours": round(play_hours, 2),
        "redzone_hours": round(zone_hours, 2),
        "program_events_per_play_hour": round(len(program) / play_hours, 2),
        "redzone_events_per_hour": round(len(zone_program) / max(zone_hours, 1e-6), 2),
        "by_network": {k: dict(v) for k, v in sorted(by_net.items())},
        "universal_v1_cover_seconds": v1_seconds,
        "universal_v1_cover_seconds_with_a_transition_in_the_prior_30s": v1_kept,
        "universal_v1_intervals": v1_intervals,
        "credited": credited,
        "program_event_times": [{"session": e["session"], "t": e["t"]} for e in program],
        "redzone_program_event_times": [{"session": e["session"], "t": e["t"]} for e in zone_program],
    }
    OUT.write_text(json.dumps(payload), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in payload if k not in ("credited", "program_events")}, indent=2))


if __name__ == "__main__":
    main()
