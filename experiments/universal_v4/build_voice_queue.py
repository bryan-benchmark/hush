"""Football voices, most heard first.

The longest groups in a game are the ones a person should name first.
Hulu is left out. A group is not a person until someone names the sample.
October 8, 10, 11, and 12 have no speaker pass, so they are absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog

REPO = Path(__file__).resolve().parents[2]
EXP = REPO / "experiments/exp002"
OUT = REPO / "docs/ohush/research/VOICE_ROSTER_001"
MIN_PROGRAM_SECONDS = 180.0
MIN_AD_SECONDS = 60.0
MAX_PROGRAM_PER_SESSION = 6


def date_label(info: dict) -> str:
    raw = info.get("date") or ""
    parts = raw.split("-")
    if len(parts) != 3:
        return raw or "Unknown date"
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    return f"{months[int(parts[1]) - 1]} {int(parts[2])}, {parts[0]}"


def ad_share(windows: pd.DataFrame, ads: list[tuple[float, float]]) -> float:
    total = 0.0
    inside = 0.0
    for row in windows.itertuples(index=False):
        start = float(row.window_start)
        end = float(row.window_end)
        span = max(0.0, end - start)
        if span <= 0:
            continue
        total += span
        for ad_start, ad_end in ads:
            overlap = min(end, ad_end) - max(start, ad_start)
            if overlap > 0:
                inside += overlap
    if total <= 0:
        return 0.0
    return inside / total


def label_for(info: dict) -> str:
    network = info.get("network_or_service") or "Unknown"
    stamp = info.get("session_id", "")
    day = stamp[5:13] if stamp.startswith("hush_") else ""
    if len(day) == 8:
        day = f"{day[4:6]}/{day[6:8]}"
    return f"{network} · {day}" if day else network


def sample_window(windows: pd.DataFrame) -> pd.Series:
    usable = windows[windows["duration"] >= 1.5]
    if usable.empty:
        usable = windows
    similarity = pd.to_numeric(usable["similarity_to_best_known"], errors="coerce")
    strong = usable[similarity.fillna(0) >= 0.35]
    if not strong.empty:
        usable = strong
    starts = pd.to_numeric(usable["window_start"], errors="coerce")
    median = float(starts.median())
    return usable.iloc[(starts - median).abs().argmin()]


def main() -> None:
    catalog = load_catalog()
    ads_by_session: dict[str, list[tuple[float, float]]] = {}
    for row in commercials(coverage()):
        ads_by_session.setdefault(row["session"], []).append((float(row["start_seconds"]), float(row["end_seconds"])))
    public = []
    key = []
    for folder in sorted(path for path in EXP.iterdir() if path.is_dir() and path.name.startswith("hush_")):
        info = catalog.get(folder.name, {})
        if (info.get("content_type") or "") != "sports":
            continue
        segments = pd.read_parquet(folder / "speaker_segments.parquet")
        windows = segments[segments["row_kind"] == "embedding_window"].copy()
        grouped = (
            windows.groupby("assigned_cluster_id")["cum_after"]
            .max()
            .sort_values(ascending=False)
        )
        program_n = 0
        chosen = []
        for cid, seconds in grouped.items():
            seconds = float(seconds)
            if seconds < MIN_AD_SECONDS:
                continue
            share = ad_share(windows[windows["assigned_cluster_id"] == cid], ads_by_session.get(folder.name, []))
            is_ad = share >= 0.5
            if is_ad and seconds >= MIN_AD_SECONDS:
                chosen.append((cid, seconds, share))
            elif not is_ad and seconds >= MIN_PROGRAM_SECONDS and program_n < MAX_PROGRAM_PER_SESSION:
                chosen.append((cid, seconds, share))
                program_n += 1
        for cid, seconds, share in chosen:
            clip = sample_window(windows[windows["assigned_cluster_id"] == cid])
            start = round(float(clip["window_start"]), 3)
            heard = round(seconds, 1)
            public.append({
                "session": folder.name,
                "play_start": start,
                "duration": 8.0,
                "heard_seconds": heard,
                "session_label": label_for({**info, "session_id": folder.name}),
                "date_label": date_label(info),
                "program": info.get("show") or "Unknown program",
                "network": info.get("network_or_service") or "Unknown",
                "ad_voice": share >= 0.5,
                "ad_share": round(share, 3),
            })
            key.append({
                "session": folder.name,
                "cluster_id": cid,
                "heard_seconds": heard,
                "play_start": start,
                "ad_voice": share >= 0.5,
                "ad_share": round(share, 3),
            })
    # Thursday Night Football is a known booth. Ask about those jobs first.
    # These samples are game talk from the two longest voices, then the show line.
    # The names are the question, not a saved identity.
    tnf = []
    for item, secret in zip(public, key):
        if item["session"] != "hush_20260924_220624":
            continue
        if secret["cluster_id"] == "c0008":
            item = {**item, "play_start": 3173.7, "ask": "Longest voice. On Thursday Night Football that should be Al Michaels.", "suggestions": ["Al Michaels", "Kirk Herbstreit", "Someone else"]}
            secret = {**secret, "play_start": 3173.7, "ask": item["ask"]}
            tnf.append((0, item, secret))
        elif secret["cluster_id"] == "c0002":
            item = {**item, "play_start": 3255.5, "ask": "Second voice. On Thursday Night Football that should be Kirk Herbstreit.", "suggestions": ["Kirk Herbstreit", "Al Michaels", "Someone else"]}
            secret = {**secret, "play_start": 3255.5, "ask": item["ask"]}
            tnf.append((1, item, secret))
    tnf.sort()
    show = {
        "session": "hush_20260924_220624",
        "play_start": 4460.0,
        "duration": 8.0,
        "heard_seconds": 0,
        "session_label": "Prime · 09/24",
        "date_label": "September 24, 2026",
        "program": "Falcons at Packers",
        "network": "Prime",
        "ad_voice": False,
        "ad_share": 0,
        "ask": "This is the Thursday Night Football on Prime line. It is the show, not a person in the booth.",
        "suggestions": ["Show open or close", "An ad", "A person"],
    }
    show_key = {
        "session": show["session"],
        "cluster_id": "c0024",
        "heard_seconds": 0,
        "play_start": 4460.0,
        "ad_voice": False,
        "ad_share": 0,
        "ask": show["ask"],
    }
    used = {secret["cluster_id"] for _, _, secret in tnf}
    rest_public = []
    rest_key = []
    for item, secret in zip(public, key):
        if item["session"] == "hush_20260924_220624" and secret["cluster_id"] in used:
            continue
        rest_public.append(item)
        rest_key.append(secret)
    rest = sorted(zip(rest_public, rest_key), key=lambda pair: (pair[0]["ad_voice"], -pair[0]["heard_seconds"]))
    rest_public = [item for item, _ in rest]
    rest_key = [secret for _, secret in rest]
    public = [item for _, item, _ in tnf] + [show] + rest_public
    key = [secret for _, _, secret in tnf] + [show_key] + rest_key
    order = list(range(len(public)))
    public = [public[i] for i in order]
    key = [key[i] for i in order]
    for index, (item, secret) in enumerate(zip(public, key), start=1):
        qid = f"v{index:03d}"
        item["id"] = qid
        item["rank"] = index
        item["n_in_session"] = len(public)
        secret["id"] = qid
        secret["rank"] = index
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "queue_public.json").write_text(
        json.dumps(
            {
                "instructions": "Thursday Night Football comes first: the longest voice, the second voice, then the show line. Other games follow, program voices before ads. A name is not stored until you save it. Intro music is not in this list.",
                "excluded_from_broadcasters": [
                    {
                        "session": "hush_20260827_135935",
                        "service": "Hulu",
                        "reason": "Scripted. No broadcasters. Actress names are not being collected.",
                    },
                    {
                        "session": "hush_20261007_220650",
                        "service": "Hulu",
                        "reason": "Scripted. No broadcasters. Actress names are not being collected.",
                    },
                ],
                "missing_sessions": [
                    "hush_20261008_205100",
                    "hush_20261010_222400",
                    "hush_20261011_135700",
                    "hush_20261011_204300",
                    "hush_20261012_204200",
                ],
                "items": public,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "queue_key.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    print(len(public))
    for item in public:
        kind = "ad" if item["ad_voice"] else "program"
        print(f"{item['id']} {item['date_label']:20} {item['network']:16} {item['program'][:28]:28} {kind:8} {item['ad_share']:.0%} {item['heard_seconds']:7.0f}s")


if __name__ == "__main__":
    main()
