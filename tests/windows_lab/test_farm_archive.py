"""Farm prepare / package retain set (no rclone / Ollama required)."""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_archive import prepare_take, write_package_index
from tools.windows_lab.farm_draft import _auto_accept


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def _write_silent_wav(path: Path, seconds: float = 2.0, rate: int = 48000) -> None:
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n * 2)


def test_auto_accept_gate():
    assert _auto_accept({"bucket": "paid_ad", "confidence": "high"}, "GEICO hump day savings")
    assert not _auto_accept({"bucket": "paid_ad", "confidence": "high"}, "touchdown on the yard line")
    assert not _auto_accept({"bucket": "paid_ad", "confidence": "medium"}, "order now at chili's")
    assert not _auto_accept({"bucket": "program", "confidence": "high"}, "order now")


def test_prepare_writes_facts_and_drops_video(data_root: Path):
    take = data_root / "work" / "capture" / "streamers" / "20261110T1200Z_test"
    take.mkdir(parents=True)
    _write_silent_wav(take / "audio.wav", seconds=2.0)
    (take / "video.mp4").write_bytes(b"fake-video")
    (take / "label_aid.json").write_text(
        json.dumps(
            {
                "session": take.name,
                "timeline": [{"t_s": 0, "kind": "commercial", "brand": "TestCo", "notes": "ad"}],
            }
        ),
        encoding="utf-8",
    )
    stills = take / "stills"
    stills.mkdir()
    (stills / "still_t00000.0.jpg").write_bytes(b"jpeg")
    (stills / "still_t00001.0.jpg").write_bytes(b"jpeg")

    out = prepare_take(take, delete_video=True, purge_stills=False)
    assert out["ok"] is True
    assert not (take / "video.mp4").exists()
    assert (take / "timeline_facts.jsonl").is_file()
    assert (take / "label_manifest.json").is_file()
    facts = [
        json.loads(line)
        for line in (take / "timeline_facts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(r.get("source") == "label_aid" for r in facts)
    assert any(r.get("source") == "still_index" for r in facts)

    pkg = write_package_index(data_root)
    assert pkg["ok"] is True
    assert pkg["objects"] >= 1
    paths = [json.loads(line)["path"] for line in Path(pkg["manifest"]).read_text().splitlines() if line]
    assert "audio.wav" in paths
    assert all(not p.startswith("stills/") for p in paths)
