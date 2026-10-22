"""Pull the vocal stem with Hybrid Demucs, then ask SpeechBrain again.

Reads the clips already chosen in VOICE_PEEL_001. The 0.25 line stays put.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import read_span  # noqa: E402
from experiments.measurement.break_trace_001 import booth_bank  # noqa: E402
from experiments.measurement.voice_peel_001 import DECISIONS, embed  # noqa: E402
from hush.audio import find_session, load_session  # noqa: E402
from hush.experiment002 import EMBEDDING_MODEL_ID, _load_encoder  # noqa: E402
from hush.speaker_memory import MATCH_COSINE, SR  # noqa: E402

OUT = REPO / "docs/ohush/research/VOICE_PEEL_001/results.json"
MODEL = REPO / "experiments/exp002/models" / EMBEDDING_MODEL_ID.split("/")[-1]
DEMUX_SR = 44100


def to_demucs(stereo: np.ndarray) -> torch.Tensor:
    # 48000 -> 44100, shape (channels, time)
    converted = resample_poly(stereo, 147, 160, axis=0).astype(np.float32)
    return torch.from_numpy(np.ascontiguousarray(converted.T))


def vocal_16k(model, stereo: np.ndarray) -> np.ndarray:
    mix = to_demucs(stereo)
    # Hybrid Demucs wants a reasonably long chunk. Pad, then crop back.
    pad = (-mix.shape[-1]) % 44100
    if pad:
        mix = torch.nn.functional.pad(mix, (0, pad))
    with torch.inference_mode():
        stems = model(mix.unsqueeze(0))
    vocals = stems[0, 3].mean(dim=0).cpu().numpy()
    vocals = vocals[: mix.shape[-1] - pad] if pad else vocals
    return resample_poly(vocals, SR, DEMUX_SR).astype(np.float32)


def main() -> None:
    from torchaudio.pipelines import HDEMUCS_HIGH_MUSDB

    payload = json.loads(OUT.read_text())
    banks = booth_bank()
    shows = {}
    for line in DECISIONS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            shows.setdefault(row["session"], row.get("show"))
    encoder = _load_encoder(MODEL, "cpu")
    separator = HDEMUCS_HIGH_MUSDB.get_model().cpu().eval()
    sessions = {}
    for row in payload["clips"]:
        if row["session"] not in sessions:
            folder = find_session(REPO / "recordings", row["session"])
            sessions[row["session"]] = (folder, load_session(folder))
        folder, meta = sessions[row["session"]]
        stereo = read_span(folder, meta, max(0.0, row["start"] - 1.0), row["end"] + 1.0)
        vocal = vocal_16k(separator, stereo)
        # The extra second on each side was only context for the separator.
        lead = int(SR * min(1.0, row["start"]))
        span = int(round((row["end"] - row["start"]) * SR))
        vocal = vocal[lead : lead + span]
        bank = banks[shows[row["session"]]]
        names = list(bank)
        matrix = np.vstack([bank[name] for name in names])
        vector = embed(encoder, vocal)
        scores = vector @ matrix.T
        slot = int(np.argmax(scores))
        row["demucs"] = round(float(scores[slot]), 3)
        row["demucs_name"] = names[slot]
        row["demucs_over"] = row["demucs"] >= MATCH_COSINE
        print(row["kind"], row["network"], row["stored"], "->", row["demucs"], row["demucs_name"], flush=True)
    for kind in ("miss", "ad"):
        group = [row for row in payload["clips"] if row["kind"] == kind]
        payload["summary"][kind]["demucs_vocal_at_or_over_0.25"] = sum(1 for row in group if row["demucs_over"])
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
