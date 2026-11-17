"""Atomic audit receipts for farm vision / ASR / acoustic hops.

One JSONL line per decision time so bugs are greppable:

  session_dir/audit/hops.jsonl
  indexes/farm_labels/audit/<session>/hops.jsonl
  indexes/farm_labels/audit/<session>/AUDIT.md

Each hop can carry vision, ASR, and acoustic channels independently.
Missing channels are explicit nulls — never omitted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_dir(session: str, session_dir: Path | None = None) -> Path:
    """Canonical audit folder under farm_labels + optional session mirror."""
    path = farm_label_dir() / "audit" / session
    path.mkdir(parents=True, exist_ok=True)
    if session_dir is not None:
        local = Path(session_dir) / "audit"
        local.mkdir(parents=True, exist_ok=True)
    return path


def hop_receipt(
    *,
    session: str,
    t: float,
    vision: dict[str, Any] | None = None,
    asr: dict[str, Any] | None = None,
    acoustic: dict[str, Any] | None = None,
    gold: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one atomic hop. Null channels are explicit."""
    v = vision
    a = asr
    ac = acoustic
    vision_vote = None
    asr_vote = None
    if v and v.get("ok"):
        vision_vote = v.get("acoustic_bucket") or v.get("class")
    if a and a.get("ok"):
        asr_vote = a.get("acoustic_bucket") or a.get("lexicon")

    votes = {
        "vision": vision_vote,
        "asr": asr_vote,
        "acoustic_action": (ac or {}).get("action") if ac else None,
        "acoustic_p": (ac or {}).get("p") if ac else None,
        "gold_bucket": (gold or {}).get("bucket") if gold else None,
    }
    disagree = _disagreement(votes)
    why = _why(votes, disagree)
    row = {
        "schema": SCHEMA_VERSION,
        "receipt_id": f"{session}@t={t:.1f}",
        "session": session,
        "t": round(float(t), 3),
        "utc": _now(),
        "channels": {
            "vision": v,
            "asr": a,
            "acoustic": ac,
            "gold": gold,
        },
        "votes": votes,
        "disagreement": disagree,
        "why": why,
    }
    if extra:
        row["extra"] = extra
    return row


def _disagreement(votes: dict[str, Any]) -> bool:
    vis = votes.get("vision")
    asr = votes.get("asr")
    # Normalize class names
    def norm(x: Any) -> str | None:
        if x is None:
            return None
        s = str(x).lower()
        if s in {"ad", "non_broadcast", "mute", "paid_ad", "show_promo"}:
            return "mute"
        if s in {"program", "broadcast", "play"}:
            return "play"
        if s in {"mixed", "uncertain", "other"}:
            return "uncertain"
        return s

    v, a = norm(vis), norm(asr)
    if v and a and v != a and "uncertain" not in {v, a}:
        return True
    gold = norm(votes.get("gold_bucket"))
    action = votes.get("acoustic_action")
    if gold == "play" and action == "cover":
        return True
    if gold == "mute" and action == "play":
        return True
    if v == "play" and action == "cover":
        return True
    # Label bugs: vision/ASR clear mute while gold still says play (late boundary)
    if gold == "play" and v == "mute":
        return True
    if gold == "play" and a == "mute":
        return True
    if gold == "mute" and v == "play" and a == "play":
        return True
    return False


def _why(votes: dict[str, Any], disagree: bool) -> str:
    parts = []
    if votes.get("vision"):
        parts.append(f"vision={votes['vision']}")
    if votes.get("asr"):
        parts.append(f"asr={votes['asr']}")
    if votes.get("acoustic_action") is not None:
        p = votes.get("acoustic_p")
        parts.append(f"acoustic={votes['acoustic_action']}(p={p})")
    if votes.get("gold_bucket"):
        parts.append(f"gold={votes['gold_bucket']}")
    if disagree:
        parts.append("DISAGREE")
    return " ".join(parts) if parts else "empty"


def write_hops(
    session: str,
    hops: list[dict[str, Any]],
    *,
    session_dir: Path | None = None,
    kind: str = "combined",
) -> dict[str, Any]:
    """Write hops.jsonl + AUDIT.md (+ optional session mirror)."""
    root = audit_dir(session, session_dir)
    # Kind-specific + combined
    path = root / (f"hops_{kind}.jsonl" if kind != "combined" else "hops.jsonl")
    path.write_text(
        "\n".join(json.dumps(h, ensure_ascii=False) for h in hops) + ("\n" if hops else ""),
        encoding="utf-8",
    )
    if session_dir is not None:
        mirror = Path(session_dir) / "audit" / path.name
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    md_path = root / ("AUDIT.md" if kind == "combined" else f"AUDIT_{kind}.md")
    _write_md(md_path, session, hops, kind=kind)
    if session_dir is not None:
        (Path(session_dir) / "audit" / md_path.name).write_text(
            md_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    n_disagree = sum(1 for h in hops if h.get("disagreement"))
    meta = {
        "generated_utc": _now(),
        "session": session,
        "kind": kind,
        "n_hops": len(hops),
        "n_disagree": n_disagree,
        "hops_path": str(path),
        "md_path": str(md_path),
        "how_to_audit": [
            f"Open {md_path}",
            f"grep DISAGREE {path}",
            "Each hop has channels.vision / .asr / .acoustic / .gold (null if missing)",
        ],
    }
    (root / f"meta_{kind}.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def _write_md(path: Path, session: str, hops: list[dict[str, Any]], *, kind: str) -> None:
    lines = [
        f"# Atomic audit — `{session}` ({kind})",
        "",
        f"hops={len(hops)} · disagreements={sum(1 for h in hops if h.get('disagreement'))}",
        "",
        "Search `DISAGREE` / `FALSE` / `vision=` / `asr=` / `acoustic=`.",
        "",
        "| t | vision | ASR lexicon | acoustic | gold | why |",
        "|---:|---|---|---|---|---|",
    ]
    for h in hops:
        ch = h.get("channels") or {}
        v = ch.get("vision") or {}
        a = ch.get("asr") or {}
        ac = ch.get("acoustic") or {}
        g = ch.get("gold") or {}
        vis = "—"
        if v:
            vis = f"{v.get('class') or v.get('acoustic_bucket') or '?'}"
            if v.get("still"):
                vis += f" [`still`]({Path(str(v['still'])).name})"
        asr = (a.get("lexicon") or a.get("acoustic_bucket") or "—") if a else "—"
        if a and a.get("text"):
            asr = f"{asr}: {(a.get('text') or '')[:40]}"
        aco = "—"
        if ac:
            aco = f"{ac.get('action')} p={ac.get('p')}"
        gold = (g.get("bucket") or "—") if g else "—"
        flag = " **DISAGREE**" if h.get("disagreement") else ""
        lines.append(
            f"| {h.get('t')} | {vis} | {asr} | {aco} | {gold} | {(h.get('why') or '')}{flag} |"
        )
    # Detail blocks for disagreements only (keeps MD readable)
    disag = [h for h in hops if h.get("disagreement")]
    if disag:
        lines.extend(["", "## Disagreement detail", ""])
        for h in disag[:80]:
            ch = h.get("channels") or {}
            lines.append(f"### t={h.get('t')} — `{h.get('why')}`")
            v = ch.get("vision")
            if v:
                lines.append(f"- still: `{v.get('still')}`")
                lines.append(f"- vision class={v.get('class')} · {str(v.get('visual') or '')[:160]}")
            a = ch.get("asr")
            if a:
                lines.append(f"- ASR[{a.get('t0')}-{a.get('t1')}]: {str(a.get('text') or '')[:200]}")
            ac = ch.get("acoustic")
            if ac:
                lines.append(
                    f"- acoustic: action={ac.get('action')} p={ac.get('p')} force_play={ac.get('force_play')}"
                )
            g = ch.get("gold")
            if g:
                lines.append(f"- gold: {g.get('bucket')} {g.get('start_s')}-{g.get('end_s')}")
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_event(session: str, event: dict[str, Any], *, session_dir: Path | None = None) -> Path:
    """Append a non-hop event (export, train, vision run) to events.jsonl."""
    root = audit_dir(session, session_dir)
    path = root / "events.jsonl"
    row = {"utc": _now(), "session": session, **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
