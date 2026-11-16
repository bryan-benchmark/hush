"""Shadow-refit CausalHead on farm embeds with You-keep hard-negatives overweighted.

- Relabel farm *.npz from farm_accepted (You → gold already applied)
- Fine-tune from live frozen_head.pt (does not overwrite it until KEEP+ship)
- Score Pluto You sessions vs baseline frozen head
- Write audit/EPISODE_YOU_SHADOW_REFIT.json

  python -m tools.windows_lab.farm_you_shadow_refit
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from experiments.audio_learn.head import CausalHead, load_head, probabilities, save_head
from experiments.audio_learn.splits import HIDDEN, HOP_S, SEQUENCE
from experiments.audio_learn.windows import consecutive_end_indices
from ohush_live.research_muter import HEAD as LIVE_HEAD
from ohush_live.research_muter import LiveController

from .coverage_farm import farm_label_dir
from .export_farm_acoustic_gold import OUT as FARM_ACCEPTED
from .farm_embed_extract import EMBED_ROOT
from .farm_live_scorecard import _cover_ranges, load_gold_clips, score_session
from .farm_ontology import BROADCAST, NON_BROADCAST

OUT_DIR = Path(r"C:\OHushData\gpu_lab\audio_learn\checkpoints")
SHADOW_HEAD = OUT_DIR / "farm_you_shadow_head.pt"
EPOCHS = 6
BATCH = 64
PER_CLASS = 2500
HN_DUP = 6  # overweight You-keep hard-neg sequences
LR = 5e-4
PLUTO = (
    "20261110T1339Z_pluto_cbs_sports_hq",
    "20261110T1401Z_pluto_cbs_sports_hq",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_accepted() -> list[dict[str, Any]]:
    if not FARM_ACCEPTED.is_file():
        return []
    return [json.loads(l) for l in FARM_ACCEPTED.read_text(encoding="utf-8").splitlines() if l.strip()]


def _load_hard_negs() -> list[dict[str, Any]]:
    path = farm_label_dir() / "audit" / "EPISODE_YOU_SCORE_DELTA.json"
    if not path.is_file():
        return []
    return list((json.loads(path.read_text(encoding="utf-8")).get("you_hard_negatives") or []))


def _in_spans(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(a <= t < b for a, b in spans)


def _relabel(session: str, t: np.ndarray, accepted: list[dict[str, Any]]) -> np.ndarray:
    nb = [
        (float(r["start_s"]), float(r["end_s"]))
        for r in accepted
        if r.get("session") == session and r.get("bucket") == NON_BROADCAST
    ]
    bc = [
        (float(r["start_s"]), float(r["end_s"]))
        for r in accepted
        if r.get("session") == session and r.get("bucket") == BROADCAST
    ]
    labels = np.full(len(t), -1, dtype=np.int8)
    for i, tt in enumerate(t):
        tf = float(tt)
        if _in_spans(tf, nb):
            labels[i] = 1
        elif _in_spans(tf, bc):
            labels[i] = 0
    return labels


def _load_caches(sessions: list[str], accepted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    caches = []
    for session in sessions:
        path = EMBED_ROOT / f"{session}.npz"
        if not path.is_file():
            continue
        blob = np.load(path)
        t = np.asarray(blob["t"], dtype=np.float64)
        emb = np.asarray(blob["emb"], dtype=np.float32)
        label = _relabel(session, t, accepted)
        caches.append({"session": session, "t": t, "emb": emb, "label": label, "path": str(path)})
    if not caches:
        raise RuntimeError("no farm embedding caches found")
    return caches


def _indexes(
    caches: list[dict[str, Any]], hard_negs: list[dict[str, Any]]
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]]]:
    commercial: list[tuple[int, int]] = []
    program: list[tuple[int, int]] = []
    hard: list[tuple[int, int]] = []
    hn_by = defaultdict(list)
    for row in hard_negs:
        hn_by[str(row.get("session"))].append((float(row["t0"]), float(row["t1"])))
    for ci, cache in enumerate(caches):
        spans = hn_by.get(cache["session"]) or []
        for end in consecutive_end_indices(cache["t"], SEQUENCE, HOP_S):
            lab = int(cache["label"][end])
            if lab == 1:
                commercial.append((ci, end))
            elif lab == 0:
                program.append((ci, end))
                tt = float(cache["t"][end])
                if _in_spans(tt, spans):
                    hard.append((ci, end))
    if not commercial or not program:
        raise RuntimeError(f"need both classes; got mute={len(commercial)} play={len(program)}")
    return commercial, program, hard


def _batch(caches: list[dict[str, Any]], picks: list[tuple[int, int]], device: torch.device):
    dim = caches[0]["emb"].shape[1]
    waves = np.zeros((len(picks), SEQUENCE, dim), dtype=np.float32)
    labels = np.full((len(picks), SEQUENCE), -1, dtype=np.int8)
    for row, (ci, end) in enumerate(picks):
        cache = caches[ci]
        left = end - SEQUENCE + 1
        waves[row] = cache["emb"][left : end + 1]
        labels[row] = cache["label"][left : end + 1]
    return torch.from_numpy(waves).to(device), torch.from_numpy(labels).long().to(device)


def train_shadow(caches: list[dict[str, Any]], hard_negs: list[dict[str, Any]]) -> dict[str, Any]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required for shadow refit")
    device = torch.device("cuda")
    commercial, program, hard = _indexes(caches, hard_negs)
    head = load_head(LIVE_HEAD, device)
    head.train()
    for p in head.parameters():
        p.requires_grad_(True)
    opt = torch.optim.AdamW(head.parameters(), lr=LR, weight_decay=1e-4)
    rng = np.random.default_rng(7)
    history = []
    for epoch in range(EPOCHS):
        order_c = commercial.copy()
        order_p = program.copy()
        rng.shuffle(order_c)
        rng.shuffle(order_p)
        count = min(PER_CLASS, len(order_c), len(order_p))
        picks = order_c[:count] + order_p[:count]
        if hard:
            picks.extend(hard * HN_DUP)
        rng.shuffle(picks)
        total = 0.0
        seen = 0
        for start in range(0, len(picks), BATCH):
            batch = picks[start : start + BATCH]
            waves, labels = _batch(caches, batch, device)
            opt.zero_grad(set_to_none=True)
            logits = head(waves)
            mask = labels >= 0
            if int(mask.sum()) == 0:
                continue
            loss = F.binary_cross_entropy_with_logits(logits[mask], labels[mask].float())
            loss.backward()
            opt.step()
            total += float(loss.detach()) * int(mask.sum())
            seen += int(mask.sum())
        mean = total / seen if seen else None
        history.append(mean)
        print(
            f"shadow epoch {epoch + 1}/{EPOCHS} loss {mean:.4f} "
            f"seq={count * 2}+hn={len(hard) * HN_DUP}",
            flush=True,
        )
    head.eval()
    save_head(SHADOW_HEAD, head)
    return {
        "epochs": EPOCHS,
        "history": history,
        "n_commercial": len(commercial),
        "n_program": len(program),
        "n_hard_neg_seq": len(hard),
        "hn_dup": HN_DUP,
        "head": str(SHADOW_HEAD),
        "init_from": str(LIVE_HEAD),
    }


def _score_with_head(
    head: CausalHead,
    device: torch.device,
    caches: list[dict[str, Any]],
    clips_by_session: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sessions_out = []
    for cache in caches:
        session = cache["session"]
        clips = clips_by_session.get(session) or []
        if not clips:
            continue
        probs = probabilities(head, cache["emb"], cache["t"], device, batch=256)
        ctrl = LiveController()
        decisions = []
        for t, p in zip(cache["t"], probs):
            d = ctrl.step(float(t), float(p))
            decisions.append(
                {
                    "t": float(t),
                    "available_at": float(t),
                    "action": d["action"],
                    "probability": float(p),
                    "force_play": bool(d.get("force_play")),
                }
            )
        t0 = min(c["t0"] for c in clips)
        t1 = max(c["t1"] for c in clips)
        cover = _cover_ranges(decisions, (t0, t1))
        scored = score_session(clips, cover)
        sessions_out.append({"session": session, **scored})
    # aggregate like scorecard
    mute_s = sum(s["mute_labeled_s"] for s in sessions_out)
    play_s = sum(s["play_labeled_s"] for s in sessions_out)
    cov_s = sum(s["commercial_covered_s"] for s in sessions_out)
    prog_m = sum(s["program_muted_s"] for s in sessions_out)
    broken = prog_m > 1e-6
    coverage = (cov_s / mute_s) if mute_s > 1e-6 else None
    return {
        "sessions": sessions_out,
        "aggregate": {
            "mute_labeled_s": round(mute_s, 3),
            "play_labeled_s": round(play_s, 3),
            "commercial_covered_s": round(cov_s, 3),
            "commercial_coverage": None if coverage is None else round(coverage, 4),
            "program_muted_s": round(prog_m, 3),
            "broken": broken,
        },
    }


def decide_keep(baseline: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
    b = baseline["aggregate"]
    s = shadow["aggregate"]
    drop = float(b["program_muted_s"]) - float(s["program_muted_s"])
    b_cov = b.get("commercial_coverage")
    s_cov = s.get("commercial_coverage")
    cov_ok = True
    if b_cov is not None and s_cov is not None:
        cov_ok = float(s_cov) + 1e-9 >= float(b_cov) - 0.05
    keep = drop >= 10.0 and cov_ok
    return {
        "keep": keep,
        "program_muted_drop_s": round(drop, 3),
        "coverage_ok": cov_ok,
        "reason": (
            "KEEP: program_muted dropped ≥10s without coverage collapse"
            if keep
            else "NO KEEP: need ≥10s program_muted drop with coverage within 5pp"
        ),
    }


def run() -> dict[str, Any]:
    accepted = _load_accepted()
    hard_negs = _load_hard_negs()
    # Train on all farm embeds we have; evaluate KEEP on Pluto You sessions.
    train_sessions = sorted({p.stem for p in EMBED_ROOT.glob("*.npz")})
    caches = _load_caches(train_sessions, accepted)
    train_meta = train_shadow(caches, hard_negs)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    clips = load_gold_clips(clean_only=True)
    clips_by = defaultdict(list)
    for c in clips:
        if c["session"] in PLUTO:
            clips_by[c["session"]].append(c)
    pluto_caches = [c for c in caches if c["session"] in PLUTO]

    base_head = load_head(LIVE_HEAD, device)
    shadow_head = load_head(SHADOW_HEAD, device)
    baseline = _score_with_head(base_head, device, pluto_caches, clips_by)
    shadow = _score_with_head(shadow_head, device, pluto_caches, clips_by)
    verdict = decide_keep(baseline, shadow)

    out = {
        "generated_utc": _now(),
        "train": train_meta,
        "hard_negatives_n": len(hard_negs),
        "train_sessions": [c["session"] for c in caches],
        "eval_sessions": list(PLUTO),
        "baseline_pluto": baseline,
        "shadow_pluto": shadow,
        "verdict": verdict,
        "next": (
            ["Ship shadow head via ship_live_muter / wire ohush_live"]
            if verdict["keep"]
            else [
                "Do not ship",
                "Open more disagree hops autonomously OR widen hard-neg mining",
            ]
        ),
    }
    path = farm_label_dir() / "audit" / "EPISODE_YOU_SHADOW_REFIT.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    md = [
        "# Episode You shadow refit",
        "",
        f"generated: {out['generated_utc'][:19]}Z",
        "",
        f"**Verdict: {'KEEP' if verdict['keep'] else 'NO KEEP'}** — {verdict['reason']}",
        "",
        f"- baseline program_muted_s: **{baseline['aggregate']['program_muted_s']}**",
        f"- shadow program_muted_s: **{shadow['aggregate']['program_muted_s']}**",
        f"- drop: **{verdict['program_muted_drop_s']}s**",
        f"- baseline coverage: **{baseline['aggregate']['commercial_coverage']}**",
        f"- shadow coverage: **{shadow['aggregate']['commercial_coverage']}**",
        f"- head: `{SHADOW_HEAD}`",
        "",
    ]
    (farm_label_dir() / "audit" / "EPISODE_YOU_SHADOW_REFIT.md").write_text(
        "\n".join(md), encoding="utf-8"
    )
    out["receipt"] = str(path)
    return out


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Farm You hard-neg shadow head refit").parse_args(argv)
    try:
        out = run()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), flush=True)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "keep": out["verdict"]["keep"],
                "drop_s": out["verdict"]["program_muted_drop_s"],
                "baseline_program_muted_s": out["baseline_pluto"]["aggregate"]["program_muted_s"],
                "shadow_program_muted_s": out["shadow_pluto"]["aggregate"]["program_muted_s"],
                "baseline_coverage": out["baseline_pluto"]["aggregate"]["commercial_coverage"],
                "shadow_coverage": out["shadow_pluto"]["aggregate"]["commercial_coverage"],
                "head": out["train"]["head"],
                "receipt": out["receipt"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
