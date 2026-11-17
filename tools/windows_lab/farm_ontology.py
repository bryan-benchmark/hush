"""Farm clip taxonomy → acoustic product ontology (broadcast / non_broadcast).

Vision/human labels may use rich farm buckets. The audio trainer and live
scorecard only eat:

  non_broadcast → want mute
  broadcast     → want play

Policy (ASAP, explicit):
  paid_ad, show_promo          → non_broadcast
  program                      → broadcast
  program_mention / L-wrap/PiP → non_broadcast  (ears hear the ad bed)
  uncertain / other            → skip (no gold)
"""

from __future__ import annotations

from typing import Any

# Acoustic buckets (labels_accepted shape)
NON_BROADCAST = "non_broadcast"
BROADCAST = "broadcast"

# Farm buckets that become mute gold for audio
MUTE_FARM = frozenset(
    {
        "paid_ad",
        "show_promo",
        "program_mention",  # PiP / L-wrap: audio is the spot
    }
)
PLAY_FARM = frozenset({"program"})
SKIP_FARM = frozenset({"uncertain"})


def to_acoustic_bucket(farm_bucket: str, *, kind: str = "") -> str | None:
    """Return non_broadcast | broadcast | None (skip)."""
    b = str(farm_bucket or "").strip().lower()
    k = str(kind or "").strip().lower()
    if b in SKIP_FARM or not b:
        return None
    if b in MUTE_FARM:
        return NON_BROADCAST
    if b in PLAY_FARM:
        return BROADCAST
    # Kind hints when bucket is odd/legacy
    if k in {"pip_ad_over_sports", "l_wrap", "lwrap", "sidecar_ad"}:
        return NON_BROADCAST
    if k.startswith("program_"):
        return BROADCAST
    if k in {"dry_vo", "paid_ad", "show_promo"}:
        return NON_BROADCAST
    return None


def desired_action(acoustic_bucket: str) -> str:
    if acoustic_bucket == NON_BROADCAST:
        return "mute"
    if acoustic_bucket == BROADCAST:
        return "play"
    raise ValueError(f"unknown acoustic bucket {acoustic_bucket!r}")


def interval_from_farm_row(row: dict[str, Any], *, source: str, model_id: str = "") -> dict[str, Any] | None:
    """Build one acoustic-style interval dict, or None if skipped."""
    bucket = to_acoustic_bucket(str(row.get("bucket") or ""), kind=str(row.get("kind") or ""))
    if bucket is None:
        return None
    session = str(row.get("session") or "")
    if not session:
        return None
    start = float(row.get("t0") if row.get("t0") is not None else row.get("start_s") or 0.0)
    end = float(row.get("t1") if row.get("t1") is not None else row.get("end_s") or 0.0)
    if end <= start:
        return None
    conf = str(row.get("confidence") or "high")
    return {
        "session": session,
        "start_s": round(start, 3),
        "end_s": round(end, 3),
        "dur_s": round(end - start, 3),
        "bucket": bucket,
        "kind": str(row.get("kind") or row.get("bucket") or "farm"),
        "desired_action": desired_action(bucket),
        "source": source,
        "confidence": conf,
        "note": str(row.get("note") or row.get("human_note") or "")[:240],
        "status": "accepted",
        "farm_bucket": str(row.get("bucket") or ""),
        "clip": str(row.get("clip") or ""),
        "session_dir": str(row.get("session_dir") or ""),
        "model_id": model_id or "",
    }
