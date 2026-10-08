#!/usr/bin/env python3
"""
OHush baseline experiment matrix (research).

Takes labeled windows JSONL:
  {"path": "...wav", "label": "ad"|"content", "session": "..."}

Or builds weak labels from candidate clips after you tag a CSV.

Runs several cheap detectors and writes a comparison report:
  experiments/reports/baseline_<timestamp>.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC


def load_mono(path: Path, target_sr: int = 16000):
    import librosa

    y, sr = librosa.load(str(path), sr=target_sr, mono=True)
    return y, sr


def features(y: np.ndarray, sr: int) -> np.ndarray:
    import librosa

    # Fixed-length summary vector
    if len(y) < sr // 2:
        y = np.pad(y, (0, sr // 2 - len(y)))

    rms = librosa.feature.rms(y=y).mean()
    zcr = librosa.feature.zero_crossing_rate(y).mean()
    cent = librosa.feature.spectral_centroid(y=y, sr=sr).mean()
    bw = librosa.feature.spectral_bandwidth(y=y, sr=sr).mean()
    roll = librosa.feature.spectral_rolloff(y=y, sr=sr).mean()
    flat = librosa.feature.spectral_flatness(y=y).mean()
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_m = mfcc.mean(axis=1)
    mfcc_s = mfcc.std(axis=1)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr).mean(axis=1)
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    onset_m = onset.mean()
    onset_s = onset.std()

    vec = np.concatenate(
        [
            [rms, zcr, cent, bw, roll, flat, onset_m, onset_s],
            mfcc_m,
            mfcc_s,
            chroma,
        ]
    )
    return vec.astype(np.float64)


def load_labeled(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--labels",
        default="experiments/features/labels.jsonl",
        help="JSONL with path + label (ad|content)",
    )
    args = ap.parse_args()

    label_path = Path(args.labels)
    if not label_path.exists():
        print(
            f"No labels at {label_path}.\n"
            "Create labels.jsonl after listening to candidate clips, e.g.:\n"
            '  {"path":"experiments/clips/.../cand.wav","label":"ad"}\n'
            '  {"path":"experiments/clips/.../cand.wav","label":"content"}\n'
        )
        return

    rows = load_labeled(label_path)
    X = []
    y = []
    kept = []
    for r in rows:
        lab = r["label"].lower().strip()
        if lab not in ("ad", "content"):
            continue
        p = Path(r["path"])
        if not p.exists():
            print("missing", p)
            continue
        vec = features(*load_mono(p))
        X.append(vec)
        y.append(1 if lab == "ad" else 0)
        kept.append(r)

    X = np.vstack(X)
    y = np.asarray(y)
    print(f"Examples: {len(y)}  ads={int(y.sum())} content={int((1-y).sum())}  dim={X.shape[1]}")

    if len(y) < 12 or len(set(y.tolist())) < 2:
        print("Need at least ~12 labeled clips with both classes before CV baselines.")
        return

    models = {
        "logreg": Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
            ]
        ),
        "linear_svm": Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LinearSVC(class_weight="balanced", dual="auto")),
            ]
        ),
        "knn3": Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", KNeighborsClassifier(n_neighbors=3)),
            ]
        ),
        "rf": RandomForestClassifier(
            n_estimators=200,
            class_weight="balanced",
            random_state=0,
        ),
    }

    cv = StratifiedKFold(n_splits=min(5, int(y.sum()), int((1 - y).sum()), len(y) // 2) or 2)
    results = {}
    for name, model in models.items():
        pred = cross_val_predict(model, X, y, cv=cv)
        f1 = f1_score(y, pred, zero_division=0)
        report = classification_report(
            y, pred, target_names=["content", "ad"], zero_division=0, output_dict=True
        )
        results[name] = {"macro_f1": f1, "report": report}
        print(f"\n=== {name}  F1(ad vs content one-vs-rest f1_score)={f1:.3f} ===")
        print(classification_report(y, pred, target_names=["content", "ad"], zero_division=0))

    # Unsupervised sanity: do ads/content separate in PCA space?
    zs = StandardScaler().fit_transform(X)
    xy = PCA(n_components=2, random_state=0).fit_transform(zs)
    km = KMeans(n_clusters=2, n_init=10, random_state=0).fit_predict(zs)
    # agreement with labels (best matching)
    agree = max(
        float(np.mean(km == y)),
        float(np.mean(km == (1 - y))),
    )

    out = {
        "n": len(y),
        "ads": int(y.sum()),
        "content": int((1 - y).sum()),
        "supervised": results,
        "kmeans_label_agreement": agree,
        "pca_points": [
            {"x": float(xy[i, 0]), "y": float(xy[i, 1]), "label": int(y[i])}
            for i in range(len(y))
        ],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out_path = Path("experiments/reports") / f"baseline_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nKMeans agreement with labels: {agree:.3f}")
    print("Wrote", out_path)


if __name__ == "__main__":
    main()
