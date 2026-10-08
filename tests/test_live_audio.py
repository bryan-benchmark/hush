"""Live transport invariants. No hardware and no frozen detector."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.request
import wave
from array import array
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import live_audio as live  # noqa: E402
from live_server import LiveState, start_live_server  # noqa: E402


def stereo(frames: int, left: int, right: int | None = None) -> bytes:
    if right is None:
        right = left
    samples = array("h")
    for _ in range(frames):
        samples.append(int(left))
        samples.append(int(right))
    return samples.tobytes()


def stereo_ids(start: int, frames: int) -> bytes:
    samples = array("h")
    for index in range(frames):
        ident = (start + index) % 30000
        samples.append(ident)
        samples.append(-ident if ident else 0)
    return samples.tobytes()


def channels(data: bytes) -> tuple[list[int], list[int]]:
    samples = array("h")
    samples.frombytes(data)
    left = [samples[index] for index in range(0, len(samples), 2)]
    right = [samples[index] for index in range(1, len(samples), 2)]
    return left, right


def engine(**kwargs: object) -> live.LiveEngine:
    params = {
        "sample_rate": 48000,
        "prime_ms": 10,
        "capacity_ms": 250,
        "ramp_frames": 0,
    }
    params.update(kwargs)
    return live.LiveEngine(**params)  # type: ignore[arg-type]


class RingTests(unittest.TestCase):
    def test_overflow_drops_oldest_frames(self) -> None:
        ring = live.StereoRing(100)
        ring.write(stereo(100, 1))
        ring.write(stereo(40, 2))
        self.assertEqual(ring.overrun_count(), 1)
        self.assertEqual(ring.fill_frames(), 100)
        played = ring.read_if_available(100)
        self.assertIsNotNone(played)
        left, _right = channels(played or b"")
        self.assertEqual(left[:60], [1] * 60)
        self.assertEqual(left[60:], [2] * 40)

    def test_exact_fill_is_not_an_overrun(self) -> None:
        ring = live.StereoRing(10)
        ring.write(stereo(10, 3))
        self.assertEqual(ring.overrun_count(), 0)
        self.assertEqual(ring.fill_frames(), 10)

    def test_wraps_without_reordering(self) -> None:
        ring = live.StereoRing(10)
        ring.write(stereo_ids(0, 8))
        self.assertEqual(channels(ring.read_if_available(6) or b"")[0], list(range(6)))
        ring.write(stereo_ids(8, 6))
        self.assertEqual(channels(ring.read_if_available(8) or b"")[0], list(range(6, 14)))


class InvariantTests(unittest.TestCase):
    def test_muting_never_stops_input_capture(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.set_mode("manual")
        audio.mute()
        loud = stereo(480, 1000, -2000)
        audio.push_input(loud)
        queued = audio.pop_record()
        self.assertIsNotNone(queued)
        assert queued is not None
        self.assertEqual(queued[1], loud)
        left, right = channels(queued[1])
        self.assertEqual(left[0], 1000)
        self.assertEqual(right[0], -2000)

    def test_muting_never_stops_ring_consumption(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.push_input(stereo(480, 7))
        primed = audio.render_output(480)
        self.assertEqual(audio.transport, "running")
        self.assertEqual(channels(primed)[0], [7] * 480)

        audio.push_input(stereo_ids(0, 480 * 5))
        audio.set_mode("manual")
        audio.mute()
        for _ in range(3):
            muted = audio.render_output(480)
            self.assertEqual(channels(muted)[0], [0] * 480)
        self.assertEqual(audio.ring.fill_frames(), 480 * 2)

        audio.unmute()
        resumed = audio.render_output(480)
        self.assertEqual(channels(resumed)[0], list(range(1440, 1920)))

    def test_recording_drops_never_alter_session_time(self) -> None:
        audio = engine(record_queue_size=1)
        audio.open_transport()
        first = stereo(480, 1000, -1000)
        dropped = stereo(480, 1111, -1111)
        later = stereo(480, 2000, -2000)
        audio.push_input(first)
        audio.push_input(dropped)
        queued_first = audio.pop_record()
        audio.push_input(later)
        queued_later = audio.pop_record()

        self.assertEqual(audio.record_queue_drops, 1)
        self.assertEqual(audio.recording_integrity, "degraded")
        self.assertEqual(audio.xruns, 0)
        self.assertEqual(
            audio.recording_gaps,
            [
                {
                    "start_session_sample": 480,
                    "frames_missing": 480,
                    "duration_ms": 10.0,
                }
            ],
        )
        self.assertEqual(audio.session_samples, 1440)
        assert queued_first is not None and queued_later is not None
        self.assertEqual(queued_first, (0, first))
        self.assertEqual(queued_later[0], 960)
        self.assertEqual(queued_later[1], later)

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            wav = live.WavSession(
                folder,
                48000,
                2,
                __import__("datetime").datetime.now().astimezone(),
                frames_per_chunk=480,
            )
            wav.write_block(*queued_first)
            wav.write_block(*queued_later)
            wav.finish(audio.session_samples)
            self.assertEqual(wav.written, 1440)
            files = sorted(folder.glob("audio_*.wav"))
            self.assertEqual([path.name for path in files], ["audio_0001.wav", "audio_0002.wav", "audio_0003.wav"])
            blocks = [_read_wav(path) for path in files]
            self.assertEqual(channels(blocks[0])[0], [1000] * 480)
            self.assertEqual(channels(blocks[1])[0], [0] * 480)
            self.assertEqual(channels(blocks[2])[0], [2000] * 480)
            self.assertEqual(wav.chunks[1]["start_elapsed_seconds"], 0.01)
            self.assertEqual(wav.chunks[2]["start_elapsed_seconds"], 0.02)

    def test_trailing_drop_is_padded_to_the_session_clock(self) -> None:
        audio = engine(record_queue_size=1)
        audio.open_transport()
        audio.push_input(stereo(480, 5))
        audio.push_input(stereo(480, 9))
        queued = audio.pop_record()
        assert queued is not None
        with tempfile.TemporaryDirectory() as tmp:
            wav = live.WavSession(
                Path(tmp),
                48000,
                2,
                __import__("datetime").datetime.now().astimezone(),
                frames_per_chunk=4800,
            )
            wav.write_block(*queued)
            wav.finish(audio.session_samples)
            self.assertEqual(wav.written, 960)
            audio_path = next(Path(tmp).glob("audio_*.wav"))
            left, _right = channels(_read_wav(audio_path))
            self.assertEqual(left[:480], [5] * 480)
            self.assertEqual(left[480:], [0] * 480)


class GateTests(unittest.TestCase):
    def test_playback_keeps_left_and_right(self) -> None:
        audio = engine()
        audio.open_transport()
        block = stereo(480, 1000, -2000)
        audio.push_input(block)
        played = audio.render_output(480)
        left, right = channels(played)
        self.assertEqual(left, [1000] * 480)
        self.assertEqual(right, [-2000] * 480)

    def test_pass_through_ignores_mute(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.set_mode("pass_through")
        with self.assertRaises(live.LiveControlError):
            audio.mute()
        self.assertEqual(audio.gate, "play")

    def test_auto_cannot_mute(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.set_mode("auto")
        with self.assertRaisesRegex(live.LiveControlError, "discontinuity_causal_v1"):
            audio.mute()
        self.assertEqual(audio.gate, "play")

    def test_leaving_manual_returns_to_play(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.set_mode("manual")
        audio.mute()
        audio.set_mode("pass_through")
        self.assertEqual(audio.gate, "play")
        event = audio.manual_mute_events[0]
        self.assertEqual(event["trigger"], "manual")
        self.assertIsNotNone(event["end_session_sample"])

    def test_test_mute_ends_on_the_input_sample_clock(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.push_input(stereo(1000, 1))
        audio.set_mode("manual")
        audio.test_mute(2)
        self.assertEqual(audio.manual_mute_events[0]["start_session_sample"], 1000)
        self.assertEqual(audio.manual_mute_events[0]["start_elapsed_seconds"], round(1000 / 48000, 6))
        audio.push_input(stereo(95999, 1))
        audio.tick()
        self.assertEqual(audio.gate, "mute")
        audio.push_input(stereo(1, 1))
        self.assertEqual(audio.gate, "play")
        event = audio.manual_mute_events[0]
        self.assertEqual(event["end_session_sample"], 97000)
        self.assertEqual(event["end_elapsed_seconds"], round(97000 / 48000, 6))
        self.assertEqual(event["trigger"], "manual")

    def test_hold_mute_does_not_expire(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.set_mode("manual")
        audio.mute()
        audio.push_input(stereo(48000, 1))
        audio.tick()
        self.assertEqual(audio.gate, "mute")
        audio.unmute()
        self.assertEqual(audio.gate, "play")
        self.assertEqual(audio.manual_mute_events[0]["end_session_sample"], 48000)

    def test_fail_safe_returns_to_play(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.set_mode("manual")
        audio.mute()
        audio.fail_safe("detector crashed")
        self.assertEqual(audio.gate, "play")
        self.assertEqual(audio.last_fail_safe, "detector crashed")
        self.assertIsNotNone(audio.manual_mute_events[0]["end_session_sample"])

    def test_stall_and_disconnect_return_to_play(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.note_heartbeats(100.0)
        self.assertFalse(audio.callback_stalled(100.4))
        self.assertTrue(audio.callback_stalled(100.6))
        audio.set_mode("manual")
        audio.mute()
        audio.mark_stalled()
        self.assertEqual(audio.gate, "play")
        self.assertTrue(audio.engine_stalled)
        audio.set_mode("manual")
        audio.mute()
        audio.mark_disconnected("input")
        self.assertTrue(audio.input_disconnected)
        self.assertEqual(audio.gate, "play")


class TransportTests(unittest.TestCase):
    def test_priming_is_silent_and_does_not_count_as_an_underrun(self) -> None:
        audio = engine()
        audio.open_transport()
        self.assertEqual(channels(audio.render_output(480))[0], [0] * 480)
        self.assertEqual(audio.transport, "priming")
        self.assertEqual(audio.ring_underruns, 0)
        self.assertEqual(audio.reprime_count, 0)

    def test_underrun_reprimes_instead_of_stuttering(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.push_input(stereo(480, 1))
        audio.render_output(480)
        self.assertEqual(audio.transport, "running")

        gap = audio.render_output(480)
        self.assertEqual(channels(gap)[0], [0] * 480)
        self.assertEqual(audio.transport, "priming")
        self.assertEqual(audio.ring_underruns, 1)
        self.assertEqual(audio.reprime_count, 1)

        audio.push_input(stereo(200, 9))
        held = audio.render_output(480)
        self.assertEqual(channels(held)[0], [0] * 480)
        self.assertEqual(audio.transport, "priming")
        self.assertEqual(audio.ring.fill_frames(), 200)
        self.assertEqual(audio.ring_underruns, 1)

        audio.push_input(stereo(280, 9))
        resumed = audio.render_output(480)
        self.assertEqual(audio.transport, "running")
        self.assertEqual(channels(resumed)[0], [9] * 480)
        self.assertEqual(audio.ring.fill_frames(), 0)

    def test_input_silence_needs_the_full_duration(self) -> None:
        audio = engine(sample_rate=1000, silence_seconds=5, prime_ms=40)
        audio.open_transport()
        audio.push_input(stereo(4999, 0))
        self.assertFalse(audio.input_silent)
        audio.push_input(stereo(1, 0))
        self.assertTrue(audio.input_silent)
        audio.push_input(stereo(1, 1000))
        self.assertFalse(audio.input_silent)

    def test_muted_output_is_silent_while_input_level_moves(self) -> None:
        audio = engine()
        audio.open_transport()
        audio.push_input(stereo(480, 1000, -1000))
        audio.render_output(480)
        audio.set_mode("manual")
        audio.mute()
        audio.push_input(stereo(480, 4000, -4000))
        muted = audio.render_output(480)
        snap = audio.snapshot()
        self.assertEqual(channels(muted)[0], [0] * 480)
        self.assertGreater(snap["input_dbfs"], -40)
        self.assertEqual(snap["output_dbfs"], -100.0)
        self.assertEqual(snap["dbfs"], snap["input_dbfs"])


class DeviceAndRateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.devices = [
            {
                "index": 0,
                "name": "MacBook Microphone",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 48000.0,
            },
            {
                "index": 2,
                "name": "Cubilux SPDIF ReceiverSolid ",
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 48000.0,
            },
            {
                "index": 3,
                "name": "External Headphones",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 44100.0,
            },
        ]

    def test_exact_name_does_not_fall_back(self) -> None:
        found = live.resolve_live_device(
            "Cubilux SPDIF ReceiverSolid ",
            "input",
            self.devices,
        )
        self.assertEqual(found["index"], 2)
        with self.assertRaisesRegex(live.LiveControlError, "not available"):
            live.resolve_live_device("Cubilux", "input", self.devices)
        with self.assertRaisesRegex(live.LiveControlError, "default device"):
            live.resolve_live_device(None, "output", self.devices)
        headphones = live.resolve_live_device(3, "output", self.devices)
        self.assertEqual(headphones["name"], "External Headphones")

    def test_sample_rate_mismatch_is_explicit(self) -> None:
        self.assertFalse(live.rates_mismatch(48000, 48000, 48000, 48000, 48000))
        self.assertTrue(live.rates_mismatch(48000, 48000, 44100, 48000, 44100))
        self.assertTrue(live.rates_mismatch(48000, 48000, 48000, 48000, 44100))
        self.assertTrue(
            live.host_resampling(48000, 48000, 48000, 44100)
        )


class ControlApiTests(unittest.TestCase):
    def test_gate_command_rejects_pass_through(self) -> None:
        host = live.LiveHost(
            SimpleNamespace(
                samplerate=48000,
                channels=2,
                chunk_minutes=15,
                seconds=0,
                output="recordings",
                live_host="127.0.0.1",
                live_port=0,
                input_device=None,
                output_device=None,
            )
        )
        host.engine.open_transport()
        rejected = host._handle("gate", {"action": "test_mute"})
        self.assertFalse(rejected["ok"])
        self.assertIn("PASS-THROUGH", rejected["error"])
        host.engine.set_mode("auto")
        auto = host._handle("gate", {"action": "mute"})
        self.assertFalse(auto["ok"])
        self.assertIn("discontinuity_causal_v1", auto["error"])

    def test_http_mode_and_devices(self) -> None:
        seen: dict[str, object] = {}

        def on_command(name: str, body: dict[str, object]) -> dict[str, object]:
            seen["name"] = name
            seen["body"] = body
            return {"ok": True, "mode": body.get("mode")}

        state = LiveState()
        server = start_live_server(
            state,
            lambda _kind, _note: None,
            host="127.0.0.1",
            port=0,
            on_command=on_command,
            devices_provider=lambda: {
                "inputs": [{"index": 2, "name": "USB Audio Device"}],
                "outputs": [{"index": 3, "name": "External Headphones"}],
            },
        )
        try:
            port = server.server_address[1]
            devices = _get_json(f"http://127.0.0.1:{port}/devices")
            self.assertEqual(devices["inputs"][0]["name"], "USB Audio Device")
            result = _post_json(
                f"http://127.0.0.1:{port}/mode",
                {"mode": "manual"},
            )
            self.assertTrue(result["ok"])
            self.assertEqual(seen["name"], "mode")
            self.assertEqual(seen["body"], {"mode": "manual"})
        finally:
            server.shutdown()
            server.server_close()


def _read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as handle:
        return handle.readframes(handle.getnframes())


def _get_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url) as response:
        body = json.loads(response.read().decode("utf-8"))
    assert isinstance(body, dict)
    return body


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        body = json.loads(response.read().decode("utf-8"))
    assert isinstance(body, dict)
    return body


if __name__ == "__main__":
    unittest.main()
