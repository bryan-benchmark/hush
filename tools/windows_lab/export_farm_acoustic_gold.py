"""Export farm timelines into the audio-learn label store.

Writes:
  C:\\OHushData\\gpu_lab\\audio_learn\\broadcast_labels\\farm_accepted.jsonl

Shape matches labels_accepted.jsonl so ontology_train / scorecard code can
load it with a one-line path swap. Never touches sealed optical holdouts.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir
from .farm_ontology import BROADCAST, NON_BROADCAST
from .farm_timeline import build_timelines

AUDIO_LEARN = Path(r"C:\OHushData\gpu_lab\audio_learn")
OUT = AUDIO_LEARN / "broadcast_labels" / "farm_accepted.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_timelines() -> list[dict[str, Any]]:
    path = farm_label_dir() / "timelines.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def export(*, rebuild: bool = True, clean_only: bool = True) -> dict[str, Any]:
    if rebuild:
        build_timelines(clean_only=clean_only)
    rows = _load_timelines()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Acoustic-facing fields only (plus farm provenance sidelined in note/source)
    # HARD GUARD: vision_auto never enters farm_accepted — candidates stay separate.
    out_rows = []
    skipped_vision = 0
    for r in rows:
        src = str(r.get("source") or "human")
        if "vision" in src.lower() or str(r.get("model_id") or "").startswith("vision_timeline"):
            skipped_vision += 1
            continue
        out_rows.append(
            {
                "session": r["session"],
                "start_s": float(r["start_s"]),
                "end_s": float(r["end_s"]),
                "dur_s": float(r["dur_s"]),
                "bucket": r["bucket"],
                "kind": r.get("kind") or "farm",
                "desired_action": r.get("desired_action") or ("mute" if r["bucket"] == NON_BROADCAST else "play"),
                "source": f"farm:{src}",
                "confidence": r.get("confidence") or "high",
                "note": r.get("note") or "",
                "status": "accepted",
                "farm_session_dir": r.get("session_dir") or "",
                "farm_clip": r.get("clip") or "",
                "model_id": r.get("model_id") or "farm_lock_v1",
            }
        )
    OUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + ("\n" if out_rows else ""),
        encoding="utf-8",
    )
    nb = sum(r["dur_s"] for r in out_rows if r["bucket"] == NON_BROADCAST)
    bc = sum(r["dur_s"] for r in out_rows if r["bucket"] == BROADCAST)
    receipt = {
        "generated_utc": _now(),
        "path": str(OUT),
        "n": len(out_rows),
        "non_broadcast_s": round(nb, 3),
        "broadcast_s": round(bc, 3),
        "sessions": sorted({r["session"] for r in out_rows}),
        "skipped_vision_auto_rows": skipped_vision,
        "guard": "vision_auto never merged into farm_accepted; see farm_vision_candidates.jsonl",
        "next": [
            "Score live stack: python -m tools.windows_lab.farm_live_scorecard",
            "Later: extract farm embeddings + ontology_train including farm_accepted.jsonl",
            "Do not merge into sealed optical holdouts",
            "Do not promote farm_vision_candidates → farm_accepted without human/boundary review",
        ],
    }
    receipt_path = farm_label_dir() / "FARM_ACCEPTED_EXPORT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    (AUDIO_LEARN / "broadcast_labels" / "farm_accepted_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export farm timelines → farm_accepted.jsonl")
    p.add_argument("--no-rebuild", action="store_true", help="Use existing timelines.jsonl only")
    p.add_argument("--all-locked", action="store_true")
    args = p.parse_args(argv)
    receipt = export(rebuild=not args.no_rebuild, clean_only=not args.all_locked)
    print(json.dumps({"ok": True, **receipt}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
