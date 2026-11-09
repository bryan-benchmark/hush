"""Boundary recovery: gold ad end → does cover stick into program/desk?

Audit every gold-ad trailing edge on Prime, then KPI-test a post-break
cool-down latch (force play for N seconds after ad end). Frozen checkpoint
and live television stay put.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.studio_fit import CONTROLLER, DESK_SPANS, _overlap, _score_array
from experiments.measurement.metrics import Interval, target_commercials
from experiments.nfl75.inventory import active_intervals, coverage_by_session
from experiments.nfl75.score import playback_from_decisions

FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
REVIEWED = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\OHUSH_STUDIO_HEAD_001\reviewed_boundaries.json")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\boundary_recovery")
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
FOCUS = {
    "hush_20260924_220624": {
        "odell": (7035.0, 7095.2),
        "whitworth": (7406.8, 7436.2),
        "palmer": (6180.7, 6207.8),
        "injury": (6267.8, 6287.2),
    },
    "hush_20261008_205100": {
        "welcome_back": (3437.1, 3443.0),
    },
}
# cool-down windows to KPI-test after audit
COOL_S_OPTIONS = (3.0, 5.0, 8.0, 12.0, 20.0)
HORIZON_AFTER = 30.0


def _round(row: dict) -> dict:
    kept = {}
    for key in (
        "commercial_coverage",
        "commercial_covered_s",
        "commercial_s",
        "program_covered_s",
        "false_mute_episodes",
        "false_mutes_per_hour",
        "longest_false_mute_s",
        "recovery",
        "desk_span_covered_s",
    ):
        value = row[key]
        kept[key] = None if value is None else round(float(value), 4)
    delays = [item["start_delay_s"] for item in row["breaks"] if item["start_delay_s"] is not None]
    kept["median_start_delay_s"] = None if not delays else round(float(np.median(delays)), 3)
    kept["breaks_missed"] = sum(1 for item in row["breaks"] if item["missed_break"])
    kept["longest_episodes"] = row["longest_episodes"]
    return kept


def _reviewed(session: str) -> list[Interval]:
    extra = json.loads(REVIEWED.read_text(encoding="utf-8"))["commercials"]
    intervals = list(active_intervals(session))
    for row in extra:
        if row["session"] != session:
            continue
        intervals.append(
            Interval(
                start=float(row["start_s"]),
                end=float(row["end_s"]),
                event_class="commercial",
                desired_action="mute",
                confidence="reviewed",
            )
        )
    return intervals


def _focus(session: str, times: np.ndarray, scores: np.ndarray) -> dict:
    coverage = coverage_by_session()[session]
    spans = playback_from_decisions(coverage, decisions(times.tolist(), scores.tolist(), **CONTROLLER))
    found = {name: round(_overlap(spans, [bounds]), 3) for name, bounds in FOCUS.get(session, {}).items()}
    found["named_desk_list_s"] = round(_overlap(spans, DESK_SPANS.get(session, [])), 3)
    return found


def _playback_cover_mask(times: np.ndarray, probs: np.ndarray, session: str) -> np.ndarray:
    coverage = coverage_by_session()[session]
    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    spans = playback_from_decisions(coverage, rows)
    covered = np.zeros(len(times), dtype=bool)
    for i, t in enumerate(times):
        tt = float(t)
        for span in spans:
            if span.state == "covered" and span.start <= tt < span.end:
                covered[i] = True
                break
    return covered


def audit_edges(session: str, times: np.ndarray, probs: np.ndarray) -> list[dict]:
    ads = target_commercials(active_intervals(session))
    desks = DESK_SPANS.get(session, [])
    covered = _playback_cover_mask(times, probs, session)
    edges = []
    for i, (a0, a1) in enumerate(ads):
        # samples in (a1, a1+HORIZON]
        after = (times > a1) & (times <= a1 + HORIZON_AFTER)
        if not after.any():
            continue
        t_after = times[after]
        p_after = probs[after]
        c_after = covered[after]
        # how long until p drops below 0.5 / cover ends
        cool_p = None
        cool_cover = None
        for tt, pp, cc in zip(t_after, p_after, c_after):
            if cool_p is None and pp < 0.5:
                cool_p = float(tt - a1)
            if cool_cover is None and not cc:
                cool_cover = float(tt - a1)
            if cool_p is not None and cool_cover is not None:
                break
        # sticky: still covering at +2s / +5s / +10s
        def still(at_s: float, arr_t, arr_c):
            m = np.abs(arr_t - (a1 + at_s))
            if not len(m):
                return None
            j = int(np.argmin(m))
            if abs(float(arr_t[j]) - (a1 + at_s)) > 0.4:
                return None
            return bool(arr_c[j])

        # what gold is in first 10s after
        desk_s = 0.0
        prog_s = 0.0
        next_ad_s = 0.0
        for tt0, tt1 in zip(t_after[:-1], t_after[1:]):
            if tt0 > a1 + 10:
                break
            dt = float(tt1 - tt0)
            mid = float(tt0)
            if any(d0 <= mid < d1 for d0, d1 in desks):
                desk_s += dt
            elif any(b0 <= mid < b1 for b0, b1 in ads):
                next_ad_s += dt
            else:
                prog_s += dt
        # p stats in first 5s after
        first5 = (times > a1) & (times <= a1 + 5.0)
        sticky = bool(cool_cover is None or cool_cover > 2.0)
        into_desk = desk_s >= 1.0 and sticky
        into_prog = prog_s >= 1.0 and sticky and desk_s < 1.0
        edges.append(
            {
                "session": session,
                "break": i,
                "ad_start": round(a0, 2),
                "ad_end": round(a1, 2),
                "ad_len": round(a1 - a0, 2),
                "cool_p_s": None if cool_p is None else round(cool_p, 2),
                "cool_cover_s": None if cool_cover is None else round(cool_cover, 2),
                "never_cooled_in_30s": cool_cover is None,
                "cover_at_2s": still(2.0, t_after, c_after),
                "cover_at_5s": still(5.0, t_after, c_after),
                "cover_at_10s": still(10.0, t_after, c_after),
                "p_mean_5s": None if not first5.any() else round(float(np.mean(probs[first5])), 4),
                "frac_p_ge_0.9_5s": None if not first5.any() else round(float((probs[first5] >= 0.9).mean()), 4),
                "post10_desk_s": round(desk_s, 2),
                "post10_prog_s": round(prog_s, 2),
                "post10_ad_s": round(next_ad_s, 2),
                "sticky_gt2s": sticky,
                "sticky_into_desk": into_desk,
                "sticky_into_program": into_prog,
            }
        )
    return edges


def apply_cooldown(times: np.ndarray, probs: np.ndarray, ads: list[tuple[float, float]], cool_s: float) -> np.ndarray:
    """Force p=0 for cool_s after each gold ad end (past-only relative to ad_end)."""
    out = np.array(probs, dtype=np.float64, copy=True)
    for _a0, a1 in ads:
        m = (times > a1) & (times <= a1 + cool_s)
        out[m] = 0.0
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_edges = []
    for session in SESSIONS:
        pred = np.load(FROZEN / f"{session}.npz")
        edges = audit_edges(session, pred["t"], pred["p"])
        all_edges.extend(edges)
        sticky = sum(1 for e in edges if e["sticky_gt2s"])
        into_desk = sum(1 for e in edges if e["sticky_into_desk"])
        into_prog = sum(1 for e in edges if e["sticky_into_program"])
        print(
            f"{session} edges={len(edges)} sticky>2s={sticky} into_desk={into_desk} into_prog={into_prog}",
            flush=True,
        )
        for e in edges:
            if e["sticky_into_desk"] or e["sticky_into_program"] or e["never_cooled_in_30s"]:
                print(
                    f"  br{e['break']} end={e['ad_end']} cool_cover={e['cool_cover_s']} "
                    f"at2/5/10={e['cover_at_2s']}/{e['cover_at_5s']}/{e['cover_at_10s']} "
                    f"desk_s={e['post10_desk_s']} prog_s={e['post10_prog_s']} "
                    f"p5={e['p_mean_5s']}",
                    flush=True,
                )

    summary = {
        "n_edges": len(all_edges),
        "sticky_gt2s": sum(1 for e in all_edges if e["sticky_gt2s"]),
        "sticky_into_desk": sum(1 for e in all_edges if e["sticky_into_desk"]),
        "sticky_into_program": sum(1 for e in all_edges if e["sticky_into_program"]),
        "never_cooled_in_30s": sum(1 for e in all_edges if e["never_cooled_in_30s"]),
        "median_cool_cover_s": None
        if not any(e["cool_cover_s"] is not None for e in all_edges)
        else round(
            float(np.median([e["cool_cover_s"] for e in all_edges if e["cool_cover_s"] is not None])),
            2,
        ),
        "cover_at_2s_rate": round(
            float(np.mean([1 if e["cover_at_2s"] else 0 for e in all_edges if e["cover_at_2s"] is not None])),
            3,
        ),
        "cover_at_5s_rate": round(
            float(np.mean([1 if e["cover_at_5s"] else 0 for e in all_edges if e["cover_at_5s"] is not None])),
            3,
        ),
    }
    print("\nAUDIT SUMMARY", json.dumps(summary, indent=2), flush=True)

    # KPI: frozen + each cool-down
    report = {
        "controller": CONTROLLER,
        "audit_summary": summary,
        "edges": all_edges,
        "runs": {},
    }
    cool_options = (0.0,) + COOL_S_OPTIONS
    for cool_s in cool_options:
        name = "frozen" if cool_s == 0 else f"cooldown_{int(cool_s)}s"
        games = []
        reviewed = []
        focus = {}
        for session in SESSIONS:
            pred = np.load(FROZEN / f"{session}.npz")
            times = pred["t"]
            scores = pred["p"].astype(np.float64)
            if cool_s > 0:
                ads = target_commercials(active_intervals(session))
                scores = apply_cooldown(times, scores, ads, cool_s)
            games.append(_round(_score_array(session, times, scores)))
            games[-1]["session"] = session
            reviewed.append(_round(_score_array(session, times, scores, _reviewed(session))))
            reviewed[-1]["session"] = session
            focus[session] = _focus(session, times, scores)
            print(
                f"{name} {session} cov={games[-1]['commercial_coverage']:.3f} "
                f"prog={games[-1]['program_covered_s']:.1f}s "
                f"rate={games[-1]['false_mutes_per_hour']:.2f}/h "
                f"long={games[-1]['longest_false_mute_s']:.1f}s "
                f"desk={focus[session].get('named_desk_list_s')}",
                flush=True,
            )
        cov = sum(g["commercial_covered_s"] for g in games)
        tot = sum(g["commercial_s"] for g in games)
        prog = sum(g["program_covered_s"] for g in games)
        agg = {
            "commercial_coverage": round(cov / tot, 4),
            "commercial_covered_s": round(cov, 1),
            "program_covered_s": round(prog, 1),
            "false_mute_episodes": sum(g["false_mute_episodes"] for g in games),
            "longest_false_mute_s": round(max(g["longest_false_mute_s"] for g in games), 2),
            "desk_span_covered_s": round(sum(focus[s].get("named_desk_list_s", 0) for s in SESSIONS), 1),
            "focus": focus,
        }
        report["runs"][name] = {
            "cool_s": cool_s,
            "original_gold": games,
            "reviewed_boundaries": reviewed,
            "aggregate": agg,
        }
        print("AGG", name, agg, flush=True)

    (OUT / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (OUT / "edges.jsonl").open("w", encoding="utf-8") as fh:
        for e in all_edges:
            fh.write(json.dumps(e) + "\n")
    print("wrote", OUT / "result.json", flush=True)


if __name__ == "__main__":
    main()
