# COVERAGE_FARM_001

Agent-owned Streamers coverage loop. Farm corpus is `authorized_stream_reference` under `C:\OHushData`. It does not merge into sealed football optical gold.

## Doctrine

Three operations — [`ORCHESTRATION.md`](ORCHESTRATION.md). Archive — [`ARCHIVE.md`](ARCHIVE.md). Hierarchy — [`HIERARCHY.md`](HIERARCHY.md).

Temporary analysis of authorized video/stills → **retain audio + factual JSON**. Frames local-temp; video deleted after densify.

## Owner job

**Default:** nothing. Ops 1+2 run autonomously.

**Only when** `farm human` says `required=true` (or Ollama is stuck): open http://127.0.0.1:3010/farm.

## Agent commands

```powershell
cd C:\Users\faceo\Projects\ohush
.\.venv\Scripts\Activate.ps1
$env:OHUSH_DATA_ROOT = "C:\OHushData"

python -m tools.windows_lab farm status          # all three ops
python -m tools.windows_lab farm record          # op1 plan
python -m tools.windows_lab farm label --tick    # op2 Ollama pass + behind
python -m tools.windows_lab farm human           # op3 gate
```

## Priority

Live events when actually on air → daypart fill (locals any US DMA anytime) → news → FAST. Stills rate for local labeling: **1 fps**.

## Parallel captures

Two clean instances need distinct virtual cables. See `C:\OHushData\farm\MULTI_INSTANCE_SETUP.md`.

## Artifacts

| Path | Role |
|---|---|
| `indexes/capture_plan.json` | Current assignments |
| `indexes/COVERAGE_BOARD.md` | Slot × daypart board |
| `indexes/farm_labels/` | grab judgments, drafts, score |
| `work/capture/streamers/*/timeline_facts.jsonl` | Retained facts |
| `work/capture/streamers/*/stills/` | Local-temp only |
