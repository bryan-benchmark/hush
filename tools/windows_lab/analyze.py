"""Non-mutating analysis subset for Node 01.

Runs existing qa_audio heuristics and optional causal feature extraction.
Does not change thresholds, gold, or Universal baselines.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

from . import NODE_ID, __version__
from .config import ensure_data_layout

# Repo root: tools/windows_lab/analyze.py → parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


def run_qa(path: Path) -> dict:
    from qa_audio import analyze as qa_analyze

    return qa_analyze(path)


def run_features_smoke(path: Path, max_seconds: float = 30.0) -> dict:
    """Compute exp001 mono_features on a short prefix — read-only smoke."""
    from hush.features import FEATURE_SCHEMA_VERSION, mono_features

    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if sr != 48000:
        raise ValueError(f"features smoke expects 48 kHz, got {sr}")
    n = min(audio.shape[0], int(max_seconds * sr))
    # Research pipeline often resamples to 16 kHz mono; keep 48k for QA fidelity
    # and downsample here only for the feature smoke (non-mutating copy).
    mono48 = audio[:n].mean(axis=1).astype(np.float32)
    target_sr = 16000
    idx = np.round(np.linspace(0, n - 1, int(n * target_sr / sr))).astype(np.int64)
    mono = mono48[idx]
    feats = mono_features(mono, target_sr)
    summary = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "samples_used_48k": int(n),
        "samples_used_16k": int(mono.shape[0]),
        "duration_sec": round(n / sr, 3),
        "keys": sorted(feats.keys())[:40],
    }
    for k in ("timestamp_seconds", "rms_dbfs", "silence_fraction"):
        if k in feats:
            arr = np.asarray(feats[k])
            summary[f"{k}_n"] = int(arr.size)
            if arr.size:
                summary[f"{k}_head"] = float(arr.flat[0])
    return summary


def analyze_file(path: Path, *, features: bool = True) -> dict:
    path = Path(path)
    root = ensure_data_layout()
    qa = run_qa(path)
    out = {
        "node_id": NODE_ID,
        "analysis_version": __version__,
        "analyzed_utc": datetime.now(timezone.utc).isoformat(),
        "path": str(path),
        "qa": qa,
        "features_smoke": None,
        "features_error": None,
    }
    if features:
        try:
            out["features_smoke"] = run_features_smoke(path)
        except Exception as e:
            out["features_error"] = str(e)

    work = root / "work" / "analyze"
    work.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = work / f"analyze_{stamp}_{path.stem}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    out["report_path"] = str(out_path)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Analyze one local WAV with OHush QA (+ optional features)")
    p.add_argument("path", type=Path)
    p.add_argument("--no-features", action="store_true")
    args = p.parse_args(argv)
    try:
        report = analyze_file(args.path, features=not args.no_features)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({"ok": True, "report": report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
