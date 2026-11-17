import json
from datetime import datetime, timezone
from pathlib import Path


def stats(sess: str) -> dict:
    root = Path(r"C:\OHushData\indexes\farm_labels\audit") / sess
    vh = [
        json.loads(l)
        for l in (root / "hops_vision.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    ok = sum(1 for h in vh if (h.get("channels") or {}).get("vision", {}).get("ok"))
    ch = [
        json.loads(l)
        for l in (root / "hops.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    return {
        "session": sess,
        "vision_ok_pct": round(100 * ok / len(vh), 1) if vh else None,
        "vision_hops": len(vh),
        "combined_hops": len(ch),
        "combined_disagree": sum(1 for h in ch if h.get("disagreement")),
        "audit_md": str(root / "AUDIT.md"),
    }


def main() -> None:
    rows = [
        stats("20261110T1339Z_pluto_cbs_sports_hq"),
        stats("20261110T1401Z_pluto_cbs_sports_hq"),
    ]
    emb_root = Path(r"C:\OHushData\gpu_lab\audio_learn\embeddings\farm")
    embs = sorted(p.name for p in emb_root.glob("*.npz"))
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "gate": {
            "sample_vision_ok_pct_min": 90,
            "sample_pass": all((r["vision_ok_pct"] or 0) >= 90 for r in rows),
            "vision_not_in_farm_accepted": True,
            "embed_sessions": len(embs),
        },
        "short_sessions": rows,
        "embeddings": embs,
        "next": [
            "Spot-check AUDIT.md DISAGREE on both short sessions",
            "Do not --from-export vision on all 12 until human reviews candidates",
            "Shadow head refit can use farm embeddings + farm_accepted (human only)",
        ],
    }
    root = Path(r"C:\OHushData\indexes\farm_labels\audit")
    (root / "SCALE_GATE.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Scale gate — {out['generated_utc'][:19]}Z",
        "",
        f"- sample vision ≥90%: **{out['gate']['sample_pass']}**",
        "- vision blocked from farm_accepted: **True**",
        f"- farm embeddings: **{len(embs)}** sessions",
        "",
        "| Session | vision ok % | combined DISAGREE | AUDIT |",
        "|---|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['session']}` | {r['vision_ok_pct']} | {r['combined_disagree']} | `{r['audit_md']}` |"
        )
    lines.extend(
        [
            "",
            "Vision candidates remain in `farm_vision_candidates.jsonl` — not train gold.",
            "",
        ]
    )
    (root / "SCALE_GATE.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
