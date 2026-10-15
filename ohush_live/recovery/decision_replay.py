"""Decision replay: reapply recorded detector families through a Machine.

Mode A of LIVE_RECOVERY_001. Does not rerun Torch workers.
Replaying the same track + Machine module yields identical transitions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ohush_live.recovery.load_machine import load_machine  # noqa: E402


def segment_runs(track_rows: list[dict]) -> list[list[dict]]:
    """Split on timestamp resets so engine restarts never merge."""
    runs: list[list[dict]] = []
    cur: list[dict] = []
    prev: float | None = None
    for row in track_rows:
        t = float(row.get("t") or 0.0)
        if prev is not None and t + 1e-6 < prev:
            if cur:
                runs.append(cur)
            cur = []
        cur.append(row)
        prev = t
    if cur:
        runs.append(cur)
    return runs


def load_track(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def families_from_row(row: dict) -> dict:
    """Use recorded family dicts only — never invent missing evidence."""
    out = {}
    for name in ("audio", "speaker", "semantic"):
        value = row.get(name)
        out[name] = value if isinstance(value, dict) else None
    return out


def replay_run(Machine, rows: list[dict], *, run_id: str) -> list[dict]:
    machine = Machine()
    events: list[dict] = []
    prev_t: float | None = None
    for row in rows:
        t = float(row.get("t") or 0.0)
        dt = 1.0 if prev_t is None else max(0.0, t - prev_t)
        # Cap dt so a gap does not dump a huge streak in one step.
        if dt > 2.0:
            dt = 1.0
        families = families_from_row(row)
        event = machine.step(t, dt, families)
        if event:
            events.append(
                {
                    "run_id": run_id,
                    "t": t,
                    "state_after": event["state_after"],
                    "reason": event["reason"],
                    "manual_override": bool(event.get("manual_override")),
                    "audio_departure": event.get("audio_departure"),
                    "speaker_departure": event.get("speaker_departure"),
                    "hearing_recorded": row.get("hearing"),
                    "machine_recorded": row.get("machine"),
                    "speaker_booth_locked": (families.get("speaker") or {}).get("booth_locked"),
                    "speaker_booth_present": (families.get("speaker") or {}).get("booth_present"),
                    "speaker_speech": (families.get("speaker") or {}).get("speech"),
                }
            )
        prev_t = t
    return events


def replay_track(Machine, track_path: Path) -> list[dict]:
    rows = load_track(track_path)
    runs = segment_runs(rows)
    all_events: list[dict] = []
    for index, run in enumerate(runs):
        run_id = f"run{index:02d}"
        all_events.extend(replay_run(Machine, run, run_id=run_id))
    return all_events


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OHUSH live decision replay")
    parser.add_argument("--track", type=Path, required=True)
    parser.add_argument(
        "--code-root",
        type=Path,
        required=True,
        help="Directory containing ohush_live/state.py (+ policy.py)",
    )
    parser.add_argument("--alias", required=True, help="Unique name for this code snapshot")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    Machine = load_machine(args.code_root, alias=args.alias)
    events = replay_track(Machine, args.track)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    meta = {
        "alias": args.alias,
        "code_root": str(args.code_root.resolve()),
        "track": str(args.track.resolve()),
        "track_sha256": file_sha256(args.track),
        "state_sha256": file_sha256(args.code_root / "ohush_live" / "state.py"),
        "n_events": len(events),
        "n_mute": sum(1 for e in events if e["state_after"] == "MUTED"),
        "n_play": sum(1 for e in events if e["state_after"] == "PLAY"),
    }
    meta_path = args.out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
