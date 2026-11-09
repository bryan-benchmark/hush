"""ML-engineer failure trace for a named false-mute span.

Atomic receipts already store p + action. This dump adds what an ML engineer
reads when debugging a classifier + hysteresis product:

  - logit and P(commercial)
  - controller state machine (hot/cold streak + transition reason)
  - embedding nearest-neighbor to train commercial vs program prototypes
  - enrolled voice scores joined on the same clock
  - short acoustic bed snapshot every 2s
  - phase brief (pre-onset / onset / sustained / release)

Default focus is atomic Odell. Frozen weights and live TV are not touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from experiments.audio_learn.crowd_bed_receipts import _measures
from experiments.audio_learn.extract import load_cache
from experiments.audio_learn.head import load_head
from experiments.audio_learn.research_latch import (
    FITZ_CACHE,
    FITZ_MARGIN,
    PALMER_CACHE,
    PALMER_MARGIN,
    apply_research_latch,
)
from experiments.audio_learn.splits import HOP_S, SEQUENCE, TRAIN
from experiments.audio_learn.studio_fit import CONTROLLER
from experiments.audio_learn.windows import lookback_bounds
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals
from tools.gpu_lab.audio_load import load_coverage

DATA = Path(r"C:\OHushData\gpu_lab\audio_learn")
FROZEN_PRED = DATA / "predictions" / "frozen"
EMB = DATA / "embeddings" / "frozen"
HEAD = DATA / "checkpoints" / "frozen_head.pt"
ECAPA = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\NFL75_PROTECT_001\cache")
OUT = DATA / "ml_failure_traces"
NAMES = ["Al Michaels", "Kirk Herbstreit", "Clarissa Thompson", "Andrew Whitworth", "Tony Gonzalez"]
PANEL_MARGINS = {
    "Clarissa Thompson": 0.10,
    "Andrew Whitworth": 0.15,
}

# (session, name, t0, t1, pad_before_s)
# Blind 10-15: remaining research_stack covers (longest first) + one voice-freed contrast.
FOCUS = (
    ("hush_20261015_210805", "blind_cover_130s", 4667.0, 4797.25, 20.0),
    ("hush_20261015_210805", "blind_cover_112s", 8088.25, 8200.75, 20.0),
    ("hush_20261015_210805", "blind_cover_93s", 7782.5, 7876.0, 20.0),
    ("hush_20261015_210805", "blind_cover_92s", 3167.75, 3259.75, 20.0),
    ("hush_20261015_210805", "blind_voice_freed_28s", 1929.25, 2072.25, 20.0),
)

PROTO_PER_CLASS = 400
NN_EVERY = 1  # hops (0.25s) — full density for engineer log
ACOUSTIC_EVERY_S = 2.0


def _gold_at(t: float, ads: list[tuple[float, float]]) -> str:
    return "commercial" if any(a0 <= t < a1 for a0, a1 in ads) else "program"


def _traced_decisions(
    times: np.ndarray,
    probs: np.ndarray,
    logits: np.ndarray,
    on: float,
    off: float,
    on_streak: int,
    off_streak: int,
) -> list[dict]:
    state = "play"
    hot = 0
    cold = 0
    rows = []
    for t, p, logit in zip(times.tolist(), probs.tolist(), logits.tolist()):
        prev = state
        reason: str
        if state == "play":
            if p >= on:
                hot += 1
                reason = f"play: hot {hot}/{on_streak} (p={p:.4f}>={on})"
                if hot >= on_streak:
                    state = "cover"
                    cold = 0
                    reason += " → COVER"
            else:
                hot = 0
                reason = f"play: hot reset (p={p:.4f}<{on})"
        else:
            if p <= off:
                cold += 1
                reason = f"cover: cold {cold}/{off_streak} (p={p:.4f}<={off})"
                if cold >= off_streak:
                    state = "play"
                    hot = 0
                    reason += " → PLAY"
            else:
                cold = 0
                reason = f"cover: cold reset (p={p:.4f}>{off}); stay COVER"
        rows.append(
            {
                "t": round(float(t), 3),
                "logit": round(float(logit), 4),
                "p": round(float(p), 4),
                "action": state,
                "prev_action": prev,
                "hot_streak": hot,
                "cold_streak": cold,
                "transition": prev != state,
                "reason": reason,
            }
        )
    return rows


def _logits_and_p(head, emb: np.ndarray, times: np.ndarray, device: torch.device, index_slice: slice) -> tuple[np.ndarray, np.ndarray]:
    """Recompute logit + sigmoid for a contiguous index range (past-only windows)."""
    head.eval()
    emb = np.asarray(emb, dtype=np.float32)
    times = np.asarray(times, dtype=np.float64)
    length = int(head.sequence)
    indexes = list(range(index_slice.start, index_slice.stop))
    logits = np.empty(len(indexes), dtype=np.float32)
    batch = 128
    for start in range(0, len(indexes), batch):
        stop = min(len(indexes), start + batch)
        window = np.zeros((stop - start, length, emb.shape[1]), dtype=np.float32)
        for row, index in enumerate(indexes[start:stop]):
            left, right = lookback_bounds(times, index, length, HOP_S)
            chunk = emb[left:right]
            window[row, -len(chunk) :] = chunk
        tensor = torch.from_numpy(window).to(device)
        with torch.inference_mode():
            logit = head(tensor)[:, -1]
            logits[start:stop] = logit.float().cpu().numpy()
    probs = 1.0 / (1.0 + np.exp(-logits))
    return logits, probs


def _train_prototypes(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Sample L2-normalized train embeddings for commercial vs program retrieval."""
    commercial = []
    program = []
    for session in TRAIN:
        path = EMB / f"{session}.npz"
        if not path.is_file():
            continue
        cache = load_cache(path)
        labels = np.asarray(cache["label"])
        vecs = np.asarray(cache["emb"], dtype=np.float32)
        for label, bucket in ((1, commercial), (0, program)):
            idx = np.flatnonzero(labels == label)
            if idx.size == 0:
                continue
            take = idx if idx.size <= PROTO_PER_CLASS else rng.choice(idx, size=PROTO_PER_CLASS, replace=False)
            bucket.append(vecs[take])
    if not commercial or not program:
        raise RuntimeError("train embedding prototypes missing")
    c = np.concatenate(commercial, axis=0)
    p = np.concatenate(program, axis=0)
    c /= np.linalg.norm(c, axis=1, keepdims=True) + 1e-9
    p /= np.linalg.norm(p, axis=1, keepdims=True) + 1e-9
    # subsample pooled set for speed
    if len(c) > PROTO_PER_CLASS:
        c = c[rng.choice(len(c), size=PROTO_PER_CLASS, replace=False)]
    if len(p) > PROTO_PER_CLASS:
        p = p[rng.choice(len(p), size=PROTO_PER_CLASS, replace=False)]
    return c, p


def _nn_scores(vec: np.ndarray, commercial: np.ndarray, program: np.ndarray) -> dict:
    v = vec.astype(np.float32)
    v = v / (np.linalg.norm(v) + 1e-9)
    cos_c = float(np.max(commercial @ v))
    cos_p = float(np.max(program @ v))
    return {
        "nn_commercial_cos": round(cos_c, 4),
        "nn_program_cos": round(cos_p, 4),
        "nn_margin_c_minus_p": round(cos_c - cos_p, 4),
        "nn_says": "commercial" if cos_c >= cos_p else "program",
    }


def _side_score(cache_dir: Path, session: str, key: str, t: float) -> float | None:
    path = cache_dir / f"{session}_{key}.npz"
    if not path.is_file():
        return None
    blob = np.load(path)
    ended = np.flatnonzero(blob["end"] <= t + 1e-9)
    if ended.size == 0:
        return None
    i = int(ended[-1])
    val = float(blob[key][i])
    return None if not np.isfinite(val) else val


def _voice_at(session: str, t: float, cache: dict | None) -> dict | None:
    if cache is None:
        return None
    start, end, people = cache["start"], cache["end"], cache["people"]
    # window that has ended by t (causal)
    ended = np.flatnonzero(end <= t + 1e-9)
    if ended.size == 0:
        return None
    i = int(ended[-1])
    if start[i] > t:  # shouldn't happen
        return None
    with np.errstate(invalid="ignore"):
        scores = {name: float(people[i, slot]) for slot, name in enumerate(NAMES) if np.isfinite(people[i, slot])}
    palmer = _side_score(PALMER_CACHE, session, "palmer", t)
    fitz = _side_score(FITZ_CACHE, session, "fitz", t)
    if palmer is not None:
        scores["James Palmer"] = palmer
    if fitz is not None:
        scores["Ryan Fitzpatrick"] = fitz
    if not scores:
        return None
    best = max(scores, key=scores.get)
    rival = max((v for k, v in scores.items() if k != best), default=float("nan"))
    margin = None if not np.isfinite(rival) else scores[best] - rival
    need = PANEL_MARGINS.get(best)
    if best == "James Palmer":
        need = PALMER_MARGIN
    elif best == "Ryan Fitzpatrick":
        need = FITZ_MARGIN
    panel_hot = (
        best in PANEL_MARGINS or best in ("James Palmer", "Ryan Fitzpatrick")
    ) and scores[best] >= 0.25 and margin is not None and margin >= (need or 0.0)
    return {
        "voice_window_end": round(float(end[i]), 3),
        "voice_best": best,
        "voice_cosine": round(scores[best], 3),
        "voice_ge_0.25": scores[best] >= 0.25,
        "voice_margin": None if margin is None else round(float(margin), 3),
        "voice_panel_hot": bool(panel_hot),
        "voice_scores": {k: round(v, 3) for k, v in scores.items()},
    }


def _phases(rows: list[dict], t0: float, t1: float) -> list[dict]:
    onset = next((r for r in rows if r["transition"] and r["action"] == "cover" and r["t"] >= t0 - 5), None)
    release = next((r for r in rows if r["transition"] and r["action"] == "play" and r["t"] >= t0), None)
    inside = [r for r in rows if t0 <= r["t"] <= t1]
    pre = [r for r in rows if r["t"] < t0]
    phases = [
        {
            "name": "pre_onset",
            "t_range": [pre[0]["t"], t0] if pre else None,
            "p_median": None if not pre else round(float(np.median([r["p"] for r in pre])), 4),
            "actions": sorted({r["action"] for r in pre}),
            "engineer_read": (
                "Score rising into the labeled desk. If already cover here, this is carry/reheat; "
                "if still play with rising p, onset is a fresh mute decision."
            ),
        },
        {
            "name": "onset",
            "t": None if onset is None else onset["t"],
            "p": None if onset is None else onset["p"],
            "logit": None if onset is None else onset["logit"],
            "reason": None if onset is None else onset["reason"],
            "nn": {k: onset[k] for k in ("nn_commercial_cos", "nn_program_cos", "nn_margin_c_minus_p", "nn_says") if onset and k in onset},
            "voice": {k: onset[k] for k in ("voice_best", "voice_cosine", "voice_ge_0.25") if onset and k in onset},
            "engineer_read": (
                "Hysteresis fired: on_streak consecutive hops with p>=on. "
                "Read logit (raw confidence), nn_margin (embedding neighborhood), and voice (identity unused by mute)."
            ),
        },
        {
            "name": "sustained_fp",
            "t_range": [t0, t1],
            "n_hops": len(inside),
            "p_median": None if not inside else round(float(np.median([r["p"] for r in inside])), 4),
            "p_min": None if not inside else round(float(np.min([r["p"] for r in inside])), 4),
            "share_p_ge_on": None if not inside else round(float(np.mean([r["p"] >= CONTROLLER["on"] for r in inside])), 3),
            "nn_says_commercial_share": None
            if not inside
            else round(float(np.mean([r.get("nn_says") == "commercial" for r in inside if "nn_says" in r])), 3),
            "voice_ge_0.25_share": None
            if not inside
            else round(float(np.mean([bool(r.get("voice_ge_0.25")) for r in inside if "voice_best" in r])), 3),
            "voice_panel_hot_share": None
            if not inside
            else round(float(np.mean([bool(r.get("voice_panel_hot")) for r in inside if "voice_best" in r])), 3),
            "stack_still_cover_share": None
            if not inside
            else round(float(np.mean([r.get("stack_action") == "cover" for r in inside])), 3),
            "engineer_read": (
                "While cover holds, cold streak never reaches off_streak because p stays above off. "
                "If nn_says stays commercial, the embedding space agrees with the head — not a controller bug. "
                "If voice_panel_hot and stack still covers, latch missed that name; if voice cold, head FP or real ad."
            ),
        },
        {
            "name": "release",
            "t": None if release is None else release["t"],
            "p": None if release is None else release["p"],
            "reason": None if release is None else release["reason"],
            "engineer_read": "off_streak hops with p<=off returned play. If release is after the desk ends, the FP span is the whole label.",
        },
    ]
    return phases


def _brief(name: str, session: str, t0: float, t1: float, phases: list[dict], controller: dict) -> str:
    onset = next(p for p in phases if p["name"] == "onset")
    sust = next(p for p in phases if p["name"] == "sustained_fp")
    rel = next(p for p in phases if p["name"] == "release")
    pre = next(p for p in phases if p["name"] == "pre_onset")
    lines = [
        f"# ML failure trace — {name}",
        "",
        f"Session `{session}` span **{t0}–{t1}s**. Gold: program (desk). Product action: cover (false mute).",
        "",
        "## Pipeline under test",
        "",
        "1. `frame_mn10` embedding every 0.25s (4s audio ending at t)",
        f"2. Causal GRU head (`sequence={SEQUENCE}`) → logit → `p = σ(logit)` = P(commercial)",
        f"3. Hysteresis controller: cover after {controller['on_streak']} hops with p≥{controller['on']}; "
        f"return after {controller['off_streak']} hops with p≤{controller['off']}",
        "4. Voice / transcript are **not** inputs to (2) or (3) on this path",
        "",
        "## How to read hops.jsonl (ML eng)",
        "",
        "| field | meaning |",
        "|---|---|",
        "| `logit` / `p` | raw score and probability the head assigns to commercial |",
        "| `reason` | controller state machine in plain text |",
        "| `nn_*` | cosine to nearest **train** commercial vs program embedding (retrieval sanity) |",
        "| `voice_*` | enrolled ECAPA match ending ≤ t (side channel, unused by mute) |",
        "| `acoustic` | cheap bed measures on a 2s window (side channel) |",
        "",
        "## Phase verdict",
        "",
        f"- **pre_onset** p_median={pre.get('p_median')} actions={pre.get('actions')}",
        f"- **onset** t={onset.get('t')} p={onset.get('p')} logit={onset.get('logit')} reason=`{onset.get('reason')}`",
        f"  - nn={onset.get('nn')} voice={onset.get('voice')}",
        f"- **sustained_fp** p_median={sust.get('p_median')} share_p≥on={sust.get('share_p_ge_on')} "
        f"nn_commercial_share={sust.get('nn_says_commercial_share')} voice_hit_share={sust.get('voice_ge_0.25_share')}",
        f"- **release** t={rel.get('t')} p={rel.get('p')} reason=`{rel.get('reason')}`",
        "",
        "## Interpretation checklist",
        "",
        "1. If onset `nn_says=commercial` and margin>0 → head+embedding agree; fix is representation/labels or a veto, not streak tuning alone.",
        "2. If `voice_panel_hot` during cover but `stack_action` still cover → latch not wired for that name/margin.",
        "3. If voice cold entire cover → remaining mute is head/embedding (desk≠enrolled cast, or real ad).",
        "4. If pre_onset already `cover` → carry from earlier audio (Palmer-class), not a fresh desk decision.",
        "5. If logit only barely positive → threshold/calibration play; Odell-class usually has large positive logits.",
        "",
    ]
    return "\n".join(lines)


def trace_one(session: str, name: str, t0: float, t1: float, pad_before: float, commercial_proto, program_proto, head, device) -> Path:
    out = OUT / f"{session}_{name}"
    out.mkdir(parents=True, exist_ok=True)

    cache = load_cache(EMB / f"{session}.npz")
    times = np.asarray(cache["t"], dtype=np.float64)
    emb = np.asarray(cache["emb"], dtype=np.float32)
    pred = np.load(FROZEN_PRED / f"{session}.npz")
    # prefer stored p when aligned; still recompute logits for engineer log
    left = float(t0 - pad_before)
    right = float(t1 + 5.0)
    idx = np.flatnonzero((times >= left) & (times <= right))
    if idx.size == 0:
        raise RuntimeError(f"no hops for {session} {name}")
    sl = slice(int(idx[0]), int(idx[-1]) + 1)
    logits, probs = _logits_and_p(head, emb, times, device, sl)
    # sanity vs frozen file
    frozen_p = pred["p"]
    frozen_t = pred["t"]

    ads = target_commercials(active_intervals(session))
    rows = _traced_decisions(times[sl], probs, logits, **CONTROLLER)
    stack_p = apply_research_latch(session, times, frozen_p.astype(np.float64), with_voice=True)
    stack_rows = _traced_decisions(times[sl], stack_p[sl], logits, **CONTROLLER)
    stack_action = {r["t"]: r["action"] for r in stack_rows}

    ecapa = None
    ecapa_path = ECAPA / f"{session}.npz"
    if ecapa_path.is_file():
        blob = np.load(ecapa_path)
        ecapa = {"start": blob["start"], "end": blob["end"], "people": blob["people"]}

    # join nn + voice + frozen p alignment + gold
    for i, row in enumerate(rows):
        global_i = int(idx[0]) + i
        row["gold"] = _gold_at(row["t"], ads) if ads else "unlabeled"
        if row["gold"] == "unlabeled":
            row["cell"] = "cover" if row["action"] == "cover" else "play"
        else:
            row["cell"] = (
                "TP"
                if row["gold"] == "commercial" and row["action"] == "cover"
                else "FN"
                if row["gold"] == "commercial" and row["action"] == "play"
                else "FP"
                if row["gold"] == "program" and row["action"] == "cover"
                else "TN"
            )
        row["stack_action"] = stack_action.get(row["t"])
        # frozen file p if same stamp exists
        j = int(np.searchsorted(frozen_t, row["t"]))
        if j < len(frozen_t) and abs(float(frozen_t[j]) - row["t"]) < 1e-6:
            row["p_frozen_file"] = round(float(frozen_p[j]), 4)
            row["p_recompute_delta"] = round(float(row["p"] - frozen_p[j]), 5)
        if i % NN_EVERY == 0:
            row.update(_nn_scores(emb[global_i], commercial_proto, program_proto))
        voice = _voice_at(session, row["t"], ecapa)
        if voice:
            row.update(voice)

    # acoustic every 2s (load one pad range, slice windows)
    from experiments.audio_learn.splits import SR as TARGET_SR

    origin = left
    audio = np.asarray(load_coverage(session, left, right), dtype=np.float32)
    acoustic_times = np.arange(left + ACOUSTIC_EVERY_S, right + 1e-9, ACOUSTIC_EVERY_S)
    acoustics = []
    for t in acoustic_times:
        a0 = int(round((t - ACOUSTIC_EVERY_S - origin) * TARGET_SR))
        a1 = int(round((t - origin) * TARGET_SR))
        a0 = max(0, a0)
        a1 = min(len(audio), a1)
        if a1 <= a0:
            continue
        m = _measures(audio[a0:a1])
        if not m:
            continue
        entry = {"t": round(float(t), 3), **m}
        acoustics.append(entry)
        nearest = min(rows, key=lambda r: abs(r["t"] - t))
        if abs(nearest["t"] - t) <= ACOUSTIC_EVERY_S / 2 + 0.01:
            nearest["acoustic"] = m

    phases = _phases(rows, t0, t1)
    brief = _brief(name, session, t0, t1, phases, CONTROLLER)

    meta = {
        "session": session,
        "name": name,
        "span": [t0, t1],
        "pad_before_s": pad_before,
        "controller": CONTROLLER,
        "head": str(HEAD),
        "sequence": SEQUENCE,
        "n_hops": len(rows),
        "phases": phases,
        "logging_contract": {
            "hops.jsonl": "one hop per line; controller reason + logit/p + nn + voice",
            "acoustics.jsonl": "2s bed measures on the same clock",
            "ENGINEER_BRIEF.md": "how to read the dump",
            "not_logged": [
                "per-dim GRU attention (head has none)",
                "AudioSet class posteriors on this path",
                "transcript tokens on the mute path",
            ],
        },
    }
    (out / "summary.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (out / "ENGINEER_BRIEF.md").write_text(brief, encoding="utf-8")
    with (out / "hops.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    with (out / "acoustics.jsonl").open("w", encoding="utf-8") as fh:
        for row in acoustics:
            fh.write(json.dumps(row) + "\n")

    # also emit transition-only view for quick grepping
    transitions = [r for r in rows if r["transition"]]
    (out / "transitions.json").write_text(json.dumps(transitions, indent=2), encoding="utf-8")
    print(brief)
    print("wrote", out)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    head = load_head(HEAD, device)
    rng = np.random.default_rng(0)
    print("building train prototypes…", flush=True)
    commercial_proto, program_proto = _train_prototypes(rng)
    print(f"prototypes commercial={len(commercial_proto)} program={len(program_proto)}", flush=True)
    for session, name, t0, t1, pad in FOCUS:
        print(f"\n=== {name} {session} {t0}-{t1} ===", flush=True)
        trace_one(session, name, t0, t1, pad, commercial_proto, program_proto, head, device)


if __name__ == "__main__":
    main()
