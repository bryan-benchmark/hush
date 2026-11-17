"""Vision encode / prompt efficiency helpers (no live Ollama required)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from tools.windows_lab.farm_draft import (
    VISION_MAX_EDGE,
    _still_jpeg_b64,
    describe_still,
)


def test_still_jpeg_downscales(tmp_path: Path) -> None:
    src = tmp_path / "big.jpg"
    Image.new("RGB", (1920, 1080), color=(40, 80, 120)).save(src, quality=95)
    b64, meta = _still_jpeg_b64(src)
    assert b64
    assert meta["src_w"] == 1920
    assert max(meta["out_w"], meta["out_h"]) <= VISION_MAX_EDGE


def test_qwen_uses_single_prompt(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "frame.jpg"
    Image.new("RGB", (800, 450), color=(30, 30, 30)).save(src)
    # Not black enough to short-circuit? mean may be 30 — force past dead check.
    Image.new("RGB", (800, 450), color=(80, 90, 100)).save(src)

    calls: list[str] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"response":"A sports scorebug and two anchors on a desk."}'

    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        import json

        body = json.loads(req.data.decode())
        calls.append(body["prompt"])
        assert len(body["images"]) == 1
        return _Resp()

    monkeypatch.setattr("tools.windows_lab.farm_draft.urlopen", fake_urlopen)
    out = describe_still(src, model="qwen2.5vl:7b")
    assert out["ok"] is True
    assert len(calls) == 1


def test_moondream_keeps_second_prompt_on_empty(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "frame.jpg"
    Image.new("RGB", (800, 450), color=(80, 90, 100)).save(src)
    calls: list[str] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"response":""}'

    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        import json

        body = json.loads(req.data.decode())
        calls.append(body["prompt"])
        return _Resp()

    monkeypatch.setattr("tools.windows_lab.farm_draft.urlopen", fake_urlopen)
    out = describe_still(src, model="moondream")
    assert out["ok"] is False
    assert len(calls) == 2
