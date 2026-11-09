"""Write the NFL75_001 evidence pack. Does not train, mute, or open a holdout.

    python -m experiments.nfl75
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from experiments.ledger import TRUTH_PATH, sha256_file
from experiments.measurement.metrics import target_commercials

from experiments.nfl75.causal import audit_availability_file
from experiments.nfl75.contract import EXPERIMENT, MERGE_RULE, THRESHOLDS
from experiments.nfl75.diagnose import bottleneck, oracle_playback
from experiments.nfl75.inventory import (
    CAUSAL_AVAILABILITY,
    PRIME_DEV,
    active_intervals,
    build_inventory,
    coverage_by_session,
    excluded_ranges,
    wall_gaps,
)
from experiments.nfl75.score import aggregate, always_play, score_product

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/NFL75_001"


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _public(row: dict) -> dict:
    keep = {
        "session": row.get("session"),
        "oracle": row.get("oracle"),
        "deployable": False,
        "evaluable": row["evaluable"],
        "blockers": row["blockers"],
        "commercial_s": _round(row["commercial_s"], 3),
        "commercial_covered_s": _round(row["commercial_covered_s"], 3),
        "commercial_missed_s": _round(row["commercial_missed_s"], 3),
        "commercial_missing_s": _round(row["commercial_missing_s"], 3),
        "commercial_coverage": _round(row["commercial_coverage"], 4),
        "program_s": _round(row["program_s"], 3),
        "program_covered_s": _round(row["program_covered_s"], 3),
        "program_hours": _round(row["program_hours"], 4),
        "false_mute_episodes": row["false_mute_episodes"],
        "false_mutes_per_hour": _round(row["false_mutes_per_hour"], 4),
        "longest_false_mute_s": _round(row["longest_false_mute_s"], 3),
        "program_hidden_per_hour": _round(row["program_hidden_per_hour"], 4),
        "unsure_s": _round(row["unsure_s"], 3),
        "excluded_unmarked_s": _round(row["excluded_unmarked_s"], 3),
        "wall_gap_s": _round(row["wall_gap_s"], 3),
        "acceptance": row["acceptance"],
    }
    if "episodes" in row:
        keep["episodes"] = row["episodes"]
    if "breaks" in row:
        keep["break_count"] = len(row["breaks"])
    return keep


def _git() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def score_champion() -> dict:
    coverage = coverage_by_session()
    gaps = wall_gaps()
    per_session = []
    oracle_rows = []
    for session in PRIME_DEV:
        span = coverage[session]
        intervals = active_intervals(session)
        playback = always_play(span)
        dropped = excluded_ranges(session, intervals)
        joint = score_product(
            span,
            intervals,
            playback,
            session=session,
            excluded_ranges=dropped,
            wall_gap_s=gaps.get(session, 0.0),
            audio_present=False,
        )
        ads = target_commercials(intervals)
        endings_play = oracle_playback(span, playback, ads, "perfect_endings")
        starts_play = oracle_playback(span, playback, ads, "perfect_starts")
        endings = score_product(
            span,
            intervals,
            endings_play,
            session=session,
            oracle=True,
            excluded_ranges=dropped,
            wall_gap_s=gaps.get(session, 0.0),
        )
        starts = score_product(
            span,
            intervals,
            starts_play,
            session=session,
            oracle=True,
            excluded_ranges=dropped,
            wall_gap_s=gaps.get(session, 0.0),
        )
        per_session.append(joint)
        oracle_rows.append(
            {
                "session": session,
                "joint": _public(joint),
                "perfect_endings": _public(endings),
                "perfect_starts": _public(starts),
                "bottleneck": bottleneck(joint, endings, starts),
            }
        )
    combined = aggregate(per_session, oracle=False)
    return {"sessions": oracle_rows, "prime_combined_champion": _public(combined)}


def _fmt_pct(value) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * value:.1f}%"


def _fmt(value, suffix="") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}{suffix}"
    return f"{value}{suffix}"


def render_report(inventory: dict, stamps: dict, champion: dict, code_hash: str) -> str:
    combined = champion["prime_combined_champion"]
    acceptance = combined["acceptance"]["pass"]
    lines = [
        "# NFL75_001",
        "",
        "Product score only. The 99.99% ladder, the champion rule, the gold labels, and the sealed recordings were not changed. Nothing here is an authorized mute.",
        "",
        "## Gate",
        "",
        f"Prime development champion (always play): **{'PASS' if acceptance else 'FAIL'}**.",
        "",
        "The causal check on the existing fingerprint reader is **FAIL**. Further detector experiments stop here.",
        "",
        "## Measured champion, both labeled Prime games",
        "",
        "These are the authorized decisions: play. They do not look ahead. Oracle rows are not in this table.",
        "",
        "| Metric | Measured | Acceptance |",
        "| --- | ---: | --- |",
        f"| Ad coverage | {_fmt_pct(combined['commercial_coverage'])} | ≥75% |",
        f"| False mutes / hour | {_fmt(combined['false_mutes_per_hour'])} | <1 |",
        f"| Longest false mute | {_fmt(combined['longest_false_mute_s'], 's')} | <10s |",
        f"| Program hidden / hour | {_fmt(combined['program_hidden_per_hour'], 's')} | <5s |",
        "",
        f"Eligible commercial seconds: {combined['commercial_s']}. Eligible program seconds: {combined['program_s']}. False-mute episodes: {combined['false_mute_episodes']}.",
        "",
        "No confidence interval. A rate is episodes divided by program hours. Audio seconds are not independent trials, and a zero on tape that never mutes is not a bound on a future detector.",
        "",
        "Per game:",
        "",
    ]
    for row in champion["sessions"]:
        joint = row["joint"]
        lines.append(
            f"- `{row['session']}`: coverage {_fmt_pct(joint['commercial_coverage'])}, "
            f"commercial {joint['commercial_s']}s, program {joint['program_s']}s, "
            f"breaks {joint['break_count']}, false mutes {joint['false_mute_episodes']}, "
            f"acceptance {'PASS' if joint['acceptance']['pass'] else 'FAIL'}."
        )
    lines.extend(
        [
            "",
            "## Bottleneck on the causal champion",
            "",
            "The champion never covers. Perfect commercial endings and perfect commercial starts recover no advertising, because both oracles need a real cover to repair. Hidden football is zero. The bottleneck is the start: there is no authorized commercial start. The return cannot be separated until a cover exists.",
            "",
            "Count 10, the waveform confirm, and the 180-second holds were not rescored. Those streams can read future audio, so they are not NFL75 measurements.",
            "",
            "## Causal verification",
            "",
            f"Stamp order on `{stamps['rows']}` rows of `causal_availability.jsonl`: **{'PASS' if stamps['pass'] else 'FAIL'}**.",
            "That check only confirms each row's `available_at` is at or after `sample_max_consumed_at`, which is at or after the query end. It does not prove the hash would survive deleting later audio.",
            "",
            "Prefix invariance of the fingerprint reader: **FAIL**, already measured in `docs/ohush/research/FINGERPRINT_CAUSAL_STREAM_001/REPORT.md`. Interior hashes still changed at a 7.989-second backward window. `docs/ohush/research/UNIVERSAL_V1/decisions.jsonl` is not in this checkout (cited sha256 `08b1b8d9…86713`), so that file was not replayed. Recordings are not in this checkout either.",
            "",
            "A synthetic prefix check is in `tests/test_nfl75.py`. A causal hopper matches. A hopper that reads the last sample of the buffer does not.",
            "",
            "## Merge rule",
            "",
            MERGE_RULE,
            "",
            "## What is development, and what is not an exam set",
            "",
            inventory["why_no_untouched_prime_holdout"],
            "",
            f"Active gold marks in the ledger: {inventory['active_marks']} (the 13 October handoff says {inventory['documented_active_marks']}). Truth sha256 `{inventory['truth_sha256']}`.",
            "",
            "| Session | Broadcaster | Role | Inspected | Commercial s | Program s | Excluded s | Wall gap s |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in inventory["annotated"]:
        lines.append(
            f"| `{row['session']}` | {row['broadcaster']} | {row['role']} | {row['inspected_or_tuned']} | "
            f"{row['commercial_s']:.3f} | {row['program_s']:.3f} | {row['excluded_unmarked_s']:.3f} | {row['wall_gap_s']:.3f} |"
        )
    lines.extend(["", "Sealed, not opened:"])
    for row in inventory["sealed"]:
        lines.append(f"- `{row['session']}`")
    lines.extend(["", "Unlabeled, not an exam set:"])
    for row in inventory["unlabeled"]:
        lines.append(f"- `{row['session']}` ({row['broadcaster']})")
    lines.extend(
        [
            "",
            "## Exclusions",
            "",
            "Unsure gold is neither covered advertising nor hidden football. The September 9 NBC tape has an excluded gap between gold commercials: an AWS spot that was heard and left out of gold (`tools/gpu_lab/exclusions.json`). That gap is not program and not a covered ad.",
            "",
            "Wall gaps on 8 October (3395.1s) and 11 October night (1388.1s) are holes already removed from the elapsed clock. They are listed above and are not scored as silence. Missing playback would block acceptance rather than count as a mute or as a clean game. This champion replay has no missing playback.",
            "",
            "October 7 Hulu sums to 1503.839 commercial seconds on the current ledger. `docs/ohush/dataset_handoff/STATUS.md` and the Universal v1 results still say 1521.3. NFL75 uses the current ledger and does not relabel. The nine football games still sum to 17,648.4 commercial seconds.",
            "",
            "## Next experiment",
            "",
            "Do not train a model from this result. The authorized system covers none of the ads, and the fingerprint scores that cover some of them are not prefix-invariant.",
            "",
            "The next experiment is one prefix-invariant feature on `hush_20261008_205100` only: decisions for the first 30 minutes must match when that prefix is scored alone and when it is scored inside the full file. The feature value at time t may use audio at or before t, plus a stated latency that is included in `available_at`. Restore the recording locally to run it. The WAV files and the AST score cache are not in this checkout. If that check fails, stop. If it passes, run the same three-way split — joint, perfect endings, perfect starts — on that one stream, still on development tape, before any new classifier.",
            "",
            "## Receipts",
            "",
            f"- Experiment: {EXPERIMENT}",
            f"- Commit: `{_git()}`",
            f"- Scorer sha256: `{code_hash}`",
            f"- Truth sha256: `{inventory['truth_sha256']}`",
            f"- Thresholds: `{json.dumps(THRESHOLDS, sort_keys=True)}`",
            "- Command: `python -m unittest tests.test_nfl75`",
            "- Command: `python -m experiments.nfl75`",
            "- Live playback was not started. Holdouts were not opened. Gold was not written.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory()
    stamps = audit_availability_file(CAUSAL_AVAILABILITY)
    champion = score_champion()
    code_hash = sha256_file(Path(__file__).with_name("score.py"))
    payload = {
        "experiment": EXPERIMENT,
        "commit": _git(),
        "scorer_sha256": code_hash,
        "truth_sha256": sha256_file(TRUTH_PATH),
        "contract_sha256": sha256_file(Path(__file__).with_name("contract.py")),
        "thresholds": THRESHOLDS,
        "merge_rule": MERGE_RULE,
        "inventory": inventory,
        "causal_stamp_audit": stamps,
        "fingerprint_prefix_invariance": {
            "pass": False,
            "source": "docs/ohush/research/FINGERPRINT_CAUSAL_STREAM_001/REPORT.md",
            "reason": "Interior hashes still changed when more audio was supplied, including at 7.989 seconds.",
        },
        "champion": champion,
        "product_acceptance": champion["prime_combined_champion"]["acceptance"],
        "muted": False,
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    report = render_report(inventory, stamps, champion, code_hash)
    (OUT / "REPORT.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
