"""Failure-first replay for October 8 Prime. Not a mute.

Count-10 decisions are the published stream. They can read future audio.
Staying covered is applied to that same stream so the tradeoff is on one clock.
Gold is used only after the actions, to count seconds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage  # noqa: E402
from experiments.universal_v1.replay import (  # noqa: E402
    actions_for,
    cover_spans,
    intersect,
    merge,
    overlap,
    subtract,
)

SID = "hush_20261008_205100"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
CONFIRM = REPO / "docs/ohush/research/EXACT_AUDIO_CONFIRM_001/confirmations.jsonl"
OUT = REPO / "docs/ohush/research/TNF_FAILURES_001"
POD = (139.874, 376.900)
FAIL_OPEN_S = 180.0


def incidents(program_pieces: list[tuple[float, float]]) -> list[dict]:
    rows = []
    for index, (left, right) in enumerate(program_pieces, start=1):
        rows.append(
            {
                "incident": index,
                "start_s": round(left, 3),
                "end_s": round(right, 3),
                "seconds": round(right - left, 3),
            }
        )
    return rows


def stay_covered(decisions: list[dict], cov1: float, fail_open_s: float) -> list[tuple[float, float]]:
    spans = []
    hold_until = None
    for index, row in enumerate(decisions):
        start = float(row["available_at"])
        end = cov1 if index + 1 == len(decisions) else float(decisions[index + 1]["available_at"])
        if hold_until is not None and start >= hold_until:
            hold_until = None
        hot = int(row["score"]) >= 10 and not row["same_session"]
        if hold_until is None and hot:
            hold_until = start + fail_open_s
        if hold_until is None:
            continue
        piece_end = min(end, hold_until)
        if piece_end > start:
            spans.append((start, piece_end))
    return merge(spans)


def confirmed_hold(decisions: list[dict], confirms: dict[float, dict], cov1: float, fail_open_s: float) -> list[tuple[float, float]]:
    """Stay covered only after a count-10 hit the waveform also accepts."""
    spans = []
    hold_until = None
    for index, row in enumerate(decisions):
        start = float(row["available_at"])
        end = cov1 if index + 1 == len(decisions) else float(decisions[index + 1]["available_at"])
        if hold_until is not None and start >= hold_until:
            hold_until = None
        confirm = confirms.get(float(row["query_t0"]))
        hot = (
            int(row["score"]) >= 10
            and not row["same_session"]
            and confirm is not None
            and confirm["accepted"]
        )
        if hold_until is None and hot:
            hold_until = start + fail_open_s
        if hold_until is None:
            continue
        piece_end = min(end, hold_until)
        if piece_end > start:
            spans.append((start, piece_end))
    return merge(spans)


def confirmed_covers(decisions: list[dict], confirms: dict[float, dict], cov1: float) -> list[tuple[float, float]]:
    spans = []
    for index, row in enumerate(decisions):
        start = float(row["available_at"])
        end = cov1 if index + 1 == len(decisions) else float(decisions[index + 1]["available_at"])
        if int(row["score"]) < 10 or row["same_session"]:
            continue
        confirm = confirms.get(float(row["query_t0"]))
        if confirm is None or not confirm["accepted"]:
            continue
        spans.append((start, end))
    return merge(spans)


def score(covers: list[tuple[float, float]], ads, program) -> dict:
    ad = overlap(covers, ads)
    prog_pieces = intersect(covers, program)
    return {
        "commercial_seconds_covered": round(ad, 1),
        "program_seconds_covered": round(overlap(covers, program), 1),
        "false_cover_incidents": len(prog_pieces),
        "worst_program_interruption_s": round(max((b - a for a, b in prog_pieces), default=0.0), 1),
        "incidents": incidents(prog_pieces),
        "draftkings_pod_covered_s": round(overlap(covers, [POD]), 1),
    }


def main() -> None:
    decisions = []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] == SID:
            decisions.append(row)
    decisions.sort(key=lambda row: float(row["available_at"]))
    confirms = {}
    for line in CONFIRM.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] == SID:
            confirms[float(row["query_t0"])] = row
    spans = [span for span in coverage() if span["session"] == SID]
    cov0 = min(float(span["from_seconds"]) for span in spans)
    cov1 = max(float(span["to_seconds"]) for span in spans)
    ads = [(float(row["start_seconds"]), float(row["end_seconds"])) for row in commercials(spans)]
    program = subtract([(cov0, cov1)], ads)
    bag = {"coverage": (cov0, cov1)}
    letgo = cover_spans(actions_for(bag, decisions, 10))
    held = stay_covered(decisions, cov1, FAIL_OPEN_S)
    kept = confirmed_covers(decisions, confirms, cov1)
    held_confirmed = confirmed_hold(decisions, confirms, cov1, FAIL_OPEN_S)
    base = score(letgo, ads, program)
    stay = score(held, ads, program)
    wave = score(kept, ads, program)
    stay_wave = score(held_confirmed, ads, program)

    enriched = []
    for row in base["incidents"]:
        hits = []
        cursor = None
        for decision in decisions:
            start = float(decision["available_at"])
            if cursor is not None and int(cursor["score"]) >= 10 and not cursor["same_session"]:
                if start > row["start_s"] and float(cursor["available_at"]) < row["end_s"]:
                    hits.append(cursor)
            cursor = decision
        if cursor is not None and int(cursor["score"]) >= 10 and not cursor["same_session"]:
            if cov1 > row["start_s"] and float(cursor["available_at"]) < row["end_s"]:
                hits.append(cursor)
        confirm_rows = [confirms.get(float(hit["query_t0"])) for hit in hits]
        confirm_rows = [item for item in confirm_rows if item]
        accepted = sum(1 for item in confirm_rows if item["accepted"])
        best = max((float(item["best_positive_within_2s"]) for item in confirm_rows), default=None)
        near_pod = any(abs(float(hit["query_t0"]) - edge) <= 20 for hit in hits for edge in (row["start_s"],))
        pod_edge = min((abs(row["start_s"] - end) for _start, end in ads), default=999)
        if pod_edge <= 0.05 and best is not None and best >= 0.85:
            cause = "recognized copy runs past the labeled commercial end"
        elif pod_edge <= 0.05:
            cause = "weak match at the labeled commercial end"
        elif confirm_rows and accepted == 0 and best is not None and best < 0.2:
            cause = "unrelated fingerprint collision"
        elif confirm_rows and accepted == len(confirm_rows) and best is not None and best >= 0.85:
            cause = "repeated audio on program-labeled time"
        elif confirm_rows and accepted == 0:
            cause = "waveform confirmation rejects the match"
        else:
            cause = "count-10 match, confirmation row absent"
        enriched.append(
            {
                **row,
                "decisions": len(hits),
                "max_score": max((int(hit["score"]) for hit in hits), default=None),
                "refs": sorted({hit.get("ref_session") for hit in hits if hit.get("ref_session")}),
                "confirmation_rows": len(confirm_rows),
                "confirmation_accepted": accepted,
                "best_correlation": None if best is None else round(best, 4),
                "seconds_after_nearest_ad_end": round(pod_edge, 1),
                "cause": cause,
                "near_query": near_pod,
            }
        )

    control = (3390.0, 3410.0)
    control_hits = [
        {
            "query_t0": row["query_t0"],
            "score": row["score"],
            "ref_session": row["ref_session"],
        }
        for row in decisions
        if float(row["query_t0"]) < control[1]
        and float(row["query_t1"]) > control[0]
        and int(row["score"]) >= 10
        and not row["same_session"]
    ]
    pod_decisions = [
        {
            "query_t0": row["query_t0"],
            "score": row["score"],
            "ref_session": row["ref_session"],
        }
        for row in decisions
        if POD[0] <= float(row["query_t0"]) < POD[1] and int(row["score"]) >= 10 and not row["same_session"]
    ]
    result = {
        "session": SID,
        "clock": "published count-10 decisions; alignment can read future audio; not a live rate",
        "gold_used_only_to_score": True,
        "let_go_count_10": {key: base[key] for key in base if key != "incidents"},
        "stay_covered_180s": {key: stay[key] for key in stay if key != "incidents"},
        "waveform_confirm_0.85": {key: wave[key] for key in wave if key != "incidents"},
        "stay_after_confirmed_start_180s": {key: stay_wave[key] for key in stay_wave if key != "incidents"},
        "delta_confirmed_hold_minus_let_go": {
            "commercial_seconds": round(stay_wave["commercial_seconds_covered"] - base["commercial_seconds_covered"], 1),
            "program_seconds": round(stay_wave["program_seconds_covered"] - base["program_seconds_covered"], 1),
        },
        "negative_control_3390_3410": {
            "count10_hits": control_hits,
            "let_go_program_seconds": round(overlap(letgo, [control]), 1),
            "note": "The count-10 interruption begins at 3415, five seconds after this window.",
        },
        "draftkings_count10_queries_at_or_above_10": pod_decisions,
        "false_interruptions": enriched,
        "stay_covered_incidents": stay["incidents"],
        "waveform_incidents": wave["incidents"],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# TNF failures 001",
        "",
        "Not a mute. October 8 Prime, `hush_20261008_205100`. The count-10 stream can read future audio. Gold was applied after the actions.",
        "",
        "## Same stream, four rules",
        "",
        "| Rule | Ads covered | Game covered | Game interruptions | Worst | DraftKings pod covered |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in (
        ("Let go when the score drops", base),
        ("Stay 180 s after every count-10 start", stay),
        ("Keep only waveform correlation ≥ 0.85", wave),
        ("Stay 180 s only after a confirmed start", stay_wave),
    ):
        lines.append(
            f"| {name} | {row['commercial_seconds_covered']} | {row['program_seconds_covered']} | {row['false_cover_incidents']} | {row['worst_program_interruption_s']} | {row['draftkings_pod_covered_s']} |"
        )
    lines += [
        "",
        f"Holding every count-10 start for 180 s changes commercial seconds by {round(stay['commercial_seconds_covered'] - base['commercial_seconds_covered'], 1)} and program seconds by {round(stay['program_seconds_covered'] - base['program_seconds_covered'], 1)}.",
        f"Holding only a waveform-confirmed start changes commercial seconds by {result['delta_confirmed_hold_minus_let_go']['commercial_seconds']} and program seconds by {result['delta_confirmed_hold_minus_let_go']['program_seconds']}.",
        "",
        "The DraftKings pod is 139.874–376.900 s (237.0 s). A 180 s hold that begins at the first count-10 decision covers 180.0 s and ends inside the pod, so that one hold does not mute the game. The extra program seconds come from the same timer on later, shorter breaks.",
        "",
        f"The 3,390–3,410 s negative control has {len(control_hits)} count-10 hits. The nearby game interruption starts at 3,415 s.",
        "",
        "September 24 Prime break 6, 2,217.880–2,338.326 s, is a different tape. Its already-measured return is 40.7 s for the booth voice and 84.7 s for the acoustic signature, on both the oracle and the causal clock. No new return-signal contest was run.",
        "",
        "None of these rules is installed in the live gate. The waveform alignment can read future audio. A full-file causal fingerprint of this tape was not run.",
        "",
        "## The 12 count-10 game interruptions",
        "",
        "| # | Start | Seconds | Score | Correlation | Cause |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in enriched:
        corr = "—" if row["best_correlation"] is None else row["best_correlation"]
        lines.append(
            f"| {row['incident']} | {row['start_s']} | {row['seconds']} | {row['max_score']} | {corr} | {row['cause']} |"
        )
    lines.append("")
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
