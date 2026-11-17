"""Rolling 1s-hop × evidence-width W experiment for autonomous transition labeling.

DRAFT-AID ONLY — not live mute accuracy.
Mute accuracy: python -m tools.windows_lab.farm_live_scorecard

Question
--------
If we keep 1-second *decisions* (so we can point at the transition frame) but feed
the model a rolling evidence window of width W ∈ {2,3,5,10}s, which W maximizes:

  1) 1s-frame draft-label match vs gold (ASR/lexicon/ollama — not the Mac muter)
  2) transition localization (how close the predicted change is to the gold cut)
  3) auto-lock rate (low uncertain → less human review)

Method
------
Gold map (from locked queue clips on the same take):
  each second inherits the locked bucket of the clip covering it.
  Gold transitions = seconds where bucket[t] != bucket[t-1].

For each W and each hop t (1s):
  evidence = ASR in [t - W/2, t + W/2]   (centered; use --causal for [t-W, t])
  optional mid still description
  model → bucket (lexicon cheap pass; --ollama for qwen)

Predicted transition = hop where bucket[t] != bucket[t-1] (ignore uncertain↔uncertain).

Match predicted cuts to gold cuts within τ seconds; report P/R/F1 and median |error|.

Usage
-----
  python -m tools.windows_lab.rolling_transition_probe
  python -m tools.windows_lab.rolling_transition_probe --ollama --widths 2,3,5,10
  python -m tools.windows_lab.rolling_transition_probe --causal --ollama
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir
from .farm_draft import (
    AD_HINT,
    SHOW_HINT,
    SPORTS_VISUAL,
    VISUAL_AD_HINT,
    apply_common_sense,
    transcript_for_window,
)

WIDTHS = (2, 3, 5, 10)
TOLERANCES = (1, 2, 3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _lexicon_bucket(text: str) -> str:
    ad = bool(AD_HINT.search(text or "") or VISUAL_AD_HINT.search(text or ""))
    prog = bool(SHOW_HINT.search(text or "") or SPORTS_VISUAL.search(text or ""))
    if ad and not prog:
        return "paid_ad"
    if prog and not ad:
        return "program"
    if ad and prog:
        return "uncertain"
    return "uncertain"


def _load_transcript(session_dir: Path) -> dict[str, Any]:
    cache = session_dir / "farm_transcript.json"
    if not cache.is_file():
        return {"ok": False, "segments": []}
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "segments": []}
    return data if data.get("ok") else {"ok": False, "segments": data.get("segments") or []}


def build_gold_maps(
    locked: list[dict[str, Any]],
    queue: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-session 1s gold label maps + transition times from adjacent locked clips."""
    by_session: dict[str, list[tuple[float, float, str, str]]] = defaultdict(list)
    for k in locked:
        clip = str(k.get("clip") or "")
        q = queue.get(clip) or {}
        sd = str(q.get("session_dir") or k.get("session_dir") or "")
        if not sd:
            continue
        try:
            t0 = float(k.get("t0") if k.get("t0") is not None else q.get("t0"))
            t1 = float(k.get("t1") if k.get("t1") is not None else q.get("t1"))
        except (TypeError, ValueError):
            continue
        bucket = str(k.get("bucket"))
        by_session[sd].append((t0, t1, bucket, clip))

    # Also fold multi-region judgments
    # (caller may pass none — handled in run_probe)

    maps: list[dict[str, Any]] = []
    for sd, rows in by_session.items():
        rows = sorted(rows, key=lambda r: r[0])
        if len(rows) < 1:
            continue
        t_min = min(r[0] for r in rows)
        t_max = max(r[1] for r in rows)
        # 1s gold labels
        labels: dict[int, str] = {}
        for t0, t1, bucket, _ in rows:
            a = int(t0)
            b = max(a + 1, int(t1))
            for sec in range(a, b):
                # later clip wins on overlap
                labels[sec] = bucket
        transitions = []
        secs = sorted(labels)
        for i in range(1, len(secs)):
            if secs[i] != secs[i - 1] + 1:
                continue  # gap in coverage
            if labels[secs[i]] != labels[secs[i - 1]]:
                transitions.append(
                    {
                        "t": float(secs[i]),
                        "from": labels[secs[i - 1]],
                        "to": labels[secs[i]],
                    }
                )
        if not labels:
            continue
        maps.append(
            {
                "session_dir": sd,
                "t_min": t_min,
                "t_max": t_max,
                "labels": {str(k): v for k, v in labels.items()},
                "transitions": transitions,
                "n_seconds": len(labels),
                "n_transitions": len(transitions),
            }
        )
    return maps


def _merge_judgment_regions(
    maps: list[dict[str, Any]],
    judgments: dict[str, Any],
    queue: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay multi-region human judgments onto gold maps when present."""
    by_sd = {m["session_dir"]: m for m in maps}
    for _id, row in judgments.items():
        if not isinstance(row, dict):
            continue
        regs = row.get("regions") or []
        if len(regs) < 2:
            continue
        q = queue.get(_id) or {}
        sd = str(row.get("session_dir") or q.get("session_dir") or "")
        if not sd:
            continue
        labels: dict[int, str] = {}
        for reg in regs:
            try:
                a = int(float(reg.get("start_s") or 0))
                b = max(a + 1, int(float(reg.get("end_s") or a + 1)))
                bucket = str(reg.get("bucket") or "")
            except (TypeError, ValueError):
                continue
            if bucket in {"", "uncertain"}:
                continue
            # judgment times are clip-relative; absolute = audio_start + relative
            base = float(q.get("t0") or row.get("t0") or 0)
            for sec in range(int(base) + a, int(base) + b):
                labels[sec] = bucket
        if len(labels) < 2:
            continue
        transitions = []
        secs = sorted(labels)
        for i in range(1, len(secs)):
            if secs[i] == secs[i - 1] + 1 and labels[secs[i]] != labels[secs[i - 1]]:
                transitions.append(
                    {"t": float(secs[i]), "from": labels[secs[i - 1]], "to": labels[secs[i]]}
                )
        m = by_sd.get(sd)
        if m is None:
            m = {
                "session_dir": sd,
                "t_min": float(min(labels)),
                "t_max": float(max(labels) + 1),
                "labels": {},
                "transitions": [],
                "n_seconds": 0,
                "n_transitions": 0,
            }
            maps.append(m)
            by_sd[sd] = m
        # merge — judgment wins
        merged = {int(k): v for k, v in m["labels"].items()}
        merged.update(labels)
        m["labels"] = {str(k): v for k, v in merged.items()}
        # rebuild transitions on merged
        transitions = []
        secs = sorted(merged)
        for i in range(1, len(secs)):
            if secs[i] == secs[i - 1] + 1 and merged[secs[i]] != merged[secs[i - 1]]:
                transitions.append(
                    {"t": float(secs[i]), "from": merged[secs[i - 1]], "to": merged[secs[i]]}
                )
        m["transitions"] = transitions
        m["n_seconds"] = len(merged)
        m["n_transitions"] = len(transitions)
        m["t_min"] = float(min(merged))
        m["t_max"] = float(max(merged) + 1)
    return maps


def match_transitions(
    gold: list[dict[str, Any]],
    pred: list[dict[str, Any]],
    *,
    tau: float,
) -> dict[str, float]:
    """Greedy 1:1 match within tau seconds."""
    used_p: set[int] = set()
    hits = 0
    errors: list[float] = []
    for g in gold:
        best_i = None
        best_err = None
        for i, p in enumerate(pred):
            if i in used_p:
                continue
            err = abs(float(p["t"]) - float(g["t"]))
            if err <= tau and (best_err is None or err < best_err):
                best_err = err
                best_i = i
        if best_i is not None and best_err is not None:
            used_p.add(best_i)
            hits += 1
            errors.append(best_err)
    prec = hits / len(pred) if pred else 0.0
    rec = hits / len(gold) if gold else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return {
        "precision": round(prec, 3),
        "recall": round(rec, 3),
        "f1": round(f1, 3),
        "hits": hits,
        "gold_n": len(gold),
        "pred_n": len(pred),
        "median_abs_err_s": round(sorted(errors)[len(errors) // 2], 3) if errors else None,
    }


def score_hop(
    *,
    text: str,
    ollama: bool,
    model: str,
) -> dict[str, Any]:
    rescued = apply_common_sense(
        {"bucket": "uncertain", "kind": "unknown", "confidence": "low", "why": "rolling"},
        text,
        "",
    )
    bucket = rescued["bucket"] if rescued["bucket"] != "uncertain" else _lexicon_bucket(text)
    out = {
        "bucket": bucket,
        "confidence": rescued.get("confidence") or "low",
        "source": "lexicon",
        "text_chars": len(text or ""),
    }
    if not ollama:
        return out
    try:
        from .farm_draft import _ask_ollama_text

        draft = _ask_ollama_text(model, text or "(no speech)", "")
        draft = apply_common_sense(draft, text, "")
        out["bucket"] = draft.get("bucket") or "uncertain"
        out["confidence"] = draft.get("confidence") or "low"
        out["why"] = str(draft.get("why") or "")[:120]
        out["source"] = "ollama"
    except Exception as exc:  # noqa: BLE001
        out["ollama_error"] = str(exc)[:100]
    return out


def run_probe(
    *,
    widths: tuple[int, ...] = WIDTHS,
    hop_s: float = 1.0,
    causal: bool = False,
    ollama: bool = False,
    model: str = "qwen2.5:14b",
    limit_sessions: int | None = None,
    focus_pad_s: float | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    from .config import ensure_data_layout

    ensure_data_layout(root)
    label = farm_label_dir(root)
    queue_rows = _read_jsonl(label / "queue.jsonl")
    queue = {r["clip"]: r for r in queue_rows if r.get("clip")}
    keys = _read_jsonl(label / "key.jsonl")
    locked = [
        k
        for k in keys
        if (k.get("ask") == "locked" or k.get("gold") or k.get("source") in {"gold", "human"})
        and str(k.get("bucket") or "") not in {"", "uncertain"}
    ]
    maps = build_gold_maps(locked, queue)
    jpath = label / "take_judgments.json"
    if jpath.is_file():
        try:
            judgments = json.loads(jpath.read_text(encoding="utf-8"))
            if isinstance(judgments, dict):
                maps = _merge_judgment_regions(maps, judgments, queue)
        except json.JSONDecodeError:
            pass

    # Prefer sessions that actually have transitions
    maps = sorted(maps, key=lambda m: (-int(m["n_transitions"]), -int(m["n_seconds"])))
    if limit_sessions is not None:
        maps = maps[:limit_sessions]

    per_width: dict[str, Any] = {}
    details: dict[str, Any] = {}

    for W in widths:
        frame_correct = 0
        frame_n = 0
        uncertain_n = 0
        empty_asr_n = 0
        all_gold_t: list[dict[str, Any]] = []
        all_pred_t: list[dict[str, Any]] = []
        session_rows = []

        for m in maps:
            sd = Path(m["session_dir"])
            tr = _load_transcript(sd)
            gold_labels = {int(k): v for k, v in m["labels"].items()}
            if not gold_labels:
                continue
            secs = sorted(gold_labels)
            focus_secs: set[int] | None = None
            if focus_pad_s is not None and m["transitions"]:
                focus_secs = set()
                pad = int(focus_pad_s)
                for g in m["transitions"]:
                    gt = int(float(g["t"]))
                    for sec in range(gt - pad, gt + pad + 1):
                        if sec in gold_labels:
                            focus_secs.add(sec)
            pred_seq: list[tuple[int, str]] = []
            for sec in secs:
                if focus_secs is not None and sec not in focus_secs:
                    continue
                t = float(sec) + 0.5  # decision at mid-second
                if causal:
                    a, b = t - float(W), t
                else:
                    half = float(W) / 2.0
                    a, b = t - half, t + half
                text = transcript_for_window(tr, a, b, pad=0.0) if tr.get("ok") else ""
                if not text.strip():
                    empty_asr_n += 1
                # Expensive model only on focus band; elsewhere lexicon keeps the curve cheap.
                use_ollama = bool(ollama and (focus_secs is None or sec in focus_secs))
                scored = score_hop(text=text, ollama=use_ollama, model=model)
                bucket = str(scored.get("bucket") or "uncertain")
                if bucket == "uncertain":
                    uncertain_n += 1
                pred_seq.append((sec, bucket))
                truth = gold_labels[sec]
                frame_n += 1
                if bucket == truth:
                    frame_correct += 1

            # predicted transitions (skip uncertain noise: only hard label flips)
            pred_t = []
            for i in range(1, len(pred_seq)):
                s0, b0 = pred_seq[i - 1]
                s1, b1 = pred_seq[i]
                if s1 != s0 + 1:
                    continue
                if b0 == "uncertain" or b1 == "uncertain":
                    continue
                if b0 != b1:
                    pred_t.append({"t": float(s1), "from": b0, "to": b1, "session": str(sd)})

            gold_t = [{**g, "session": str(sd)} for g in m["transitions"]]
            all_gold_t.extend(gold_t)
            all_pred_t.extend(pred_t)
            session_rows.append(
                {
                    "session_dir": str(sd),
                    "n_seconds": len(secs),
                    "gold_transitions": len(gold_t),
                    "pred_transitions": len(pred_t),
                }
            )

        n = max(1, frame_n)
        tau_table = {f"tau_{tau}s": match_transitions(all_gold_t, all_pred_t, tau=float(tau)) for tau in TOLERANCES}
        per_width[str(W)] = {
            "width_s": W,
            "hop_s": hop_s,
            "causal": causal,
            "frame_n": frame_n,
            "frame_acc_pct": round(100 * frame_correct / n, 1),
            "uncertain_pct": round(100 * uncertain_n / n, 1),
            "asr_empty_pct": round(100 * empty_asr_n / n, 1),
            "gold_transitions": len(all_gold_t),
            "pred_transitions": len(all_pred_t),
            "transition_match": tau_table,
            "auto_lock_proxy_pct": round(100 * (frame_correct) / n, 1),  # correct & (implied) decided
            "human_review_proxy_pct": round(100 * uncertain_n / n, 1),
        }
        details[str(W)] = {"sessions": session_rows, "gold": all_gold_t, "pred": all_pred_t}

    # Pick best W: maximize F1@1s, then frame acc, then lower uncertain
    def _rank(w: str) -> tuple:
        row = per_width[w]
        f1 = float(row["transition_match"]["tau_1s"]["f1"] or 0)
        return (f1, float(row["frame_acc_pct"]), -float(row["uncertain_pct"]))

    best_w = max(per_width.keys(), key=_rank) if per_width else None
    best = per_width.get(best_w or "", {})

    out = {
        "generated_utc": _now(),
        "question": (
            "1s decision hops with rolling evidence width W — which W localizes "
            "transitions best and needs the least human review?"
        ),
        "method": {
            "hop_s": hop_s,
            "widths_s": list(widths),
            "window": "causal [t-W,t]" if causal else "centered [t-W/2, t+W/2]",
            "model": model if ollama else "lexicon+common_sense",
            "gold": "locked adjacent clips + multi-region judgments → 1s label map",
            "metrics": [
                "frame_acc_pct (pred bucket == gold at each second)",
                "transition F1 within τ∈{1,2,3}s + median |error|",
                "uncertain_pct ≈ human review load",
            ],
        },
        "gold_sessions": len(maps),
        "gold_transitions_total": sum(int(m["n_transitions"]) for m in maps),
        "gold_seconds_total": sum(int(m["n_seconds"]) for m in maps),
        "focus_pad_s": focus_pad_s,
        "per_width": per_width,
        "recommend_width_s": int(best_w) if best_w else None,
        "recommend_why": (
            f"Best F1@1s={best.get('transition_match', {}).get('tau_1s', {}).get('f1')} "
            f"frame_acc={best.get('frame_acc_pct')}% uncertain={best.get('uncertain_pct')}% "
            f"({'causal' if causal else 'centered'})"
            if best_w
            else None
        ),
        "how_to_scale": [
            "Lock ≥30 paired transitions (ad↔program) via /farm morning batch — multi-region Done is ideal.",
            "Re-run with --ollama (and later moondream still at hop t) once gold_transitions_total ≥ 30.",
            "Compare centered (offline labeling) vs --causal (live muter timing).",
            "Ship winner as: still_diff cuts + 1s hops + rolling W ASR into draft worker.",
            "Auto-lock only when confidence high AND neighbors agree for ≥2 hops; else human.",
        ],
        "details": details,
    }

    json_path = label / "ROLLING_TRANSITION_PROBE.json"
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = [
        f"# Rolling transition probe — {out['generated_utc'][:19]}Z",
        "",
        out["question"],
        "",
        f"Gold: **{out['gold_sessions']}** sessions · **{out['gold_seconds_total']}** labeled seconds · "
        f"**{out['gold_transitions_total']}** transitions · model=`{out['method']['model']}` · "
        f"window=`{out['method']['window']}`",
        "",
        "| W (s) | frame acc % | uncertain % | F1@1s | F1@2s | F1@3s | median\\|err\\|@1s | pred cuts |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for W in widths:
        row = per_width[str(W)]
        t1 = row["transition_match"]["tau_1s"]
        t2 = row["transition_match"]["tau_2s"]
        t3 = row["transition_match"]["tau_3s"]
        md.append(
            f"| {W} | {row['frame_acc_pct']} | {row['uncertain_pct']} | {t1['f1']} | {t2['f1']} | "
            f"{t3['f1']} | {t1['median_abs_err_s']} | {row['pred_transitions']} |"
        )
    md.extend(
        [
            "",
            f"**Recommend W = {out.get('recommend_width_s')}s** — {out.get('recommend_why')}",
            "",
            "## How to find the real optimum",
            "",
        ]
    )
    md.extend(f"- {line}" for line in out["how_to_scale"])
    md.extend(["", f"JSON: `{json_path}`", ""])
    md_path = label / "ROLLING_TRANSITION_PROBE.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    out["md_path"] = str(md_path)
    out["json_path"] = str(json_path)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Rolling 1s-hop × W evidence transition probe")
    p.add_argument("--widths", default="2,3,5,10")
    p.add_argument("--hop", type=float, default=1.0)
    p.add_argument("--causal", action="store_true", help="Use [t-W,t] instead of centered")
    p.add_argument("--ollama", action="store_true")
    p.add_argument("--model", default="qwen2.5:14b")
    p.add_argument("--limit-sessions", type=int, default=None)
    p.add_argument(
        "--focus-pad",
        type=float,
        default=None,
        help="Only score ±pad seconds around gold transitions (required for affordable --ollama)",
    )
    args = p.parse_args(argv)
    widths = tuple(int(x) for x in str(args.widths).split(",") if x.strip())
    out = run_probe(
        widths=widths,
        hop_s=args.hop,
        causal=args.causal,
        ollama=args.ollama,
        model=args.model,
        limit_sessions=args.limit_sessions,
        focus_pad_s=args.focus_pad,
    )
    print(
        json.dumps(
            {
                k: out[k]
                for k in (
                    "gold_sessions",
                    "gold_transitions_total",
                    "gold_seconds_total",
                    "per_width",
                    "recommend_width_s",
                    "recommend_why",
                    "md_path",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
