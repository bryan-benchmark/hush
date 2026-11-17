"""Tests for sparse stills / edge-clip visual archive (no live capture)."""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import MEDIA_MODES, ensure_data_layout
from tools.windows_lab.visual_archive import (
    distill_video_to_stills,
    extract_edge_clip,
    read_still_manifest,
    session_archive_info,
    still_filename,
    stills_dir,
    write_visual_archive_meta,
)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def _write_silent_wav(path: Path, *, seconds: float = 2.0, rate: int = 48000) -> None:
    frames = int(seconds * rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * 2 * frames)


def _fake_session(root: Path) -> Path:
    session = root / "authorized_sources" / "streamers_test_session"
    session.mkdir(parents=True, exist_ok=True)
    meta = {
        "session_id": "streamers_test_session",
        "chunk_minutes": 15,
        "media": "av_full",
        "chunks": [{"index": 0, "video": "video_0000.mp4", "audio": "audio_0000.wav", "duration_sec": 2.0}],
        "label_status": "unlabeled",
    }
    (session / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _write_silent_wav(session / "audio_0000.wav", seconds=2.0)
    return session


def test_media_modes_include_av_full():
    assert "av" in MEDIA_MODES
    assert "av_full" in MEDIA_MODES
    assert "audio" in MEDIA_MODES


def test_write_archive_meta_and_info(data_root: Path):
    session = _fake_session(data_root)
    archive = write_visual_archive_meta(session, mode="stills", interval_sec=1.0, still_count=0)
    assert archive["mode"] == "stills"
    assert (stills_dir(session) / "archive.json").is_file()
    # meta.json not clobbered by archive helper
    meta = json.loads((session / "meta.json").read_text(encoding="utf-8"))
    assert meta["session_id"] == "streamers_test_session"
    info = session_archive_info(session)
    assert info["audio_files"] == ["audio_0000.wav"]


def test_distill_renames_and_manifest(data_root: Path, monkeypatch: pytest.MonkeyPatch):
    session = _fake_session(data_root)
    video = session / "video_0000.mp4"
    video.write_bytes(b"not-a-real-mp4")

    def fake_run(cmd, capture_output=True, text=True, timeout=600):  # noqa: ARG001
        # Mimic ffmpeg writing sequential stills for the pattern arg.
        pattern = Path(cmd[-1])
        out_dir = pattern.parent
        for i in range(1, 4):
            (out_dir / pattern.name.replace("%06d", f"{i:06d}")).write_bytes(b"JPEG")
        return type("P", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(
        "tools.windows_lab.visual_archive.ffmpeg_path",
        lambda: "ffmpeg",
    )
    monkeypatch.setattr("tools.windows_lab.visual_archive.subprocess.run", fake_run)

    result = distill_video_to_stills(
        video,
        session_dir=session,
        t0_sec=0.0,
        interval_sec=1.0,
        chunk_index=0,
        delete_video=True,
    )
    assert result["ok"] is True
    assert result["still_count"] == 3
    assert result["deleted_video"] is True
    assert not video.is_file()
    assert (stills_dir(session) / still_filename(0.0)).is_file()
    assert (stills_dir(session) / still_filename(2.0)).is_file()
    rows = read_still_manifest(session)
    assert [r["t_sec"] for r in rows] == [0.0, 1.0, 2.0]


def test_edge_clip_from_stills_and_audio(data_root: Path, monkeypatch: pytest.MonkeyPatch):
    session = _fake_session(data_root)
    # Seed stills around a contested window.
    sdir = stills_dir(session)
    sdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in (10.0, 11.0, 12.0, 13.0, 14.0):
        name = still_filename(t)
        (sdir / name).write_bytes(b"JPEG")
        rows.append({"t_sec": t, "path": f"stills/{name}"})
    (sdir / "manifest.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    meta = json.loads((session / "meta.json").read_text(encoding="utf-8"))
    meta["visual_archive"] = {"mode": "stills", "still_count": 5}
    meta["chunks"] = [{"index": 0, "audio": "audio_0000.wav", "duration_sec": 30.0}]
    (session / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _write_silent_wav(session / "audio_0000.wav", seconds=30.0)

    def fake_run(cmd, capture_output=True, text=True, timeout=120):  # noqa: ARG001
        out = Path(cmd[-1])
        out.write_bytes(b"RIFF")
        return type("P", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr("tools.windows_lab.visual_archive.ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr("tools.windows_lab.visual_archive.subprocess.run", fake_run)

    result = extract_edge_clip(
        session,
        start_s=11.0,
        end_s=13.0,
        pad_sec=1.0,
        label="spot",
        kind="standalone_spot",
    )
    assert result["ok"] is True
    edge = result["edge_clip"]
    assert edge["audio"]
    assert len(edge["stills"]) >= 3
    clip_dir = session / "edge_clips" / edge["id"]
    assert (clip_dir / "edge.json").is_file()
    meta2 = json.loads((session / "meta.json").read_text(encoding="utf-8"))
    assert len(meta2["edge_clips"]) == 1
