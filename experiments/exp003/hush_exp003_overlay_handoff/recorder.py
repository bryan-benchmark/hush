#!/usr/bin/env python3
"""
Hush audio recorder for macOS.

- Records USB/optical audio as stereo 48 kHz, 16-bit PCM WAV.
- Splits long sessions into chunks.
- Shows a live peak meter (terminal + localhost monitor).
- Saves rough labels:
      a + Enter = ad starts
      c + Enter = content starts
      n text    = note
- Ctrl+C stops cleanly.
"""

import argparse
import json
import math
import queue
import select
import signal
import sys
import time
import wave
from array import array
from datetime import datetime
from pathlib import Path

import sounddevice as sd

from live_server import LiveState, start_live_server

audio_q = queue.Queue(maxsize=256)
warnings = []
stop = False


def on_signal(*_):
    global stop
    stop = True


def callback(indata, frames, time_info, status):
    if status:
        warnings.append(str(status))

    try:
        audio_q.put_nowait(bytes(indata))
    except queue.Full:
        warnings.append("Audio queue overflow: a block was dropped.")


def list_devices():
    print("\nINPUT DEVICES\n")

    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            default = "  <-- default" if i == sd.default.device[0] else ""

            print(
                f"{i:>2}: {d['name']} | "
                f"{int(d['max_input_channels'])} input ch | "
                f"{d['default_samplerate']:.0f} Hz{default}"
            )

    print("\nOUTPUT DEVICES\n")

    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            default = "  <-- default" if i == sd.default.device[1] else ""
            print(
                f"{i:>2}: {d['name']} | "
                f"{int(d['max_output_channels'])} output ch | "
                f"{d['default_samplerate']:.0f} Hz{default}"
            )


def resolve_device(value):
    if value is None:
        return int(sd.default.device[0])

    try:
        return int(value)
    except ValueError:
        pass

    matches = []

    for i, d in enumerate(sd.query_devices()):
        if (
            d["max_input_channels"] > 0
            and value.lower() in d["name"].lower()
        ):
            matches.append(i)

    if len(matches) == 1:
        return matches[0]

    if not matches:
        raise RuntimeError(
            f'No input device matched "{value}". Run --list.'
        )

    raise RuntimeError(
        f'Multiple devices matched "{value}": {matches}. '
        "Use an index."
    )


def peak_dbfs(data):
    samples = array("h")
    samples.frombytes(data)

    if not samples:
        return -100.0

    peak = max(abs(x) for x in samples)

    if peak == 0:
        return -100.0

    return 20 * math.log10(peak / 32768.0)


def new_wav(folder, number, channels, rate):
    path = folder / f"audio_{number:04d}.wav"

    f = wave.open(str(path), "wb")
    f.setnchannels(channels)
    f.setsampwidth(2)
    f.setframerate(rate)

    return f, path


CONTENT_TYPES = ("sports", "scripted", "reality", "news", "movie", "other")
DELIVERIES = ("linear", "streaming")
CATALOG_COLUMNS = (
    "session_id",
    "date",
    "content_type",
    "delivery",
    "network_or_service",
    "show",
    "notes",
    "started_local",
    "duration_s",
    "role",
)


def save_json(path, data):
    path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def capture_identity(content_type, delivery, network_or_service, show="", notes="", one_program=True):
    """Identity that has to be known when Record is pressed, not reconstructed later."""
    if content_type not in CONTENT_TYPES:
        raise RuntimeError(
            f"content_type must be one of {', '.join(CONTENT_TYPES)}; got {content_type!r}"
        )
    if delivery not in DELIVERIES:
        raise RuntimeError(
            f"delivery must be one of {', '.join(DELIVERIES)}; got {delivery!r}"
        )
    network = (network_or_service or "").strip()
    if not network:
        raise RuntimeError("network_or_service is required at capture, for example ESPN, NBC, Hulu, or Prime")
    title = (show or "").strip()
    if not title:
        raise RuntimeError("show is required at capture. Use a title, or 'unknown' if the title itself is unclear")
    note = (notes or "").strip()
    if not one_program:
        extra = "More than one program in this session."
        note = f"{note} {extra}".strip() if note else extra
    return {
        "content_type": content_type,
        "delivery": delivery,
        "network_or_service": network,
        "show": title,
        "notes": note,
        "one_program": bool(one_program),
        "identity_recorded_at_capture": True,
    }


def upsert_session_catalog(catalog_path, session_id, started_at, identity, duration_s=""):
    """Keep the permanent catalog in step with a capture. Does not invent older rows."""
    import csv

    existing = []
    if catalog_path.is_file():
        with catalog_path.open(newline="", encoding="utf-8") as handle:
            existing = list(csv.DictReader(handle))
    row = {
        "session_id": session_id,
        "date": started_at[:10],
        "content_type": identity["content_type"],
        "delivery": identity["delivery"],
        "network_or_service": identity["network_or_service"],
        "show": identity["show"],
        "notes": identity["notes"],
        "started_local": started_at,
        "duration_s": duration_s,
        "role": "dev",
    }
    replaced = False
    for index, prior in enumerate(existing):
        if prior.get("session_id") == session_id:
            if prior.get("role") == "holdout":
                raise RuntimeError(f"refusing to catalog sealed holdout {session_id}")
            existing[index] = row
            replaced = True
            break
    if not replaced:
        existing.append(row)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with catalog_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CATALOG_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for item in existing:
            writer.writerow({key: item.get(key, "") for key in CATALOG_COLUMNS})


def parse_mark_text(text: str):
    lower = text.lower()
    if lower in ("a", "ad", "ad_start"):
        return "ad_start", None
    if lower in ("c", "content", "content_start"):
        return "content_start", None
    if lower.startswith("n "):
        return "note", text[2:].strip()
    if lower == "note":
        return "note", ""
    return None, None


def main():
    global stop

    p = argparse.ArgumentParser()

    p.add_argument(
        "--list",
        action="store_true",
    )

    p.add_argument(
        "--device",
        help="Record-only input index or unique part of its name",
    )

    p.add_argument(
        "--live",
        action="store_true",
        help="Stereo pass-through. Choose devices in the monitor, or pass both device flags.",
    )

    p.add_argument(
        "--input-device",
        help="Live input: exact CoreAudio name or index. No default fallback.",
    )

    p.add_argument(
        "--output-device",
        help="Live output: exact CoreAudio name or index. No default fallback.",
    )

    p.add_argument(
        "--samplerate",
        type=int,
        default=48000,
    )

    p.add_argument(
        "--channels",
        type=int,
        default=2,
    )

    p.add_argument(
        "--chunk-minutes",
        type=float,
        default=15,
    )

    p.add_argument(
        "--seconds",
        type=float,
        default=0,
    )

    p.add_argument(
        "--output",
        default="recordings",
    )

    p.add_argument(
        "--live-host",
        default="127.0.0.1",
    )

    p.add_argument(
        "--live-port",
        type=int,
        default=8787,
    )

    p.add_argument(
        "--no-live",
        action="store_true",
        help="Disable the localhost live monitor API",
    )

    p.add_argument(
        "--content-type",
        choices=CONTENT_TYPES,
        help="Required for a recording. sports, scripted, reality, news, movie, or other.",
    )
    p.add_argument(
        "--delivery",
        choices=DELIVERIES,
        help="Required for a recording. linear (cable/OTA) or streaming.",
    )
    p.add_argument(
        "--network",
        help="Required for a recording. ESPN, NBC, Prime, Hulu, Peacock, Tubi, ...",
    )
    p.add_argument(
        "--show",
        default="",
        help="Required for a recording. Program title, or unknown.",
    )
    p.add_argument(
        "--notes",
        default="",
        help="Optional capture note.",
    )
    p.add_argument(
        "--multi-program",
        action="store_true",
        help="This capture intentionally contains more than one program.",
    )

    args = p.parse_args()

    if args.list:
        list_devices()
        return

    if args.live:
        if args.no_live:
            raise RuntimeError("--live needs the monitor API.")
        if args.device:
            raise RuntimeError(
                "--live uses --input-device and --output-device, not --device."
            )
        from live_audio import serve_live

        serve_live(args)
        return

    identity = capture_identity(
        args.content_type,
        args.delivery,
        args.network,
        args.show,
        args.notes,
        one_program=not args.multi_program,
    )

    device = resolve_device(args.device)

    info = sd.query_devices(
        device,
        "input",
    )

    if info["max_input_channels"] < args.channels:
        raise RuntimeError(
            f"{info['name']} exposes only "
            f"{int(info['max_input_channels'])} input channel(s). "
            f"Try --channels 1."
        )

    sd.check_input_settings(
        device=device,
        channels=args.channels,
        dtype="int16",
        samplerate=args.samplerate,
    )

    start_dt = datetime.now().astimezone()
    start_mono = time.monotonic()

    session_name = (
        "hush_"
        + start_dt.strftime("%Y%m%d_%H%M%S")
    )

    folder = (
        Path(args.output)
        / start_dt.strftime("%Y-%m-%d")
        / session_name
    )

    folder.mkdir(
        parents=True
    )

    markers_file = (
        folder / "markers.jsonl"
    )

    metadata_file = (
        folder / "session.json"
    )

    metadata = {
        "session": session_name,
        "started_at": start_dt.isoformat(),
        "timezone_note": "All wall times are local ISO-8601 with offset. "
        "Map handwritten clock times with: started_at + elapsed_seconds.",
        "device_index": device,
        "device_name": info["name"],
        "sample_rate_hz": args.samplerate,
        "channels": args.channels,
        "format": "16-bit PCM WAV",
        "chunk_minutes": args.chunk_minutes,
        "chunks": [],
        "warnings": warnings,
        **identity,
    }

    save_json(
        metadata_file,
        metadata,
    )
    catalog_path = Path(__file__).resolve().parent / "experiments" / "SESSION_CATALOG.csv"
    upsert_session_catalog(catalog_path, session_name, start_dt.isoformat(), identity)
    print(
        f"Identity: {identity['content_type']} / {identity['delivery']} / "
        f"{identity['network_or_service']} / {identity['show']}"
        + ("" if identity["one_program"] else " / multi-program"),
        flush=True,
    )

    # Create an empty human log they can fill while watching TV.
    human_log = folder / "ad_times.txt"
    if not human_log.exists():
        human_log.write_text(
            (
                f"# Hush ad time log for {session_name}\n"
                f"# Session started: {start_dt.isoformat()}\n"
                "# Write wall-clock times from your phone/TV clock.\n"
                "# Format examples:\n"
                "#   14:12:05 ad start\n"
                "#   14:14:40 content back\n"
                "#   14:31:10 ad start  (local spots)\n"
                "#\n"
                "# Lines below:\n"
            ),
            encoding="utf-8",
        )

    live = LiveState()
    live_server = None

    def wall_now():
        return datetime.now().astimezone()

    def chunk_record(file_name: str, seconds: float, chunk_start_elapsed: float):
        chunk_start_wall = (
            start_dt.timestamp() + chunk_start_elapsed
        )
        chunk_end_wall = chunk_start_wall + seconds
        return {
            "file": file_name,
            "seconds": round(seconds, 3),
            "start_elapsed_seconds": round(chunk_start_elapsed, 3),
            "end_elapsed_seconds": round(
                chunk_start_elapsed + seconds,
                3,
            ),
            "started_at": datetime.fromtimestamp(
                chunk_start_wall
            ).astimezone().isoformat(),
            "ended_at": datetime.fromtimestamp(
                chunk_end_wall
            ).astimezone().isoformat(),
        }

    def write_marker(kind: str, note: str | None):
        elapsed = round(time.monotonic() - start_mono, 3)
        marker = {
            "type": kind,
            "elapsed_seconds": elapsed,
            "wall_time": wall_now().isoformat(),
            "note": note,
        }

        with markers_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(marker) + "\n")

        live.append_marker(marker)
        print(
            f"\nMARKED {kind} at {elapsed}s "
            f"({marker['wall_time']})"
        )
        return marker

    def on_mark(kind: str, note: str | None):
        normalized = kind
        if kind in ("a", "ad"):
            normalized = "ad_start"
        elif kind in ("c", "content"):
            normalized = "content_start"
        elif kind == "n":
            normalized = "note"

        if normalized not in ("ad_start", "content_start", "note"):
            return None

        if normalized == "note" and not (note or "").strip():
            return None

        return write_marker(normalized, note)

    if not args.no_live:
        live_server = start_live_server(
            live,
            on_mark,
            host=args.live_host,
            port=args.live_port,
        )
        live.update(
            recording=True,
            pipeline="record",
            device_index=device,
            device_name=info["name"],
            sample_rate_hz=args.samplerate,
            channels=args.channels,
            chunk=1,
            folder=str(folder),
            session=session_name,
            monitor_url=f"http://{args.live_host}:{args.live_port}",
        )

    signal.signal(
        signal.SIGINT,
        on_signal,
    )

    signal.signal(
        signal.SIGTERM,
        on_signal,
    )

    chunk_no = 1

    wav, wav_path = new_wav(
        folder,
        chunk_no,
        args.channels,
        args.samplerate,
    )

    frames_in_chunk = 0
    total_frames = 0

    frames_per_chunk = int(
        args.chunk_minutes
        * 60
        * args.samplerate
    )

    bytes_per_frame = (
        args.channels * 2
    )

    last_meter = 0

    print("\nHUSH RECORDER")

    print(
        f"Input:   [{device}] "
        f"{info['name']}"
    )

    print(
        f"Format:  "
        f"{args.samplerate} Hz, "
        f"{args.channels} ch, "
        f"16-bit PCM"
    )

    print(
        f"Folder:  {folder}"
    )

    if live_server:
        print(
            f"Live:    http://{args.live_host}:{args.live_port} "
            f"(open apps/monitor on :3000)"
        )

    print(
        "Type a + Enter = AD START"
    )

    print(
        "Type c + Enter = CONTENT START"
    )

    print(
        "Type n your note + Enter = NOTE"
    )

    print(
        "Press Ctrl+C to stop.\n"
    )

    try:

        with sd.RawInputStream(
            device=device,
            samplerate=args.samplerate,
            channels=args.channels,
            dtype="int16",
            latency="high",
            callback=callback,
        ):

            while not stop:

                elapsed = (
                    time.monotonic()
                    - start_mono
                )

                if (
                    args.seconds
                    and elapsed >= args.seconds
                ):
                    break

                try:

                    data = audio_q.get(
                        timeout=0.1
                    )

                except queue.Empty:

                    data = None

                if data:

                    wav.writeframesraw(
                        data
                    )

                    frames = (
                        len(data)
                        // bytes_per_frame
                    )

                    frames_in_chunk += frames
                    total_frames += frames

                    if (
                        time.monotonic()
                        - last_meter
                        > 0.25
                    ):

                        db = peak_dbfs(
                            data
                        )

                        level = max(
                            0,
                            min(
                                30,
                                int(
                                    (db + 60)
                                    / 2
                                ),
                            ),
                        )

                        bar = (
                            "#"
                            * level
                            + "-"
                            * (30 - level)
                        )

                        print(
                            f"\r"
                            f"{elapsed:7.1f}s  "
                            f"{db:6.1f} dBFS "
                            f"[{bar}] "
                            f"chunk "
                            f"{chunk_no:04d}",
                            end="",
                            flush=True,
                        )

                        live.update(
                            recording=True,
                            elapsed_seconds=round(elapsed, 3),
                            dbfs=round(db, 1),
                            chunk=chunk_no,
                            warnings_count=len(warnings),
                        )

                        last_meter = (
                            time.monotonic()
                        )

                    if (
                        frames_in_chunk
                        >= frames_per_chunk
                    ):

                        wav.close()

                        seconds = (
                            frames_in_chunk
                            / args.samplerate
                        )

                        chunk_start_elapsed = (
                            total_frames - frames_in_chunk
                        ) / args.samplerate

                        metadata[
                            "chunks"
                        ].append(
                            chunk_record(
                                wav_path.name,
                                seconds,
                                chunk_start_elapsed,
                            )
                        )

                        save_json(
                            metadata_file,
                            metadata,
                        )

                        chunk_no += 1

                        wav, wav_path = (
                            new_wav(
                                folder,
                                chunk_no,
                                args.channels,
                                args.samplerate,
                            )
                        )

                        frames_in_chunk = 0
                        live.update(chunk=chunk_no)

                readable, _, _ = (
                    select.select(
                        [sys.stdin],
                        [],
                        [],
                        0,
                    )
                )

                if readable:

                    text = (
                        sys.stdin
                        .readline()
                        .strip()
                    )

                    if text:
                        kind, note = parse_mark_text(text)

                        if kind:
                            write_marker(kind, note)
                        else:
                            print(
                                '\nUse "a", '
                                '"c", or '
                                '"n your note".'
                            )

    finally:

        live.update(recording=False)

        if live_server is not None:
            live_server.shutdown()

        wav.close()

        if frames_in_chunk:

            chunk_start_elapsed = (
                total_frames - frames_in_chunk
            ) / args.samplerate

            metadata[
                "chunks"
            ].append(
                chunk_record(
                    wav_path.name,
                    frames_in_chunk / args.samplerate,
                    chunk_start_elapsed,
                )
            )

        end_dt = (
            datetime.now()
            .astimezone()
        )

        metadata[
            "ended_at"
        ] = (
            end_dt.isoformat()
        )

        metadata[
            "audio_seconds"
        ] = round(
            total_frames
            / args.samplerate,
            3,
        )

        metadata[
            "warnings"
        ] = warnings

        metadata[
            "status"
        ] = "complete"

        save_json(
            metadata_file,
            metadata,
        )
        upsert_session_catalog(
            catalog_path,
            session_name,
            start_dt.isoformat(),
            identity,
            duration_s=f"{metadata['audio_seconds']:.1f}",
        )

        print("\n\nDone.")

        print(
            f"Saved: {folder}"
        )

        print(
            f"Audio: "
            f"{metadata['audio_seconds']} "
            f"seconds"
        )

        if warnings:

            print(
                f"Warnings: "
                f"{len(warnings)} "
                f"— inspect session.json"
            )


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print(
            f"\nERROR: {e}",
            file=sys.stderr,
        )

        sys.exit(1)
