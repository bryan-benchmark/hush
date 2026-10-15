"""Exp002-style speaker continuity for OHUSH_LIVE_V0.

Reads float32 mono at 16 kHz on stdin. Model files go under ohush_live/cache,
never under experiments/.

Product booth lock: top announcer voices (Al, color, etc.) are persisted with
prototypes so intro/outro recognition survives an engine bounce. Hearing any
booth voice always signals program.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

CACHE = REPO / "ohush_live" / "cache"
BOOTH_PATH = REPO / "ohush_live" / "sessions" / ".booth.json"
BOOTH_CANDIDATES_PATH = REPO / "ohush_live" / "sessions" / ".booth_candidates.json"
os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE / "hf" / "hub"))
os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))

from hush.speaker_memory import (  # noqa: E402
    CONTINUITY_WINDOW_S,
    DROP_MIN,
    DROP_WINDOW_S,
    EMBED_WIN_S,
    EMBEDDING_MODEL_ID,
    MATCH_COSINE,
    OnlineSpeakerMemory,
    RETURN_EVENT_MIN,
    SR,
    VAD_MIN_SILENCE_MS,
    VAD_MIN_SPEECH_MS,
    VAD_SPEECH_PAD_MS,
    VAD_THRESHOLD,
    _Cluster,
    _unit,
)
from ohush_live.policy import (  # noqa: E402
    BOOTH_MIN_CUMULATIVE_S,
    BOOTH_MIN_OCCURRENCES,
    BOOTH_TOP_N,
    SPEAKER_BOOTH_MATCH,
    SPEAKER_DROP,
    SPEAKER_RETURN,
)


def main() -> None:
    import torch
    from silero_vad import load_silero_vad
    from speechbrain.inference.speaker import EncoderClassifier

    torch.set_num_threads(1)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    torch.set_grad_enabled(False)
    torch.backends.nnpack.set_flags(False)
    vad = load_silero_vad()
    savedir = CACHE / "spkrec-ecapa-voxceleb"
    savedir.mkdir(parents=True, exist_ok=True)
    encoder = EncoderClassifier.from_hparams(
        source=EMBEDDING_MODEL_ID,
        savedir=str(savedir),
        run_opts={"device": "cpu"},
    )
    memory = OnlineSpeakerMemory()
    booth_protos = _load_booth()
    _seed_memory(memory, booth_protos)
    history: list[dict] = []
    continuity_hist: list[tuple[float, float]] = []
    buf = np.zeros(0, dtype=np.float32)
    seen = 0
    hop = SR
    win = int(EMBED_WIN_S * SR)
    print(
        json.dumps(
            {
                "family": "speaker",
                "available": True,
                "match_cosine": MATCH_COSINE,
                "booth_ids": sorted(booth_protos),
            }
        ),
        flush=True,
    )
    while True:
        block = sys.stdin.buffer.read(hop * 4)
        if not block:
            return
        samples = np.frombuffer(block, dtype=np.float32).copy()
        buf = np.concatenate([buf, samples])
        seen += samples.size
        now = seen / SR
        if buf.size < win:
            continue
        frame = buf[-win:]
        speech = _speech_seconds(vad, frame)
        if speech < 0.5:
            booth = _booth_ids(memory, booth_protos)
            print(
                json.dumps(
                    {
                        "family": "speaker",
                        "t": round(now, 3),
                        "departure": None,
                        "strong_departure": False,
                        "return": 0.0,
                        "strong_return": False,
                        "speech": False,
                        "recurring": False,
                        "booth_present": False,
                        "booth_ids": sorted(booth),
                        "continuity": None,
                    }
                ),
                flush=True,
            )
            buf = buf[-win * 4 :]
            continue
        start = now - EMBED_WIN_S
        emb = _embed(encoder, frame)
        row = memory.observe(emb, start, now)
        history.append(row)
        cont = _continuity(history, now)
        continuity_hist.append((now, cont if cont is not None else float("nan")))
        prior = [value for t, value in continuity_hist if now - DROP_WINDOW_S <= t < now - 1e-6 and np.isfinite(value)]
        drop = None
        strong = False
        if cont is not None and prior:
            drop = max(prior) - cont
            strong = drop + 1e-9 >= max(DROP_MIN, SPEAKER_DROP)
        ret = float(row["program_speaker_return_score"])
        booth = _booth_ids(memory, booth_protos)
        cluster_id = row.get("assigned_cluster_id")
        recurring = bool(row.get("speaker_is_recurring"))
        sim_booth = _similarity_to_booth(emb, memory, booth_protos, booth)
        # Verified booth only: known trusted id or strong prototype match.
        # Recurring / continuity alone is NOT booth identity.
        # A trusted cluster id sets the flag even when this frame's similarity
        # is low. state._booth_match does not treat that contradiction as a
        # live return. Identity of these ids across restarts is unaudited.
        booth_present = bool(cluster_id and cluster_id in booth)
        if sim_booth is not None and sim_booth + 1e-9 >= SPEAKER_BOOTH_MATCH:
            booth_present = True
        # Trusted set is frozen for auto-promotion. Refresh embeddings only for
        # IDs already trusted; quarantine new talkers as candidates (Defect D).
        if cluster_id:
            unit = _unit(emb)
            if cluster_id in booth_protos:
                booth_protos[str(cluster_id)] = unit.tolist()
                _save_booth(booth_protos)
            elif booth_present:
                for bid, proto in list(booth_protos.items()):
                    if not proto:
                        continue
                    try:
                        prior = _unit(np.asarray(proto, dtype=np.float64))
                    except Exception:
                        continue
                    if float(np.dot(unit, prior)) >= SPEAKER_BOOTH_MATCH:
                        booth_protos[bid] = unit.tolist()
                _save_booth(booth_protos)
            else:
                _note_booth_candidate(str(cluster_id), unit.tolist(), recurring=recurring)
            booth = _booth_ids(memory, booth_protos)
        if booth_present:
            ret = max(ret, 1.0)
        print(
            json.dumps(
                {
                    "family": "speaker",
                    "t": round(now, 3),
                    "departure": None if drop is None else round(drop, 4),
                    "strong_departure": bool(strong),
                    "return": round(ret, 4),
                    "strong_return": bool(booth_present)
                    or ret + 1e-9 >= max(RETURN_EVENT_MIN, SPEAKER_RETURN),
                    "speech": True,
                    "recurring": recurring,
                    "booth_present": booth_present,
                    "booth_ids": sorted(booth),
                    "cluster_id": cluster_id,
                    "similarity_to_booth": None if sim_booth is None else round(sim_booth, 4),
                    "continuity": None if cont is None else round(cont, 4),
                }
            ),
            flush=True,
        )
        if buf.size > win * 8:
            buf = buf[-win * 4 :]


def _booth_ids(memory: OnlineSpeakerMemory, booth_protos: dict[str, list[float]]) -> set[str]:
    """Trusted announcer IDs only — never auto-promote top recurring talkers."""
    del memory  # live ranking is quarantined; see _note_booth_candidate
    return set(booth_protos)


def _note_booth_candidate(cluster_id: str, proto: list[float], *, recurring: bool) -> None:
    """Quarantine unverified voices; do not merge into trusted .booth.json."""
    try:
        raw = json.loads(BOOTH_CANDIDATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {"product": "OHUSH_LIVE_V0", "candidates": {}}
    cands = raw.setdefault("candidates", {})
    entry = cands.get(cluster_id) or {"hits": 0, "recurring_hits": 0, "proto": proto}
    entry["hits"] = int(entry.get("hits") or 0) + 1
    if recurring:
        entry["recurring_hits"] = int(entry.get("recurring_hits") or 0) + 1
    entry["proto"] = proto
    cands[cluster_id] = entry
    # Cap file growth.
    if len(cands) > 32:
        ranked = sorted(cands.items(), key=lambda item: item[1].get("hits", 0), reverse=True)[:32]
        raw["candidates"] = {key: value for key, value in ranked}
    BOOTH_CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOOTH_CANDIDATES_PATH.write_text(json.dumps(raw) + "\n", encoding="utf-8")


def _similarity_to_booth(
    emb: np.ndarray,
    memory: OnlineSpeakerMemory,
    booth_protos: dict[str, list[float]],
    booth_ids: set[str],
) -> float | None:
    """Match current speech to any locked announcer — even if cluster id drifted."""
    unit = _unit(emb)
    best: float | None = None
    for bid, proto in booth_protos.items():
        if not proto:
            continue
        try:
            sim = float(np.dot(unit, _unit(np.asarray(proto, dtype=np.float64))))
        except Exception:
            continue
        best = sim if best is None else max(best, sim)
    for cluster in memory.clusters:
        if cluster.cluster_id not in booth_ids:
            continue
        sim = float(np.dot(unit, cluster.proto))
        best = sim if best is None else max(best, sim)
    return best


def _load_booth() -> dict[str, list[float]]:
    """Return id -> prototype. Empty list means id known, embedding not yet saved."""
    try:
        raw = json.loads(BOOTH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[float]] = {}
    protos = raw.get("protos") if isinstance(raw.get("protos"), dict) else None
    if isinstance(protos, dict):
        for key, value in protos.items():
            if isinstance(value, list) and value:
                out[str(key)] = [float(x) for x in value]
            else:
                out[str(key)] = []
    ids = raw.get("ids")
    if isinstance(ids, list):
        for key in ids:
            out.setdefault(str(key), [])
    if not out and all(isinstance(v, list) for v in raw.values()):
        # Legacy shape: {cluster_id: proto}
        for key, value in raw.items():
            if isinstance(value, list) and value:
                out[str(key)] = [float(x) for x in value]
    return out


def _save_booth(booth_protos: dict[str, list[float]]) -> None:
    if not booth_protos:
        return
    BOOTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Cap to top crew so ad voices do not accumulate forever.
    # Prefer entries that already have embeddings.
    ranked = sorted(
        booth_protos.items(),
        key=lambda item: (1 if item[1] else 0, len(item[1])),
        reverse=True,
    )[: max(BOOTH_TOP_N, 4)]
    payload = {
        "product": "OHUSH_LIVE_V0",
        "ids": [key for key, _ in ranked],
        "protos": {key: value for key, value in ranked if value},
    }
    BOOTH_PATH.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _seed_memory(memory: OnlineSpeakerMemory, booth_protos: dict[str, list[float]]) -> None:
    """Warm the matcher with last game's announcer voices."""
    for index, (cid, proto) in enumerate(booth_protos.items(), start=1):
        if not proto:
            continue
        try:
            arr = _unit(np.asarray(proto, dtype=np.float64))
        except Exception:
            continue
        memory.clusters.append(
            _Cluster(
                cluster_id=cid if str(cid).startswith("c") else f"booth{index:02d}",
                proto=arr.copy(),
                n_emb=8,
                cum_s=max(BOOTH_MIN_CUMULATIVE_S, 12.0),
                first_seen=0.0,
                last_seen=0.0,
                occurrence_count=max(BOOTH_MIN_OCCURRENCES, 4),
            )
        )
    if any(booth_protos.values()):
        memory._next_id = max(memory._next_id, len(memory.clusters) + 1)


def _speech_seconds(vad, frame: np.ndarray) -> float:
    import torch
    from silero_vad import get_speech_timestamps

    stamps = get_speech_timestamps(
        torch.from_numpy(frame),
        vad,
        threshold=VAD_THRESHOLD,
        sampling_rate=SR,
        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_SPEECH_PAD_MS,
        return_seconds=True,
    )
    return float(sum(float(item["end"]) - float(item["start"]) for item in stamps))


def _embed(encoder, frame: np.ndarray) -> np.ndarray:
    import torch

    with torch.inference_mode():
        batch = torch.from_numpy(frame.astype(np.float32)[None, :])
        encoded = encoder.encode_batch(batch, normalize=False)
        arr = encoded.detach().float().cpu().numpy()
        arr = np.squeeze(arr)
    return np.asarray(arr, dtype=np.float64)


def _continuity(history: list[dict], now: float) -> float | None:
    chunk = [row for row in history if now - CONTINUITY_WINDOW_S <= row["window_end"] <= now + 1e-6]
    if not chunk:
        return None
    return float(
        np.mean(
            [
                (row["similarity_to_best_known"] or 0.0) if row["speaker_is_recurring"] else 0.0
                for row in chunk
            ]
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"family": "speaker", "available": False, "error": str(exc)}), flush=True)
        raise
