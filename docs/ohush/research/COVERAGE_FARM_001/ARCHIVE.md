# Farm archive doctrine

**Analyze authorized media temporarily. Retain factual labels + audio. Do not archive frames or video.**

## Retain (local gold + Backblaze)

| Object | Why |
|---|---|
| `audio.wav` | Labeling + model training signal |
| `timeline_facts.jsonl` | Per-time facts (human grab, Whisper, aid, still *index*) |
| `take.json` / `label_aid.json` / `transcript.json` / `label_manifest.json` | Session context |

## Local-temp only

| Object | Why |
|---|---|
| `stills/` @ 1 fps | `/farm` grab UI while you label |
| `video.mp4` / `av.mp4` | Densify source only — delete in `farm prepare` |

## Operating model

1. **Always capture** (hierarchy plan). Save every take.
2. **Periodically** `farm tick` — prepare + Ollama draft unlabeled audio. No human required for clear ads.
3. **Human `/farm` at intervals** — when `farm backlog` says `human_needed`, or Ollama is failing/uncertain pile grows.
4. **More GPUs** only when `more_gpu_needed` (critical backlog).

```powershell
# After each capture chunk (or on a timer):
python -m tools.windows_lab farm tick --model qwen2.5:14b
python -m tools.windows_lab farm backlog

# When backlog warns / Ollama struggles:
# open http://127.0.0.1:3010/farm

python -m tools.windows_lab farm package
python -m tools.windows_lab farm upload-b2          # dry-run; --execute with rclone B2
python -m tools.windows_lab farm prepare --purge-stills   # after grabs, drop local frames
```

Auto-accept is narrow: `paid_ad` + high confidence + ad lexicon − show lexicon. Widen only when `farm score` says `promote_autonomy`.
