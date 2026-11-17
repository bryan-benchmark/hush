"""Join vision + ASR + acoustic receipts into one greppable audit per session.

Reads:
  audit/hops_vision.jsonl (1s)
  audit/hops_acoustic.jsonl (0.25s)
  farm_accepted gold

Writes:
  audit/hops.jsonl + AUDIT.md  (1s combined — easy to read)
  AUDIT_INDEX.md under farm_labels/audit/

Usage
-----
  python -m tools.windows_lab.farm_atomic_audit --session 20261110T1339Z_pluto_cbs_sports_hq
  python -m tools.windows_lab.farm_atomic_audit --from-export
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir, streamers_capture_root
from .export_farm_acoustic_gold import OUT as FARM_ACCEPTED
from .farm_audit_receipts import audit_dir, hop_receipt, write_hops


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _nearest_acoustic(ac_hops: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    if not ac_hops:
        return None
    best = None
    best_d = 1e9
    for h in ac_hops:
        d = abs(float(h["t"]) - t)
        if d < best_d:
            best_d = d
            best = h
    if best is None or best_d > 0.3:
        return None
    return (best.get("channels") or {}).get("acoustic")


def combine_session(session: str) -> dict[str, Any]:
    root = audit_dir(session)
    sd = streamers_capture_root() / session
    vision = _load_jsonl(root / "hops_vision.jsonl")
    acoustic = _load_jsonl(root / "hops_acoustic.jsonl")
    if not vision and not acoustic:
        return {"ok": False, "session": session, "error": "no vision or acoustic hops yet"}

    # Prefer 1s vision timeline as spine; else decimate acoustic to 1s
    if vision:
        spine_t = [float(h["t"]) for h in vision]
        vision_by_t = {round(float(h["t"]), 1): h for h in vision}
    else:
        spine_t = sorted({round(float(h["t"]) // 1 * 1.0, 1) for h in acoustic})
        vision_by_t = {}

    combined = []
    for t in spine_t:
        vh = vision_by_t.get(round(t, 1))
        vision_ch = (vh.get("channels") or {}).get("vision") if vh else None
        asr_ch = (vh.get("channels") or {}).get("asr") if vh else None
        gold_ch = (vh.get("channels") or {}).get("gold") if vh else None
        ac_ch = _nearest_acoustic(acoustic, t)
        # gold from acoustic hop if missing
        if gold_ch is None and acoustic:
            ah = min(acoustic, key=lambda h: abs(float(h["t"]) - t))
            if abs(float(ah["t"]) - t) <= 0.3:
                gold_ch = (ah.get("channels") or {}).get("gold")
        combined.append(
            hop_receipt(
                session=session,
                t=t,
                vision=vision_ch,
                asr=asr_ch,
                acoustic=ac_ch,
                gold=gold_ch,
                extra=(vh or {}).get("extra"),
            )
        )

    meta = write_hops(session, combined, session_dir=sd if sd.is_dir() else None, kind="combined")
    return {"ok": True, "session": session, **meta}


def write_index(results: list[dict[str, Any]]) -> Path:
    root = farm_label_dir() / "audit"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "AUDIT_INDEX.md"
    lines = [
        "# Farm atomic audit index",
        "",
        "Each session folder has `hops.jsonl` (combined), `hops_vision.jsonl`, `hops_acoustic.jsonl`, `AUDIT.md`.",
        "",
        "| Session | hops | disagreements | audit |",
        "|---|---:|---:|---|",
    ]
    for r in results:
        if not r.get("ok"):
            lines.append(f"| `{r.get('session')}` | — | — | {r.get('error')} |")
            continue
        lines.append(
            f"| `{r['session']}` | {r.get('n_hops')} | {r.get('n_disagree')} | `{r.get('md_path')}` |"
        )
    lines.extend(
        [
            "",
            "## How to dive a bug",
            "",
            "1. Open session `AUDIT.md` — scan **DISAGREE** rows.",
            "2. Click/copy the still path from `hops_vision.jsonl` / disagreement detail.",
            "3. Check ASR text on that hop vs acoustic `p`/`action`.",
            "4. Grep: `rg DISAGREE indexes/farm_labels/audit/<session>/hops.jsonl`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Combine vision/ASR/acoustic into one atomic audit")
    p.add_argument("--session", type=str, default=None)
    p.add_argument("--from-export", action="store_true")
    p.add_argument("--limit-sessions", type=int, default=None)
    args = p.parse_args(argv)

    if args.session:
        sessions = [args.session]
    elif args.from_export:
        sessions = []
        if FARM_ACCEPTED.is_file():
            for line in FARM_ACCEPTED.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                s = json.loads(line).get("session")
                if s and s not in sessions:
                    sessions.append(s)
    else:
        # any session that already has audit hops
        root = farm_label_dir() / "audit"
        sessions = sorted(d.name for d in root.iterdir() if d.is_dir()) if root.is_dir() else []

    if args.limit_sessions is not None:
        sessions = sessions[: args.limit_sessions]

    results = [combine_session(s) for s in sessions]
    index = write_index(results)
    print(json.dumps({"ok": True, "index": str(index), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
