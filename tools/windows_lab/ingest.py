"""Ingest one local authorized WAV/FLAC into the Node 01 catalog."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import soundfile as sf

from . import NODE_ID, __version__
from .config import ALLOWED_RIGHTS, BLOCKED_RIGHTS, ensure_data_layout


SOURCE_TYPES = frozenset(
    {"optical", "authorized_stream_reference", "enhanced_paired", "test_public_fixture"}
)


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify_audio(path: Path) -> dict:
    info = sf.info(str(path))
    if info.samplerate != 48000:
        raise ValueError(f"expected 48000 Hz, got {info.samplerate}")
    if info.channels not in (1, 2):
        raise ValueError(f"expected 1–2 channels, got {info.channels}")
    subtype = (info.subtype or "").upper()
    # PCM_16 preferred; float ok for fixtures but note it
    return {
        "sample_rate_hz": int(info.samplerate),
        "channels": int(info.channels),
        "frames": int(info.frames),
        "duration_sec": round(info.frames / info.samplerate, 6),
        "subtype": info.subtype,
        "format": info.format,
    }


def ingest(
    path: Path,
    *,
    source_label: str,
    source_type: str,
    rights_status: str,
    capture_utc_start: str | None = None,
    source_timestamp: str | None = None,
    discontinuities: list | None = None,
    git_commit: str | None = None,
    copy_into_authorized: bool = True,
) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    rights = rights_status.strip().lower()
    if rights in BLOCKED_RIGHTS or rights not in ALLOWED_RIGHTS:
        raise PermissionError(
            f"rights_status={rights_status!r} is not allowed for ingest "
            f"(allowed={sorted(ALLOWED_RIGHTS)})"
        )
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {sorted(SOURCE_TYPES)}")

    root = ensure_data_layout()
    audio_meta = verify_audio(path)
    digest = sha256_file(path)
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]

    dest = path
    if copy_into_authorized:
        dest_dir = root / "authorized_sources" / session_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        if dest.resolve() != path.resolve():
            shutil.copy2(path, dest)
            digest = sha256_file(dest)

    receipt = {
        "node_id": NODE_ID,
        "session_id": session_id,
        "source_type": source_type,
        "source_label": source_label,
        "rights_status": rights,
        "source_timestamp": source_timestamp,
        "capture_utc_start": capture_utc_start,
        "sample_count": audio_meta["frames"],
        "audio_format": audio_meta,
        "file_sha256": digest,
        "pipeline_git_commit": git_commit,
        "analysis_version": __version__,
        "discontinuities": discontinuities or [],
        "file_path": str(dest),
        "receipt_utc": datetime.now(timezone.utc).isoformat(),
        # Explicitly never store credentials/stream tokens
        "credentials": None,
        "stream_urls": None,
    }

    receipt_path = root / "receipts" / f"{session_id}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Ingest one authorized local WAV/FLAC")
    p.add_argument("path", type=Path)
    p.add_argument("--source-label", required=True)
    p.add_argument("--source-type", required=True, choices=sorted(SOURCE_TYPES))
    p.add_argument("--rights-status", required=True)
    p.add_argument("--capture-utc-start")
    p.add_argument("--source-timestamp")
    p.add_argument("--git-commit")
    p.add_argument("--no-copy", action="store_true")
    args = p.parse_args(argv)

    try:
        receipt = ingest(
            args.path,
            source_label=args.source_label,
            source_type=args.source_type,
            rights_status=args.rights_status,
            capture_utc_start=args.capture_utc_start,
            source_timestamp=args.source_timestamp,
            git_commit=args.git_commit,
            copy_into_authorized=not args.no_copy,
        )
    except PermissionError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1

    print(json.dumps({"ok": True, "receipt": receipt}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
