"""WASAPI application (process) loopback — capture one HD-Player PID, no cable.

Uses a small native helper (VS-built) that mirrors Microsoft's ApplicationLoopback
sample. N BlueStacks instances can share one Speakers device without mixing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RATE_DEFAULT = 48000
CHANNELS_DEFAULT = 2

HELPER_DIR = Path(r"C:\OHushData\tools\ProcessLoopbackCapture")
HELPER_EXE = HELPER_DIR / "ProcessLoopbackNative.exe"
HELPER_SRC = Path(__file__).with_name("ProcessLoopbackCapture.cpp")


def hd_players() -> list[dict[str, Any]]:
    ps = (
        "Get-Process HD-Player -ErrorAction SilentlyContinue | "
        "Select-Object Id, MainWindowTitle | ConvertTo-Json -Compress"
    )
    raw = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", ps],
        text=True,
        errors="ignore",
    ).strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    return [{"pid": int(r["Id"]), "title": str(r.get("MainWindowTitle") or "")} for r in data]


def resolve_hd_player_pid(*, window_title: str | None = None, instance_id: str | None = None) -> dict[str, Any]:
    title = window_title
    expected: list[str] = []
    if instance_id:
        from .instances import get_instance
        from .multi_instance import default_window_title

        try:
            inst = get_instance(instance_id)
            reg_title = str(inst.get("window_title") or "")
            if reg_title:
                expected.append(reg_title)
        except Exception:  # noqa: BLE001
            pass
        expected.append(default_window_title(str(instance_id)))
    if title:
        expected.insert(0, title)
    titles: list[str] = []
    seen: set[str] = set()
    for t in expected:
        if t and t not in seen:
            seen.add(t)
            titles.append(t)

    players = hd_players()
    if not players:
        raise RuntimeError("no HD-Player processes running")
    for cand in titles:
        hit = next((p for p in players if p["title"] == cand), None)
        if hit is not None:
            return {**hit, "matched": "exact_title", "matched_title": cand}
    if len(players) == 1 and not titles:
        return {**players[0], "matched": "sole"}
    raise RuntimeError(
        f"no HD-Player for titles={titles!r} instance_id={instance_id!r}; live={players}"
    )


def ensure_helper(*, rebuild: bool = False) -> Path:
    """Build ProcessLoopbackNative.exe with VS 2022 cl if missing/stale."""
    if HELPER_EXE.is_file() and not rebuild:
        if not HELPER_SRC.is_file() or HELPER_EXE.stat().st_mtime >= HELPER_SRC.stat().st_mtime:
            return HELPER_EXE
    HELPER_DIR.mkdir(parents=True, exist_ok=True)
    vs = subprocess.check_output(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "& \"${env:ProgramFiles(x86)}\\Microsoft Visual Studio\\Installer\\vswhere.exe\" "
            "-latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 "
            "-property installationPath",
        ],
        text=True,
        errors="ignore",
    ).strip()
    if not vs:
        raise FileNotFoundError("VS 2022 with C++ tools not found (need cl.exe)")
    vcvars = Path(vs) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not vcvars.is_file():
        raise FileNotFoundError(f"vcvars64.bat missing: {vcvars}")
    bat = HELPER_DIR / "build.bat"
    bat.write_text(
        "\r\n".join(
            [
                "@echo off",
                f'call "{vcvars}"',
                f'cd /d "{HELPER_DIR}"',
                f'cl /nologo /EHsc /O2 /W3 /DUNICODE /D_UNICODE "{HELPER_SRC}" '
                f"/Fe:ProcessLoopbackNative.exe /link Ole32.lib Mmdevapi.lib",
                "exit /b %ERRORLEVEL%",
                "",
            ]
        ),
        encoding="ascii",
    )
    proc = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True)
    if proc.returncode != 0 or not HELPER_EXE.is_file():
        raise RuntimeError(
            f"helper build failed code={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return HELPER_EXE


HEARTBEAT_NAME = "_audio_heartbeat.json"


def _session_context(out_dir: Path) -> dict[str, Any]:
    """Best-effort job/session ids from session meta.json (never raises)."""
    meta_path = Path(out_dir) / "meta.json"
    if not meta_path.is_file():
        return {"session_id": Path(out_dir).name}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"session_id": Path(out_dir).name}
    return {
        "session_id": str(meta.get("session_id") or Path(out_dir).name),
        "job_id": meta.get("job_id"),
        "instance_id": meta.get("instance_id") or meta.get("resource_id"),
    }


def _emit_chunk_event(
    event: str,
    *,
    out_dir: Path,
    pid: int,
    chunk_index: int,
    detail: str = "",
    audio_s: float | None = None,
    ok: bool | None = None,
) -> None:
    try:
        from .farm_ops import emit

        ctx = _session_context(out_dir)
        emit(
            event,
            detail=detail or f"chunk_{chunk_index:04d}",
            job_id=str(ctx["job_id"]) if ctx.get("job_id") else None,
            session_id=str(ctx.get("session_id") or "") or None,
            instance_id=str(ctx["instance_id"]) if ctx.get("instance_id") else None,
            pid=pid,
            audio_s=audio_s,
            ok=ok,
            extra={"chunk_index": chunk_index},
        )
    except Exception:  # noqa: BLE001
        pass


def write_audio_heartbeat(out_dir: Path, **fields: Any) -> Path:
    """Live audio heartbeat so audit can see capture progress before a WAV lands."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / HEARTBEAT_NAME
    row = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "unix": time.time(),
        **fields,
    }
    path.write_text(json.dumps(row, indent=2), encoding="utf-8")
    return path


def record_process_loopback(
    *,
    pid: int,
    seconds: float,
    out_path: Path,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Capture PCM from one process tree into a WAV via the native helper."""
    exe = ensure_helper()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.is_file():
        try:
            out_path.unlink()
        except OSError:
            pass
    proc = subprocess.Popen(
        [str(exe), str(int(pid)), f"{float(seconds):.3f}", str(out_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout = ""
    stderr = ""
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                raise RuntimeError("process loopback stopped by stop_event")
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    if proc.returncode not in (0, None):
        # Allow partial file if helper wrote something before kill; else hard fail.
        if not out_path.is_file() or out_path.stat().st_size < 1024:
            raise RuntimeError(
                f"process loopback failed code={proc.returncode} stderr={(stderr or '').strip()!r} "
                f"stdout={(stdout or '').strip()!r}"
            )
    line = (stdout or "").strip().splitlines()[-1] if (stdout or "").strip() else "{}"
    try:
        row = json.loads(line) if line.startswith("{") else {"ok": True, "raw": line}
    except json.JSONDecodeError:
        row = {"ok": out_path.is_file(), "raw": line}
    row.setdefault("ok", True)
    row["pid"] = int(pid)
    row["wav"] = str(out_path)
    row["captured_utc"] = datetime.now(timezone.utc).isoformat()
    row["returncode"] = proc.returncode
    return row


def record_process_loopback_chunks(
    *,
    pid: int,
    seconds: float,
    out_dir: Path,
    chunk_minutes: float = 15.0,
    rate: int = RATE_DEFAULT,
    channels: int = CHANNELS_DEFAULT,
    stop_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Write ``audio_XXXX.wav`` every ``chunk_minutes`` as the take runs (real heartbeat).

    Previously this ran one full-session helper then sliced — audit saw 0 WAVs for hours.
    Now each chunk is its own helper run; files land on disk when the chunk finishes.
    """
    del rate, channels  # helper chooses format; kept for call-site compatibility
    stop_event = stop_event or threading.Event()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chunk_seconds = max(30.0, float(chunk_minutes) * 60.0)
    chunks: list[dict[str, Any]] = []
    chunk_idx = 0
    elapsed = 0.0
    t0 = time.perf_counter()

    write_audio_heartbeat(
        out_dir,
        state="starting",
        pid=int(pid),
        chunk_minutes=float(chunk_minutes),
        target_seconds=float(seconds),
    )

    while elapsed < float(seconds) - 0.5:
        if stop_event.is_set():
            break
        remaining = float(seconds) - (time.perf_counter() - t0)
        if remaining <= 0.5:
            break
        this_len = min(chunk_seconds, remaining)
        name = f"audio_{chunk_idx:04d}.wav"
        path = out_dir / name
        write_audio_heartbeat(
            out_dir,
            state="capturing",
            pid=int(pid),
            chunk_index=chunk_idx,
            chunk_seconds=this_len,
            audio=name,
            elapsed_s=round(time.perf_counter() - t0, 1),
        )
        # Pulse during the helper run so audit is not blind for a full 15m chunk.
        pulse_stop = threading.Event()

        def _mid_chunk_pulse() -> None:
            while not pulse_stop.wait(30.0):
                write_audio_heartbeat(
                    out_dir,
                    state="capturing",
                    pid=int(pid),
                    chunk_index=chunk_idx,
                    chunk_seconds=this_len,
                    audio=name,
                    elapsed_s=round(time.perf_counter() - t0, 1),
                    pulse="mid_chunk",
                )

        pulse_thread = threading.Thread(target=_mid_chunk_pulse, name="audio-hb-pulse", daemon=True)
        pulse_thread.start()
        info: dict[str, Any] = {}
        try:
            try:
                info = record_process_loopback(
                    pid=int(pid),
                    seconds=this_len,
                    out_path=path,
                    stop_event=stop_event,
                )
            except RuntimeError as exc:
                write_audio_heartbeat(
                    out_dir,
                    state="error",
                    pid=int(pid),
                    chunk_index=chunk_idx,
                    error=str(exc)[:500],
                )
                # Keep a usable partial chunk if the helper flushed something.
                if not (path.is_file() and path.stat().st_size >= 1024):
                    _emit_chunk_event(
                        "chunk_fail",
                        out_dir=out_dir,
                        pid=int(pid),
                        chunk_index=chunk_idx,
                        detail=str(exc)[:300],
                        ok=False,
                    )
                    if stop_event.is_set():
                        break
                    raise
        finally:
            pulse_stop.set()

        duration_sec = this_len
        frames = None
        if path.is_file():
            try:
                with wave.open(str(path), "rb") as w:
                    frames = w.getnframes()
                    fr = w.getframerate() or 1
                    duration_sec = frames / float(fr)
            except Exception:  # noqa: BLE001
                frames = None

        row = {
            "index": chunk_idx,
            "audio": name if path.is_file() else None,
            "frames": frames,
            "duration_sec": round(float(duration_sec), 3),
            "capture": "process_loopback",
            "pid": int(pid),
            "peak_session": info.get("peak"),
        }
        chunks.append(row)
        write_audio_heartbeat(
            out_dir,
            state="chunk_ok",
            pid=int(pid),
            chunk_index=chunk_idx,
            audio=name,
            duration_sec=row["duration_sec"],
            wav_count=len(chunks),
            elapsed_s=round(time.perf_counter() - t0, 1),
        )
        _emit_chunk_event(
            "chunk_ok",
            out_dir=out_dir,
            pid=int(pid),
            chunk_index=chunk_idx,
            detail=name,
            audio_s=float(row["duration_sec"]),
            ok=True,
        )
        chunk_idx += 1
        elapsed = time.perf_counter() - t0
        if stop_event.is_set():
            break

    write_audio_heartbeat(
        out_dir,
        state="done" if not stop_event.is_set() else "stopped",
        pid=int(pid),
        wav_count=len(chunks),
        elapsed_s=round(time.perf_counter() - t0, 1),
    )
    return chunks


def probe_isolation(*, seconds: float = 6.0, out_dir: Path | None = None) -> dict[str, Any]:
    players = hd_players()
    if not players:
        return {"ok": False, "error": "no HD-Player", "players": []}
    ensure_helper()
    out_dir = Path(out_dir or r"C:\OHushData\work\process_loopback_probe")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    box: dict[int, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []

    def _one(p: dict[str, Any]) -> None:
        try:
            wav = out_dir / f"{stamp}_pid{p['pid']}.wav"
            row = record_process_loopback(pid=p["pid"], seconds=seconds, out_path=wav)
            row["title"] = p["title"]
            box[p["pid"]] = row
        except Exception as e:  # noqa: BLE001
            errors.append({"pid": p["pid"], "title": p["title"], "error": str(e)})

    threads = [threading.Thread(target=_one, args=(p,), daemon=True) for p in players]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=seconds + 45)
    results = [box[p["pid"]] for p in players if p["pid"] in box]
    return {
        "ok": bool(results) and not errors,
        "seconds": seconds,
        "players": players,
        "results": results,
        "errors": errors,
        "peaks_by_pid": {r["pid"]: r.get("peak") for r in results},
        "out_dir": str(out_dir),
        "guidance": (
            "Mute one BlueStacks instance: its PID peak should collapse; the other stays up. "
            "Both on the same Speakers device is fine — process loopback does not need cables."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List HD-Player PIDs / titles")
    sub.add_parser("ensure-helper", help="Build native helper if needed")
    s_rec = sub.add_parser("record", help="Record one PID to WAV")
    s_rec.add_argument("--pid", type=int)
    s_rec.add_argument("--title", type=str, default=None)
    s_rec.add_argument("--instance", type=str, default=None)
    s_rec.add_argument("--seconds", type=float, default=6.0)
    s_rec.add_argument("--out", type=str, default=None)
    s_probe = sub.add_parser("probe", help="Parallel capture all HD-Player PIDs")
    s_probe.add_argument("--seconds", type=float, default=6.0)
    s_probe.add_argument("--out-dir", type=str, default=None)
    args = p.parse_args(argv)
    if args.cmd == "list":
        print(json.dumps({"players": hd_players()}, indent=2))
        return 0
    if args.cmd == "ensure-helper":
        print(json.dumps({"ok": True, "exe": str(ensure_helper(rebuild=True))}, indent=2))
        return 0
    if args.cmd == "record":
        pid = args.pid
        if not pid:
            hit = resolve_hd_player_pid(window_title=args.title, instance_id=args.instance)
            pid = int(hit["pid"])
        out = (
            Path(args.out)
            if args.out
            else Path(r"C:\OHushData\work\process_loopback_probe") / f"pid{pid}.wav"
        )
        print(json.dumps(record_process_loopback(pid=pid, seconds=args.seconds, out_path=out), indent=2))
        return 0
    if args.cmd == "probe":
        print(
            json.dumps(
                probe_isolation(
                    seconds=args.seconds,
                    out_dir=Path(args.out_dir) if args.out_dir else None,
                ),
                indent=2,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
