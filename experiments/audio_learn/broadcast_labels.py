"""Broadcast vs non-broadcast label layer.

Product: play broadcast, mute non-broadcast.

Builds accepted labels from gold + reviewed + desk surveys, mines Prime cover
episodes that gold still calls program, auto-labels high-confidence spots via
transcript keywords, and writes a human queue for the rest.

Does not touch ohush_live, holdouts, or truth_events.jsonl.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.splits import CALIBRATE, EVAL, TRAIN
from experiments.audio_learn.studio_fit import CONTROLLER, DESK_SPANS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals, coverage_by_session
from tools.gpu_lab.audio_load import load_coverage

DATA = Path(r"C:\OHushData\gpu_lab\audio_learn")
FROZEN = DATA / "predictions" / "frozen"
OUT = DATA / "broadcast_labels"
REVIEWED = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\OHUSH_STUDIO_HEAD_001\reviewed_boundaries.json")
VERIFIED = DATA / "studio_survey" / "verified_spans.json"
SEMANTIC = DATA / "semantic_probe" / "rows.jsonl"

# sessions we label now (product eval + train context). Holdouts refused by inventory.
SESSIONS = tuple(dict.fromkeys([*EVAL, *CALIBRATE, *TRAIN]))

AD_RE = re.compile(
    r"\b("
    r"chili'?s|mcdonald|mccrispy|draft\s*kings|fanatics|amex|american express|platinum|"
    r"toyota|chevrolet|chevy|honda|ford|geico|progressive|state farm|verizon|att|t-mobile|"
    r"bud light|michelob|miller lite|coca[- ]cola|pepsi|subway|wendy'?s|burger king|"
    r"nfl\+|peacock|espn\+|disney\+|paramount\+|hulu|"
    r"bottomless|limited time|order now|learn more|visit|sponsored by|brought to you|"
    r"terms apply|gambling problem|must be 21"
    r")\b",
    re.I,
)
SHOW_RE = re.compile(
    r"\b("
    r"first down|second down|third down|fourth down|touchdown|field goal|incomplete|"
    r"interception|punt|snap|blitz|yard line|play action|audible|no huddle|"
    r"welcome back|halftime|postgame|injury report|around the league"
    r")\b",
    re.I,
)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _overlaps_any(a0: float, a1: float, spans: list[tuple[float, float]], min_s: float = 0.5) -> bool:
    return any(_overlap(a0, a1, b0, b1) >= min_s for b0, b1 in spans)


def _label(
    *,
    session: str,
    start_s: float,
    end_s: float,
    bucket: str,
    kind: str,
    source: str,
    confidence: str,
    note: str,
    desired_action: str | None = None,
) -> dict:
    if bucket == "broadcast":
        action = "play"
    elif bucket == "non_broadcast":
        action = "mute"
    else:
        action = desired_action or "unknown"
    return {
        "session": session,
        "start_s": round(float(start_s), 3),
        "end_s": round(float(end_s), 3),
        "dur_s": round(float(end_s - start_s), 3),
        "bucket": bucket,
        "kind": kind,
        "desired_action": action,
        "source": source,
        "confidence": confidence,
        "note": note,
        "status": "accepted" if confidence in {"certain", "high"} else "pending",
    }


def _from_gold() -> list[dict]:
    rows = []
    for session in SESSIONS:
        for a0, a1 in target_commercials(active_intervals(session)):
            rows.append(
                _label(
                    session=session,
                    start_s=a0,
                    end_s=a1,
                    bucket="non_broadcast",
                    kind="gold_ad_break",
                    source="truth_events",
                    confidence="certain",
                    note="gold commercial interval",
                )
            )
    return rows


def _from_reviewed() -> list[dict]:
    doc = json.loads(REVIEWED.read_text(encoding="utf-8"))
    rows = []
    for row in doc.get("commercials") or []:
        rows.append(
            _label(
                session=row["session"],
                start_s=row["start_s"],
                end_s=row["end_s"],
                bucket="non_broadcast",
                kind=row.get("kind") or "standalone_spot",
                source="reviewed_boundaries",
                confidence="certain",
                note=str(row.get("note") or ""),
            )
        )
    for row in doc.get("kept_as_program") or []:
        rows.append(
            _label(
                session=row["session"],
                start_s=row["start_s"],
                end_s=row["end_s"],
                bucket="broadcast",
                kind=row.get("kind") or "in_show_sponsorship",
                source="reviewed_boundaries",
                confidence="certain",
                note=str(row.get("note") or ""),
            )
        )
    return rows


def _from_desks() -> list[dict]:
    rows = []
    for session, spans in DESK_SPANS.items():
        for i, (a0, a1) in enumerate(spans):
            rows.append(
                _label(
                    session=session,
                    start_s=a0,
                    end_s=a1,
                    bucket="broadcast",
                    kind="desk",
                    source="desk_spans",
                    confidence="certain",
                    note=f"Prime desk span #{i}",
                )
            )
    if VERIFIED.is_file():
        for row in json.loads(VERIFIED.read_text(encoding="utf-8")).get("spans") or []:
            rows.append(
                _label(
                    session=row["session"],
                    start_s=row["start_s"],
                    end_s=row["end_s"],
                    bucket="broadcast",
                    kind=row.get("kind") or "studio_desk",
                    source="verified_spans",
                    confidence="certain",
                    note=str(row.get("note") or ""),
                )
            )
    return rows


def _cover_episodes(session: str) -> list[tuple[float, float]]:
    pred = np.load(FROZEN / f"{session}.npz")
    rows = decisions(pred["t"].tolist(), pred["p"].tolist(), **CONTROLLER)
    out: list[tuple[float, float]] = []
    cur = None
    for row in rows:
        t = float(row["available_at"])
        if row["action"] == "cover":
            if cur is None:
                cur = [t, t]
            else:
                cur[1] = t
        elif cur is not None:
            out.append((cur[0], cur[1] + 0.25))
            cur = None
    if cur is not None:
        out.append((cur[0], cur[1] + 0.25))
    return out


def _subtract(span: tuple[float, float], blockers: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return pieces of span not covered by blockers."""
    pieces = [span]
    for b0, b1 in sorted(blockers):
        next_pieces = []
        for a0, a1 in pieces:
            if b1 <= a0 or b0 >= a1:
                next_pieces.append((a0, a1))
                continue
            if a0 < b0:
                next_pieces.append((a0, b0))
            if b1 < a1:
                next_pieces.append((b1, a1))
        pieces = next_pieces
    return [(a0, a1) for a0, a1 in pieces if a1 - a0 >= 2.5]


def _mine_eval_candidates(accepted: list[dict]) -> list[dict]:
    """Residual covered program: cover minus non_broadcast, then desk-aware hypotheses."""
    non_b = [(r["session"], r["start_s"], r["end_s"]) for r in accepted if r["bucket"] == "non_broadcast"]
    desks = [
        (r["session"], r["start_s"], r["end_s"])
        for r in accepted
        if r["kind"]
        in {
            "desk",
            "studio_desk",
            "halftime_desk",
            "postgame_desk",
            "pregame_desk",
            "highlights",
            "host_bridge",
            "in_show_sponsorship",
            "show_auto",
            "show_return",
        }
    ]
    cands = []
    for session in EVAL:
        if not (FROZEN / f"{session}.npz").is_file():
            continue
        session_non = [(a, b) for s, a, b in non_b if s == session]
        session_desk = [(a, b) for s, a, b in desks if s == session]
        pred = np.load(FROZEN / f"{session}.npz")
        for a0, a1 in _cover_episodes(session):
            residuals = _subtract((a0, a1), session_non)
            for r0, r1 in residuals:
                dur = r1 - r0
                desk_ol = sum(_overlap(r0, r1, b0, b1) for b0, b1 in session_desk)
                mid = 0.5 * (r0 + r1)
                i = int(np.argmin(np.abs(pred["t"] - mid)))
                p_mid = float(pred["p"][i])
                # sticky tail if residual starts within 1s of a non_broadcast end
                after_ad = any(abs(r0 - b1) <= 1.0 or (b1 <= r0 <= b1 + 15.0) for b0, b1 in session_non)
                if desk_ol >= 2.0:
                    hyp = "desk_fp_already_labeled_broadcast"
                elif after_ad and desk_ol < 1.0:
                    hyp = "post_ad_show_return"
                else:
                    hyp = "possible_missing_non_broadcast_or_desk"
                cands.append(
                    {
                        "session": session,
                        "start_s": round(r0, 3),
                        "end_s": round(r1, 3),
                        "dur_s": round(dur, 3),
                        "p_mid": round(p_mid, 4),
                        "gold_ad_overlap_s": 0.0,
                        "desk_overlap_s": round(desk_ol, 3),
                        "parent_cover": [round(a0, 3), round(a1, 3)],
                        "hypothesis": hyp,
                    }
                )
    cands.sort(key=lambda r: -r["dur_s"])
    return cands


def _semantic_hints() -> dict[tuple[str, float], str]:
    hints = {}
    if not SEMANTIC.is_file():
        return hints
    for line in SEMANTIC.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        hints[(row["session"], float(row["t"]))] = str(row.get("text") or "")
    return hints


def _classify_text(text: str) -> tuple[str | None, str]:
    if not text or not text.strip():
        return None, "empty transcript"
    ad_hits = AD_RE.findall(text)
    show_hits = SHOW_RE.findall(text)
    if ad_hits and not show_hits:
        return "non_broadcast", f"ad keywords: {sorted(set(x.lower() for x in ad_hits))[:6]}"
    if show_hits and not ad_hits:
        return "broadcast", f"show keywords: {sorted(set(x.lower() for x in show_hits))[:6]}"
    if ad_hits and show_hits:
        return None, f"mixed ad={sorted(set(x.lower() for x in ad_hits))[:4]} show={sorted(set(x.lower() for x in show_hits))[:4]}"
    return None, "no strong keywords"


def _whisper_window(session: str, t0: float, t1: float, model) -> str:
    # cap 12s around mid for speed
    mid = 0.5 * (t0 + t1)
    a0 = max(t0, mid - 6.0)
    a1 = min(t1, mid + 6.0)
    if a1 - a0 < 2.0:
        a0, a1 = t0, min(t1, t0 + 8.0)
    audio = load_coverage(session, a0, a1)
    segments, _info = model.transcribe(audio, vad_filter=True, beam_size=1)
    return " ".join(seg.text.strip() for seg in segments if seg.text.strip())


def _auto_label_candidates(cands: list[dict], whisper: bool = True) -> tuple[list[dict], list[dict]]:
    """Return (auto_accepted, human_queue)."""
    hints = _semantic_hints()
    model = None
    if whisper:
        from faster_whisper import WhisperModel

        model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)

    auto: list[dict] = []
    queue: list[dict] = []

    # desk-overlapping cover → confirm broadcast (already in desks, skip new label) but note
    for cand in cands:
        if cand["hypothesis"] == "desk_fp_already_labeled_broadcast":
            queue.append(
                {
                    **cand,
                    "ask": "confirm_broadcast_desk",
                    "suggested_bucket": "broadcast",
                    "suggested_kind": "desk",
                    "reason": "cover overlaps known desk span; already accepted as broadcast",
                    "needs_human": False,
                    "auto_status": "covered_by_desk_label",
                }
            )
            continue

        if cand["hypothesis"] == "post_ad_show_return" and cand["dur_s"] <= 20.0:
            lab = _label(
                session=cand["session"],
                start_s=cand["start_s"],
                end_s=cand["end_s"],
                bucket="broadcast",
                kind="show_return",
                source="auto_post_ad_tail",
                confidence="high",
                note="sticky cover after non_broadcast end; treat as broadcast return",
            )
            auto.append(lab)
            queue.append(
                {
                    **cand,
                    "ask": "optional_confirm_show_return",
                    "suggested_bucket": "broadcast",
                    "suggested_kind": "show_return",
                    "needs_human": False,
                    "auto_status": "accepted_show_return",
                    "text": "",
                    "classify_reason": "post-ad residual cover <=20s",
                }
            )
            print(
                f"cand {cand['session'][-6:]} {cand['start_s']:.0f}-{cand['end_s']:.0f} "
                f"{cand['dur_s']:.1f}s → accepted_show_return",
                flush=True,
            )
            continue

        text = ""
        # reuse semantic probe text if within 3s
        for (session, t), hint in hints.items():
            if session == cand["session"] and abs(t - 0.5 * (cand["start_s"] + cand["end_s"])) < 3.0:
                text = hint
                break
        source = "semantic_probe" if text else None
        if not text and model is not None:
            try:
                started = time.perf_counter()
                text = _whisper_window(cand["session"], cand["start_s"], cand["end_s"], model)
                source = f"whisper_base.en:{time.perf_counter() - started:.2f}s"
            except Exception as exc:  # noqa: BLE001
                text = ""
                source = f"whisper_failed:{exc}"

        bucket, reason = _classify_text(text)
        item = {
            **cand,
            "text": text[:240],
            "text_source": source,
            "classify_reason": reason,
            "suggested_bucket": bucket,
        }
        # Auto-accept only clear non_broadcast standalone spots (product mute) with length >= 8s
        if bucket == "non_broadcast" and cand["dur_s"] >= 8.0 and cand["desk_overlap_s"] < 1.0:
            lab = _label(
                session=cand["session"],
                start_s=cand["start_s"],
                end_s=cand["end_s"],
                bucket="non_broadcast",
                kind="standalone_spot_auto",
                source="auto_transcript",
                confidence="high",
                note=f"{reason}; text={text[:120]}",
            )
            auto.append(lab)
            item["needs_human"] = False
            item["auto_status"] = "accepted_non_broadcast"
            item["ask"] = "optional_boundary_tighten"
        elif bucket == "broadcast" and cand["dur_s"] >= 6.0:
            # likely missing desk / show — accept as broadcast for ontology completeness
            lab = _label(
                session=cand["session"],
                start_s=cand["start_s"],
                end_s=cand["end_s"],
                bucket="broadcast",
                kind="show_auto",
                source="auto_transcript",
                confidence="high",
                note=f"{reason}; text={text[:120]}",
            )
            auto.append(lab)
            item["needs_human"] = False
            item["auto_status"] = "accepted_broadcast"
            item["ask"] = "optional_confirm_show"
        else:
            item["needs_human"] = True
            item["auto_status"] = "queued"
            item["ask"] = "label_broadcast_or_non_broadcast"
            if bucket:
                item["suggested_kind"] = "standalone_spot" if bucket == "non_broadcast" else "desk_or_show"
            else:
                item["suggested_kind"] = "unknown"
        queue.append(item)
        print(
            f"cand {cand['session'][-6:]} {cand['start_s']:.0f}-{cand['end_s']:.0f} "
            f"{cand['dur_s']:.1f}s p={cand['p_mid']:.2f} → {item['auto_status']} "
            f"{(text or '')[:70]}",
            flush=True,
        )
    return auto, queue


def _dedupe(rows: list[dict]) -> list[dict]:
    key = lambda r: (r["session"], r["start_s"], r["end_s"], r["bucket"], r["kind"], r["source"])
    seen = set()
    out = []
    for row in rows:
        k = key(row)
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def _human_decided_keys() -> set[tuple]:
    path = OUT / "human_decisions.jsonl"
    keys: set[tuple] = set()
    if not path.is_file():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        keys.add((row["session"], round(float(row["start_s"]), 3), round(float(row["end_s"]), 3)))
    return keys


def _write_human_sheet(queue: list[dict]) -> str:
    decided = _human_decided_keys()
    need = [
        q
        for q in queue
        if q.get("needs_human")
        and (q["session"], round(float(q["start_s"]), 3), round(float(q["end_s"]), 3)) not in decided
    ]
    lines = [
        "# Human broadcast label queue",
        "",
        "Product: **play broadcast / mute non_broadcast**.",
        "",
        "For each row, set `decision` to `broadcast` or `non_broadcast` (or `skip`).",
        "Optional: tighten `start_s` / `end_s`. Append to `human_decisions.jsonl` in this folder, then re-run.",
        "",
        f"Pending: **{len(need)}**",
        "",
    ]
    for i, q in enumerate(need, 1):
        lines.append(
            f"## {i}. `{q['session']}` {q['start_s']:.1f}–{q['end_s']:.1f}s ({q['dur_s']:.1f}s)"
        )
        lines.append(f"- frozen p_mid: {q.get('p_mid')}")
        lines.append(f"- desk overlap: {q.get('desk_overlap_s')}s · gold-ad overlap: {q.get('gold_ad_overlap_s')}s")
        lines.append(f"- suggested: {q.get('suggested_bucket')} ({q.get('classify_reason')})")
        lines.append(f"- text: {q.get('text') or '(none)'}")
        lines.append(
            f"- decision template: "
            f'`{{"session":"{q["session"]}","start_s":{q["start_s"]},"end_s":{q["end_s"]},'
            f'"decision":"broadcast|non_broadcast|skip","note":""}}`'
        )
        lines.append("")
    return "\n".join(lines)


def _merge_human(accepted: list[dict]) -> list[dict]:
    path = OUT / "human_decisions.jsonl"
    if not path.is_file():
        return accepted
    extra = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        decision = str(row.get("decision") or "").strip().lower()
        if decision in {"skip", ""}:
            continue
        if decision not in {"broadcast", "non_broadcast"}:
            raise SystemExit(f"bad decision in human_decisions.jsonl: {decision}")
        extra.append(
            _label(
                session=row["session"],
                start_s=float(row["start_s"]),
                end_s=float(row["end_s"]),
                bucket=decision,
                kind=str(row.get("kind") or ("standalone_spot" if decision == "non_broadcast" else "show")),
                source="human",
                confidence="certain",
                note=str(row.get("note") or "owner decision"),
            )
        )
    print(f"merged human decisions={len(extra)}", flush=True)
    return _dedupe(accepted + extra)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    accepted = _dedupe(_from_gold() + _from_reviewed() + _from_desks())
    print(f"seed accepted={len(accepted)}", flush=True)

    cands = _mine_eval_candidates(accepted)
    print(f"eval cover candidates={len(cands)}", flush=True)
    # prioritize: long unexplained first, cap whisper work
    returns = [c for c in cands if c["hypothesis"] == "post_ad_show_return"]
    unexplained = [c for c in cands if c["hypothesis"] == "possible_missing_non_broadcast_or_desk"]
    deskish = [c for c in cands if c["hypothesis"] == "desk_fp_already_labeled_broadcast"]
    work = returns[:40] + unexplained[:40] + deskish[:15]
    print(
        f"work returns={len(returns[:40])} unexplained={len(unexplained[:40])} desk={len(deskish[:15])}",
        flush=True,
    )
    auto, queue = _auto_label_candidates(work, whisper=True)
    accepted = _dedupe(accepted + auto)
    accepted = _merge_human(accepted)

    summary = {
        "product_goal": "play broadcast; mute non_broadcast",
        "sessions": list(SESSIONS),
        "n_accepted": len(accepted),
        "n_accepted_broadcast": sum(1 for r in accepted if r["bucket"] == "broadcast"),
        "n_accepted_non_broadcast": sum(1 for r in accepted if r["bucket"] == "non_broadcast"),
        "accepted_seconds": {
            "broadcast": round(sum(r["dur_s"] for r in accepted if r["bucket"] == "broadcast"), 1),
            "non_broadcast": round(sum(r["dur_s"] for r in accepted if r["bucket"] == "non_broadcast"), 1),
        },
        "n_candidates_scored": len(work),
        "n_auto_from_transcript": len(auto),
        "n_human_pending": sum(1 for q in queue if q.get("needs_human")),
        "sources": sorted({r["source"] for r in accepted}),
        "rule": (
            "Standalone spot with heard return = non_broadcast. "
            "Host talking through sponsor = broadcast. "
            "Desk/live/show = broadcast. Gold ad breaks = non_broadcast."
        ),
    }

    (OUT / "labels_accepted.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in accepted), encoding="utf-8"
    )
    (OUT / "candidates_queue.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in queue), encoding="utf-8"
    )
    (OUT / "HUMAN_QUEUE.md").write_text(_write_human_sheet(queue), encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "README.md").write_text(
        "\n".join(
            [
                "# Broadcast labels",
                "",
                summary["rule"],
                "",
                "## Files",
                "- `labels_accepted.jsonl` — use these (certain/high)",
                "- `candidates_queue.jsonl` — full candidate audit",
                "- `HUMAN_QUEUE.md` — only rows that still need you",
                "- `human_decisions.jsonl` — drop your decisions here (optional next)",
                "",
                "## Apply a decision",
                "Append JSONL lines with `decision` = broadcast|non_broadcast|skip.",
                "Re-run merge later to fold them into accepted.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2), flush=True)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
