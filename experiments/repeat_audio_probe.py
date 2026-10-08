#!/usr/bin/env python3
"""repeat_audio_probe — find near-identical 5–10s audio repeats.

Hypothesis
----------
The same commercials air repeatedly. If we can find stretches of audio whose
waveforms / spectra match for ~8 seconds in multiple places (same night or
across nights), those repeats are strong commercial evidence — and later a
fingerprint library for causal mute.

This is forensic indexing, not a real-time detector. Holdouts are skipped.
No ML training. Does not modify truth / V1.1.
"""

from __future__ import annotations

import argparse
import json
import struct
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

import ledger

PROBE_ID = "repeat_audio_probe_v0"
TARGET_SR = 8000
WINDOW_S = 8.0
HOP_S = 2.0
N_MELS = 32
N_FRAMES = 16  # time bins inside each window
# Near-identical commercial copies are typically ≥0.92; exact airings often ≥0.97
SIM_THRESHOLD = 0.93
MIN_SEPARATION_S = 45.0  # ignore self / adjacent hops
MIN_RMS = 0.01
SILENT_CHUNK_MAX = 1e-4


def role_of(session: str) -> str:
    ds = json.loads((ledger.GOLD / "DATASETS_V1.json").read_text(encoding="utf-8"))
    return (ds.get("sessions") or {}).get(session, {}).get("role") or ds.get("default_role") or "dev"


def list_dev_sessions() -> list[tuple[str, Path]]:
    out = []
    if not ledger.RECORDINGS.exists():
        return out
    for day in sorted(ledger.RECORDINGS.iterdir()):
        if not day.is_dir():
            continue
        for sess in sorted(day.iterdir()):
            if not (sess / "session.json").exists():
                continue
            if role_of(sess.name) != "dev":
                continue
            out.append((sess.name, sess))
    return out


def load_mono(path: Path) -> tuple[int, np.ndarray]:
    raw = path.read_bytes()
    if raw[0:4] != b"RIFF":
        raise RuntimeError(f"not wav: {path}")
    ch = struct.unpack_from("<H", raw, 22)[0]
    rate = struct.unpack_from("<I", raw, 24)[0]
    pos = 12
    data_off = 44
    while pos + 8 <= len(raw):
        cid = raw[pos : pos + 4]
        sz = struct.unpack_from("<I", raw, pos + 4)[0]
        if cid == b"data":
            data_off = pos + 8
            break
        pos += 8 + sz + (sz % 2)
    payload = raw[data_off:]
    usable = len(payload) - (len(payload) % (ch * 2))
    x = np.frombuffer(payload[:usable], dtype="<i2").astype(np.float32)
    x = x.reshape(-1, ch).mean(axis=1) / 32768.0
    return int(rate), x


def downsample(x: np.ndarray, sr: int, target: int = TARGET_SR) -> np.ndarray:
    if sr == target:
        return x.astype(np.float32, copy=False)
    g = np.gcd(sr, target)
    return resample_poly(x, target // g, sr // g).astype(np.float32)


def mel_filterbank(n_fft: int, sr: int, n_mels: int = N_MELS) -> np.ndarray:
    """Triangular mel weights (n_mels, n_fft//2+1)."""
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    mels = np.linspace(hz2mel(20), hz2mel(sr / 2), n_mels + 2)
    hz = mel2hz(mels)
    weights = np.zeros((n_mels, len(freqs)), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = hz[i], hz[i + 1], hz[i + 2]
        rising = (freqs - left) / max(center - left, 1e-9)
        falling = (right - freqs) / max(right - center, 1e-9)
        weights[i] = np.maximum(0.0, np.minimum(rising, falling))
    # normalize
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
    return weights


_MEL = mel_filterbank(1024, TARGET_SR, N_MELS)


def fingerprint_window(x8k: np.ndarray) -> np.ndarray | None:
    """L2-normalized log-mel fingerprint for one WINDOW_S clip at TARGET_SR."""
    need = int(WINDOW_S * TARGET_SR)
    if x8k.shape[0] < need:
        return None
    seg = x8k[:need]
    rms = float(np.sqrt(np.mean(seg * seg) + 1e-12))
    if rms < MIN_RMS:
        return None
    # frame into N_FRAMES overlapping chunks
    frame_n = need // N_FRAMES
    feats = np.zeros((N_FRAMES, N_MELS), dtype=np.float32)
    for i in range(N_FRAMES):
        frame = seg[i * frame_n : (i + 1) * frame_n]
        # pad/truncate to 1024 for rfft convenience via zero-pad
        n_fft = 1024
        if frame.shape[0] < n_fft:
            buf = np.zeros(n_fft, dtype=np.float32)
            buf[: frame.shape[0]] = frame
            frame = buf
        else:
            frame = frame[:n_fft] * np.hanning(n_fft).astype(np.float32)
        spec = np.abs(np.fft.rfft(frame, n=n_fft)) ** 2
        mel = _MEL @ spec
        feats[i] = np.log1p(mel * 1e6)
    v = feats.reshape(-1)
    v -= v.mean()
    n = float(np.linalg.norm(v) + 1e-12)
    return (v / n).astype(np.float32)


def coarse_key(vec: np.ndarray, bits: int = 64) -> int:
    """Sign-bit hash of the first `bits` dims for candidate bucketing."""
    take = min(bits, vec.shape[0])
    signs = (vec[:take] >= 0).astype(np.uint8)
    key = 0
    for b in signs:
        key = (key << 1) | int(b)
    return key


def index_session(
    session: str,
    session_dir: Path,
    *,
    max_hours: float | None = None,
) -> tuple[list[dict], np.ndarray]:
    """Return meta rows + fingerprint matrix for one session."""
    metas: list[dict] = []
    vecs: list[np.ndarray] = []
    wavs = sorted(session_dir.glob("audio_*.wav"))
    # Prefer session.json chunk offsets when present (holes preserve clock)
    meta_path = session_dir / "session.json"
    chunk_starts: dict[str, float] = {}
    if meta_path.exists():
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        for c in data.get("chunks") or []:
            if c.get("file") and c.get("start_elapsed_seconds") is not None:
                chunk_starts[str(c["file"])] = float(c["start_elapsed_seconds"])

    elapsed_cursor = 0.0
    hop = int(HOP_S * TARGET_SR)
    win = int(WINDOW_S * TARGET_SR)
    max_s = None if max_hours is None else max_hours * 3600.0

    for wav in wavs:
        rate, x = load_mono(wav)
        dur = len(x) / rate
        start_elapsed = chunk_starts.get(wav.name, elapsed_cursor)
        if np.max(np.abs(x)) < SILENT_CHUNK_MAX:
            elapsed_cursor = max(elapsed_cursor, start_elapsed + dur)
            continue
        if max_s is not None and start_elapsed >= max_s:
            break
        x8 = downsample(x, rate, TARGET_SR)
        # stride through chunk
        n = x8.shape[0]
        t0 = 0
        while t0 + win <= n:
            abs_t = start_elapsed + (t0 / TARGET_SR)
            if max_s is not None and abs_t >= max_s:
                break
            fp = fingerprint_window(x8[t0 : t0 + win])
            if fp is not None:
                metas.append(
                    {
                        "session": session,
                        "file": wav.name,
                        "elapsed_seconds": round(float(abs_t), 3),
                        "window_s": WINDOW_S,
                        "coarse": coarse_key(fp),
                    }
                )
                vecs.append(fp)
            t0 += hop
        elapsed_cursor = max(elapsed_cursor, start_elapsed + dur)

    if not vecs:
        return [], np.zeros((0, N_FRAMES * N_MELS), dtype=np.float32)
    return metas, np.stack(vecs, axis=0)


class UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.r[ra] < self.r[rb]:
            self.p[ra] = rb
        elif self.r[ra] > self.r[rb]:
            self.p[rb] = ra
        else:
            self.p[rb] = ra
            self.r[ra] += 1


def find_matches(
    metas: list[dict],
    X: np.ndarray,
    *,
    sim_thr: float = SIM_THRESHOLD,
    min_sep: float = MIN_SEPARATION_S,
    block: int = 256,
) -> list[tuple[int, int, float]]:
    """Return (i, j, sim) pairs with near-identical fingerprints."""
    n = X.shape[0]
    if n < 2:
        return []
    pairs: list[tuple[int, int, float]] = []
    # Bucket by coarse key (±1 Hamming neighbor too expensive); exact key first
    buckets: dict[int, list[int]] = defaultdict(list)
    for i, m in enumerate(metas):
        buckets[int(m["coarse"])].append(i)

    # Also compare within sliding time via full block matmul among candidates
    # For modest N, blockwise all-pairs on X is fine and catches cross-bucket near misses.
    for i0 in range(0, n, block):
        a = X[i0 : i0 + block]
        sims = a @ X.T  # (b, n)
        for bi, row in enumerate(sims):
            i = i0 + bi
            mi = metas[i]
            # only keep j > i
            for j in np.flatnonzero(row > sim_thr):
                j = int(j)
                if j <= i:
                    continue
                mj = metas[j]
                if mi["session"] == mj["session"]:
                    if abs(float(mi["elapsed_seconds"]) - float(mj["elapsed_seconds"])) < min_sep:
                        continue
                pairs.append((i, j, float(row[j])))
    pairs.sort(key=lambda t: -t[2])
    return pairs


def cluster_pairs(n: int, pairs: list[tuple[int, int, float]]) -> list[list[int]]:
    uf = UnionFind(n)
    for i, j, _ in pairs:
        uf.union(i, j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)
    clusters = [sorted(g) for g in groups.values() if len(g) >= 2]
    clusters.sort(key=lambda g: -len(g))
    return clusters


def load_gold_seeds(session: str) -> list[dict]:
    truth = [
        t
        for t in ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
        if t.get("session") == session
        and t.get("event", "ad_break") == "ad_break"
        and t.get("event_class") == "commercial"
        and t.get("desired_action") == "mute"
        and t.get("confidence") != "unsure"
    ]
    truth.sort(key=lambda t: float(t["start_seconds"]))
    return truth


def seed_hits_for_gold(
    gold: list[dict],
    metas: list[dict],
    X: np.ndarray,
    *,
    sim_thr: float,
) -> list[dict]:
    """For each gold commercial, take the fingerprint nearest its midpoint and find repeats."""
    if not gold or X.shape[0] == 0:
        return []
    by_session = defaultdict(list)
    for i, m in enumerate(metas):
        by_session[m["session"]].append(i)

    rows = []
    for g in gold:
        gin = float(g["start_seconds"])
        gout = float(g["end_seconds"])
        mid = 0.5 * (gin + gout)
        # Prefer a window fully inside the break
        target = min(max(gin + 2.0, mid - WINDOW_S / 2), max(gin, gout - WINDOW_S - 0.5))
        # nearest meta in same session
        cand = by_session.get(g["session"]) or []
        if not cand:
            continue
        best_i = min(cand, key=lambda i: abs(float(metas[i]["elapsed_seconds"]) - target))
        q = X[best_i]
        sims = X @ q
        hits = []
        for j in np.argsort(-sims)[:40]:
            j = int(j)
            if sims[j] < sim_thr:
                break
            mj = metas[j]
            # skip the query neighborhood inside this same break
            if mj["session"] == g["session"] and gin - 5 <= float(mj["elapsed_seconds"]) <= gout + 5:
                continue
            hits.append(
                {
                    "session": mj["session"],
                    "elapsed_seconds": mj["elapsed_seconds"],
                    "similarity": round(float(sims[j]), 4),
                }
            )
        rows.append(
            {
                "gold_id": g["gold_id"],
                "gold_in": gin,
                "gold_out": gout,
                "query_elapsed": metas[best_i]["elapsed_seconds"],
                "n_hits": len(hits),
                "hits": hits[:12],
            }
        )
    return rows


def render_md(payload: dict) -> str:
    lines = [
        "# Repeat audio probe",
        "",
        f"Probe `{payload['probe_id']}` · window={payload['window_s']}s hop={payload['hop_s']}s · sim≥{payload['sim_threshold']}",
        "",
        f"Sessions indexed: **{len(payload['sessions'])}** · fingerprints: **{payload['n_fingerprints']}** · "
        f"match pairs: **{payload['n_pairs']}** · clusters (≥2): **{payload['n_clusters']}**",
        "",
        "## Top repeat clusters",
        "",
    ]
    for ci, c in enumerate(payload["clusters"][:25], 1):
        lines.append(
            f"### Cluster {ci} · {c['size']} occurrences · mean_sim={c['mean_sim']:.3f}"
        )
        lines.append("")
        for occ in c["occurrences"][:12]:
            lines.append(
                f"- `{occ['session']}` @ **{occ['elapsed_seconds']:.1f}s**"
            )
        if c["size"] > 12:
            lines.append(f"- … +{c['size'] - 12} more")
        lines.append("")

    if payload.get("gold_seeds"):
        lines += ["## Gold commercial → repeat hits", ""]
        for g in payload["gold_seeds"]:
            lines.append(
                f"- gold IN `{g['gold_in']:.1f}` → query @{g['query_elapsed']:.1f}s · "
                f"**{g['n_hits']}** repeats elsewhere"
            )
            for h in g["hits"][:5]:
                lines.append(
                    f"  - `{h['session']}` @ {h['elapsed_seconds']:.1f}s (sim={h['similarity']})"
                )
        lines.append("")

    lines += [
        "## Verdict",
        "",
        payload["verdict"],
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--session",
        action="append",
        default=[],
        help="Dev session name(s). Default: gold session + next 2 unfinished-ish sessions.",
    )
    ap.add_argument("--max-hours-per-session", type=float, default=0.0, help="0 = full session")
    ap.add_argument("--sim", type=float, default=SIM_THRESHOLD)
    ap.add_argument("--gold-session", default="hush_20260914_212529")
    args = ap.parse_args()

    all_dev = list_dev_sessions()
    by_name = {n: p for n, p in all_dev}
    if args.session:
        sessions = [(n, by_name[n]) for n in args.session if n in by_name]
    else:
        # gold first, then other recent / large sessions
        prefer = [
            args.gold_session,
            "hush_20260921_204539",
            "hush_20260913_210542",
            "hush_20261004_204010",
        ]
        sessions = []
        for n in prefer:
            if n in by_name:
                sessions.append((n, by_name[n]))
        if not sessions:
            sessions = all_dev[:3]

    max_h = args.max_hours_per_session or None
    metas: list[dict] = []
    chunks: list[np.ndarray] = []
    for name, path in sessions:
        print(f"indexing {name} …", flush=True)
        m, X = index_session(name, path, max_hours=max_h)
        print(f"  → {len(m)} fingerprints", flush=True)
        metas.extend(m)
        if X.shape[0]:
            chunks.append(X)

    if not chunks:
        raise SystemExit("no fingerprints")
    X = np.concatenate(chunks, axis=0)
    print(f"matching {X.shape[0]} fingerprints …", flush=True)
    pairs = find_matches(metas, X, sim_thr=args.sim)
    clusters_idx = cluster_pairs(len(metas), pairs)

    cluster_rows = []
    for g in clusters_idx:
        # mean sim among pairs inside cluster (approx from member links)
        member_set = set(g)
        sims = [s for i, j, s in pairs if i in member_set and j in member_set]
        cluster_rows.append(
            {
                "size": len(g),
                "mean_sim": float(np.mean(sims)) if sims else None,
                "occurrences": [
                    {
                        "session": metas[i]["session"],
                        "elapsed_seconds": metas[i]["elapsed_seconds"],
                        "file": metas[i]["file"],
                    }
                    for i in g
                ],
            }
        )

    gold = load_gold_seeds(args.gold_session) if args.gold_session in {n for n, _ in sessions} else []
    gold_seed_rows = seed_hits_for_gold(gold, metas, X, sim_thr=args.sim)

    n_multi_session = sum(
        1
        for c in cluster_rows
        if len({o["session"] for o in c["occurrences"]}) > 1
    )
    n_gold_with_hits = sum(1 for g in gold_seed_rows if g["n_hits"] > 0)

    if n_multi_session >= 3 or n_gold_with_hits >= 5:
        verdict = (
            f"PROMISING_FINGERPRINT — {len(cluster_rows)} repeat clusters "
            f"({n_multi_session} cross-session); {n_gold_with_hits}/{len(gold_seed_rows)} "
            "gold commercials have near-identical audio elsewhere. "
            "Worth building a commercial fingerprint library next."
        )
    elif cluster_rows or n_gold_with_hits:
        verdict = (
            f"WEAK_SIGNAL — found {len(cluster_rows)} clusters and "
            f"{n_gold_with_hits}/{len(gold_seed_rows)} gold ads with repeats. "
            "Tighten alignment / add more nights before relying on this for mute."
        )
    else:
        verdict = (
            "NO_REPEATS — no near-identical 8s windows under this threshold. "
            "Try lower --sim, denser hop, or more sessions."
        )

    payload = {
        "probe_id": PROBE_ID,
        "window_s": WINDOW_S,
        "hop_s": HOP_S,
        "sim_threshold": args.sim,
        "sessions": [n for n, _ in sessions],
        "n_fingerprints": len(metas),
        "n_pairs": len(pairs),
        "n_clusters": len(cluster_rows),
        "n_cross_session_clusters": n_multi_session,
        "clusters": cluster_rows[:50],
        "gold_seeds": gold_seed_rows,
        "verdict": verdict,
    }

    stamp = ledger.run_id_stamp()
    out_json = ledger.ROOT / "experiments" / "reports" / f"repeat_audio_{stamp}.json"
    out_md = ledger.ROOT / "experiments" / "reports" / f"repeat_audio_{stamp}.md"
    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({"report_md": str(out_md), "verdict": verdict, "clusters": len(cluster_rows)}, indent=2))


if __name__ == "__main__":
    main()
