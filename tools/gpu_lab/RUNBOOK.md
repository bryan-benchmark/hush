# Bridge 0 runbook

One causal detector. This file is the order of operations. Nothing here mutes the television.

## Where the code is

This checkout is `fe942fe` on `research/windows-lab-node-01`, fast-forwarded to GitHub `main` from 22 October 2026. [HANDOFF.md](../../HANDOFF.md) still says the repository is private. GitHub shows `bryan-benchmark/hush` as public, and the project has no license. Do not add a license, change visibility, or publish weights from this step.

## 1. Labels, before any audio

```powershell
.\.venv\Scripts\python.exe -m tools.gpu_lab
```

This writes `C:\OHushData\gpu_lab\eligibility.json`.

Training seconds are verified commercial or verified program. Unsure gold and the unmarked NBC commercial around 240 seconds in `hush_20260909_213047` are excluded. The gold file is not edited.

The head will fit on three pre-October games. The mute rule locks on ESPN `hush_20260914_212529`. October, including Thursday Night Football `hush_20261008_205100`, is scored after that and is not used to pick the rule. RedZone is the negative control. The two sealed holdouts are refused.

A run that mutes any program second is broken and has no accuracy. That is [the ladder](../../docs/ohush/research/ACCURACY_LADDER_001/KPI.md).

The October 8 labels contain 2,642.1 commercial seconds across 23 breaks. If every break stays audible for the first 2 seconds and the return is perfect, 46 seconds are still heard and coverage is 98.26%. A 5-second wait leaves 95.65%. A 10-second wait leaves 91.29%. The 99% target needs a faster decision than “wait until a long window is filled with the ad.” The Universal v1 ledger’s 2,583.4 seconds is this same game after 240 seconds that replay could not read. The labels themselves are 2,642.1.

## 2. Restore the recordings

The Google Cloud SDK is not on this machine, `recordings/` is absent, and `C:\OHushData` is empty. Git does not contain the WAV files.

Install the Cloud SDK, then:

```powershell
gcloud auth login
gcloud config set project hushdev
.\.venv\Scripts\python.exe scripts\restore_from_gcs.py
```

The bucket is `gs://hushdev-748439071367-research`. The script copies `raw/` into `recordings/` and three enrolled-show voice files. It does not delete local files.

Run `python -m tools.gpu_lab` again. It should print that the sessions are present and record each `session.json` hash. Embeddings start only after that.

## 3. Embed, fit, and score

After `python -m tools.gpu_lab` says the recordings are present:

```powershell
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install transformers
.\.venv\Scripts\python.exe -m tools.gpu_lab embed
.\.venv\Scripts\python.exe -m tools.gpu_lab train
.\.venv\Scripts\python.exe -m tools.gpu_lab score
```

`embed` caches past-only AST windows of 2, 5, and 10 seconds on the 4070. `train` fits a logistic head on the three pre-October games only. `score` locks the mute rule on ESPN, replays October and RedZone, and writes `C:\OHushData\gpu_lab\NEED.json`. A rule that mutes the game is broken. Nothing here changes the live mute.
