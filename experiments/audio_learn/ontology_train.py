"""Train a head on broadcast ontology labels (not raw gold alone).

Relabel TRAIN frozen embeddings:
  non_broadcast accepted → 1 (mute)
  broadcast accepted     → 0 (play)
  else keep gold cache label

Sample with desk/broadcast share like studio_fit. Score EVAL on product
scorecard vs frozen. Research latch optional on top. Live untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.extract import load_cache
from experiments.audio_learn.head import CausalHead, load_head, probabilities, save_head
from experiments.audio_learn.product_scorecard import load_accepted, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.splits import EVAL, HIDDEN, HOP_S, SEED, SEQUENCE, TRAIN, assert_split
from experiments.audio_learn.train_head import BATCH as TRAIN_BATCH
from experiments.audio_learn.train_head import _batch, _indexes
from experiments.audio_learn.windows import consecutive_end_indices
from tools.gpu_lab.splits import HOLDOUTS

EPOCHS = 8
PER_CLASS = 4000
BROADCAST_SHARE = 0.25
OUT = DATA_ROOT / "ontology_train"
HEAD_PATH = DATA_ROOT / "checkpoints" / "ontology_head.pt"


def _in_spans(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(a <= t < b for a, b in spans)


def _relabel_cache(session: str, cache: dict, accepted: list[dict]) -> dict:
    times = np.asarray(cache["t"], dtype=np.float64)
    labels = np.array(cache["label"], dtype=np.int8, copy=True)
    nb = [(float(r["start_s"]), float(r["end_s"])) for r in accepted if r["session"] == session and r["bucket"] == "non_broadcast"]
    bc = [(float(r["start_s"]), float(r["end_s"])) for r in accepted if r["session"] == session and r["bucket"] == "broadcast"]
    flipped_to_1 = 0
    flipped_to_0 = 0
    for i, t in enumerate(times):
        if _in_spans(float(t), nb):
            if labels[i] != 1:
                flipped_to_1 += 1
            labels[i] = 1
        elif _in_spans(float(t), bc):
            if labels[i] != 0:
                flipped_to_0 += 1
            labels[i] = 0
    return {
        "t": times,
        "emb": cache["emb"],
        "label": labels,
        "flipped_to_1": flipped_to_1,
        "flipped_to_0": flipped_to_0,
        "n1": int((labels == 1).sum()),
        "n0": int((labels == 0).sum()),
    }


def _broadcast_indexes(caches: list[dict], sessions: tuple[str, ...], accepted: list[dict]) -> list[tuple[int, int]]:
    spans_by = {
        session: [(float(r["start_s"]), float(r["end_s"])) for r in accepted if r["session"] == session and r["bucket"] == "broadcast"]
        for session in sessions
    }
    found = []
    for cache_index, (session, cache) in enumerate(zip(sessions, caches)):
        spans = spans_by.get(session) or []
        if not spans:
            continue
        times = cache["t"]
        for end in consecutive_end_indices(times, SEQUENCE, HOP_S):
            if int(cache["label"][end]) != 0:
                continue
            if _in_spans(float(times[end]), spans):
                found.append((cache_index, end))
    return found


def train_ontology_head() -> dict:
    assert_split()
    if not torch.cuda.is_available():
        raise RuntimeError("ontology head training needs CUDA")
    device = torch.device("cuda")
    accepted = load_accepted()
    paths = [DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz" for session in TRAIN]
    for path, session in zip(paths, TRAIN):
        if not path.is_file():
            raise RuntimeError(f"missing embedding cache {path}")
        if session in EVAL or session in HOLDOUTS:
            raise RuntimeError("refusing Prime/holdout in ontology fit")
    raw = [load_cache(path) for path in paths]
    caches = []
    relabel_report = {}
    for session, cache in zip(TRAIN, raw):
        rel = _relabel_cache(session, cache, accepted)
        relabel_report[session] = {k: rel[k] for k in ("flipped_to_1", "flipped_to_0", "n1", "n0")}
        caches.append({"t": rel["t"], "emb": rel["emb"], "label": rel["label"]})
        print(f"relabel {session} {relabel_report[session]}", flush=True)

    commercial, program = _indexes(caches)
    broadcast = _broadcast_indexes(caches, TRAIN, accepted)
    broadcast_keys = set(broadcast)
    ordinary = [item for item in program if item not in broadcast_keys]
    if len(broadcast) < 100:
        raise RuntimeError(f"only {len(broadcast)} broadcast sequences; refusing weak ontology fit")

    head = CausalHead(caches[0]["emb"].shape[1], HIDDEN).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    rng = np.random.default_rng(SEED)
    b_draw = int(round(PER_CLASS * BROADCAST_SHARE))
    o_draw = PER_CLASS - b_draw
    history = []
    for epoch in range(EPOCHS):
        order_c = commercial.copy()
        order_o = ordinary.copy()
        order_b = broadcast.copy()
        rng.shuffle(order_c)
        rng.shuffle(order_o)
        rng.shuffle(order_b)
        if len(order_b) < b_draw:
            reps = int(np.ceil(b_draw / max(len(order_b), 1)))
            order_b = (order_b * reps)[:b_draw]
        count = min(PER_CLASS, len(order_c), len(order_o) + len(order_b))
        picks = order_c[:count] + order_o[:o_draw] + order_b[:b_draw]
        rng.shuffle(picks)
        total = 0.0
        seen = 0
        head.train()
        for start in range(0, len(picks), TRAIN_BATCH):
            waves, labels = _batch(caches, picks[start : start + TRAIN_BATCH], device)
            optimizer.zero_grad(set_to_none=True)
            logits = head(waves)
            mask = labels >= 0
            if int(mask.sum()) == 0:
                continue
            loss = F.binary_cross_entropy_with_logits(logits[mask], labels[mask].float())
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * int(mask.sum())
            seen += int(mask.sum())
        mean = total / seen if seen else None
        history.append(mean)
        print(f"ontology epoch {epoch + 1}/{EPOCHS} loss {mean:.4f} n={len(picks)}", flush=True)

    head.eval()
    OUT.mkdir(parents=True, exist_ok=True)
    save_head(HEAD_PATH, head)
    meta = {
        "epochs": EPOCHS,
        "broadcast_share": BROADCAST_SHARE,
        "commercial_sequences": len(commercial),
        "ordinary_program_sequences": len(ordinary),
        "broadcast_sequences": len(broadcast),
        "relabel": relabel_report,
        "loss": history,
        "checkpoint": str(HEAD_PATH),
    }
    (OUT / "train_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("wrote", HEAD_PATH, flush=True)
    return meta


def score_ontology() -> dict:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    head = load_head(HEAD_PATH, device)
    ontology_probs = {}
    for session in EVAL:
        cache = load_cache(DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz")
        scores = probabilities(head, cache["emb"], cache["t"], device)
        ontology_probs[session] = (cache["t"], scores.astype(np.float64))
        np.savez(OUT / f"{session}_ontology.npz", t=cache["t"], p=scores, label=cache["label"])

    frozen = load_frozen_probs(EVAL)
    reports = {}
    reports["frozen"] = score_run("frozen", frozen, OUT)
    reports["ontology"] = score_run("ontology", ontology_probs, OUT)

    # ontology + research latch (cooldown+voice on ontology p)
    latched = {}
    for session, (times, probs) in ontology_probs.items():
        latched[session] = (times, apply_research_latch(session, times, probs, with_voice=True))
    reports["ontology_research_latch"] = score_run("ontology_research_latch", latched, OUT)

    # frozen research latch baseline
    frozen_latch = {s: (t, apply_research_latch(s, t, p, with_voice=True)) for s, (t, p) in frozen.items()}
    reports["frozen_research_latch"] = score_run("frozen_research_latch", frozen_latch, OUT)

    def decide(name: str, base: dict, other: dict) -> dict:
        cov_d = (other["non_broadcast_coverage"] or 0) - (base["non_broadcast_coverage"] or 0)
        desk_d = other["cells"]["desk_s"] - base["cells"]["desk_s"]
        odell_d = other["focus"]["hush_20260924_220624"]["odell"] - base["focus"]["hush_20260924_220624"]["odell"]
        amex_d = other["focus"]["hush_20261008_205100"]["amex"] - base["focus"]["hush_20261008_205100"]["amex"]
        chilis_d = other["focus"]["hush_20260924_220624"]["chilis"] - base["focus"]["hush_20260924_220624"]["chilis"]
        reasons = []
        decision = "KEEP"
        if cov_d < -0.02:
            decision = "REJECT"
            reasons.append(f"coverage drop {-cov_d:.4f}")
        if amex_d < -2 or chilis_d < -2:
            decision = "REJECT"
            reasons.append(f"spot leak amex={amex_d} chilis={chilis_d}")
        if desk_d > 1:
            decision = "REJECT"
            reasons.append(f"desk muted rose {desk_d}")
        # vs frozen: need desk improvement to keep a new head
        if name.startswith("ontology") and "latch" not in name:
            if odell_d > -5 and desk_d > -20:
                decision = "REJECT"
                reasons.append(f"ontology head did not free desk/Odell odell_d={odell_d} desk_d={desk_d}")
        if not reasons:
            reasons.append("coverage/spots held; desk improved or latch baseline")
        return {
            "decision": decision,
            "reasons": reasons,
            "delta": {
                "cov_delta": round(cov_d, 4),
                "desk_delta": round(desk_d, 1),
                "odell_delta": round(odell_d, 2),
                "amex_delta": round(amex_d, 2),
                "chilis_delta": round(chilis_d, 2),
            },
        }

    base = reports["frozen"]["aggregate"]
    latch_base = reports["frozen_research_latch"]["aggregate"]
    verdicts = {
        "ontology_vs_frozen": decide("ontology", base, reports["ontology"]["aggregate"]),
        "ontology_research_latch_vs_frozen_latch": decide(
            "ontology_latch", latch_base, reports["ontology_research_latch"]["aggregate"]
        ),
    }

    print("\n=== RAW CELL TABLE ===", flush=True)
    print(f"{'run':28} {'cov':7} {'desk':7} {'odell':7} {'amex':7} {'chilis':7}", flush=True)
    for name, rep in reports.items():
        a = rep["aggregate"]
        print(
            f"{name:28} {a['non_broadcast_coverage']:.4f} {a['cells']['desk_s']:7.1f} "
            f"{a['focus']['hush_20260924_220624']['odell']:7.1f} "
            f"{a['focus']['hush_20261008_205100']['amex']:7.1f} "
            f"{a['focus']['hush_20260924_220624']['chilis']:7.1f}",
            flush=True,
        )
    print("\nKEEP/REJECT", flush=True)
    for k, v in verdicts.items():
        print(k, v["decision"], v["reasons"], v["delta"], flush=True)

    summary = {
        "verdicts": verdicts,
        "aggregates": {k: v["aggregate"] for k, v in reports.items()},
        "head": str(HEAD_PATH),
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "KEEP_REJECT.md").write_text(
        "\n".join(
            [
                "# Ontology head vs frozen (product cells)",
                "",
                *[
                    f"## {k}\n- **{v['decision']}**\n"
                    + "\n".join(f"- {r}" for r in v["reasons"])
                    + f"\n- `{json.dumps(v['delta'])}`\n"
                    for k, v in verdicts.items()
                ],
            ]
        ),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = train_ontology_head()
    print("train_meta", json.dumps(meta, indent=2), flush=True)
    score_ontology()
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
