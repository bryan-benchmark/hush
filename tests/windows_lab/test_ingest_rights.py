"""Rights gate and WAV verifier for Windows lab ingest."""

from __future__ import annotations

import json
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.capture import write_public_fixture
from tools.windows_lab.ingest import ingest, sha256_file, verify_audio


def test_verify_audio_48k_stereo(tmp_path: Path):
    wav = tmp_path / "t.wav"
    write_public_fixture(wav, seconds=2.0)
    meta = verify_audio(wav)
    assert meta["sample_rate_hz"] == 48000
    assert meta["channels"] == 2
    assert meta["frames"] == 96000
    assert abs(meta["duration_sec"] - 2.0) < 1e-6


def test_unknown_rights_blocked(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data))
    wav = tmp_path / "t.wav"
    write_public_fixture(wav, seconds=1.0)
    with pytest.raises(PermissionError):
        ingest(
            wav,
            source_label="x",
            source_type="test_public_fixture",
            rights_status="unknown",
        )


def test_test_public_ingest_writes_receipt(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data))
    wav = tmp_path / "t.wav"
    write_public_fixture(wav, seconds=1.0)
    digest = sha256_file(wav)
    receipt = ingest(
        wav,
        source_label="synthetic_tone",
        source_type="test_public_fixture",
        rights_status="test_public",
        git_commit="deadbeef",
    )
    assert receipt["file_sha256"] == digest or Path(receipt["file_path"]).exists()
    assert receipt["rights_status"] == "test_public"
    assert receipt["credentials"] is None
    assert receipt["stream_urls"] is None
    side = Path(receipt["receipt_path"])
    loaded = json.loads(side.read_text(encoding="utf-8"))
    assert loaded["node_id"] == "ohush-win-01"
    assert loaded["sample_count"] == 48000


def test_bad_sample_rate_rejected(tmp_path: Path):
    wav = tmp_path / "bad.wav"
    # 44.1 kHz mono — must fail verify
    t = np.linspace(0, 1, 44100, endpoint=False)
    pcm = (0.1 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(pcm.tobytes())
    with pytest.raises(ValueError):
        verify_audio(wav)
