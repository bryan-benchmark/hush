# OHush experiments

Goal: prove TV audio alone can separate **content vs ads** with cheap methods before any product/AI stack.

## What you have

~3.5h continuous PCM today is **enough to start**. More nights still help later (generalization), but the bottleneck now is **labels + experiment velocity**, not hours.

## Loop

1. **Keep recording** in the background (nights / other channels) — low effort.
2. **Find candidates** (unlabeled discontinuities).
3. **Listen to ~16s clips** and tag `ad` / `content` / `promo` / `other`.
4. **Run baselines** (logreg / SVM / kNN / RF on cheap features).
5. Add the next experiment family only if baselines are weak.

## Commands

```bash
source .venv/bin/activate

# A) discontinuity candidates + listen clips
python experiments/find_candidates.py --export-clips

# B) 1s feature-change peaks (first N chunks)
python experiments/segment_changes.py --max-chunks 8

# C) after you create experiments/features/labels.jsonl
python experiments/run_baselines.py
```

Listen to a clip:

```bash
afplay experiments/clips/hush_20260827_135935/audio_0001_t0123.wav
```

## Break structure (IN vs OUT vs fades)

IN (silence pad into first spot) is often easy. OUT (return to show) is usually **1.5–3+ minutes later**, with **short fades between ads**.

```bash
# Search forward from a known IN
python experiments/break_structure.py --in 108.25
```

In the labeler (`/label`): use **break view** (+2–5 min after IN), yellow ticks = fades, green = suggested OUT. Re-trim your first label if OUT was only ~9s.


| ID | Idea | Needs labels? |
|----|------|-------------|
| E1 | Loudness jump + silence pad candidates | No (verify by ear) |
| E2 | Spectral flux / band-balance change points | No |
| E3 | 1s feature self-similarity breaks | No |
| E4 | LogReg / SVM / RF on MFCC+spectral summaries | Yes (~20–50 clips) |
| E5 | Repeat-ad fingerprinting within the night | Weak (clusters) |
| E6 | Embeddings (OpenL3/CLAP) only if E4 fails | Yes |

Do **not** fine-tune an LLM. Score everything with listen-checks + F1 once labels exist.
