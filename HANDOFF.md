# Handoff

22 October 2026. `main` is the code and the labels. The recordings are not in git. They are in the private bucket named below.

## What this is

OHush listens to a television through an optical cable. The Mac records that audio and can play it back, or play a cover instead. The question under test is when a commercial has started and when the show has returned.

The live desk is `ohush_live`. The monitor is `apps/monitor` at http://127.0.0.1:3010/. The engine listens on http://127.0.0.1:8770/. `recorder.py` is the earlier capture tool and still uses port 8787. The sports desk is the path that plays on the television.

## Goal

The research target is 99.99% correct treatment of audible programming versus advertising. That is a north star. It is not a product claim. 99.99% of a three-hour game is 1.08 seconds of audio treated the wrong way.

A muted second of the game breaks the run. That run has no accuracy. On a run that stays off the game, accuracy is commercial seconds actually held, divided by 17,648.4. The rules are in `docs/ohush/research/ACCURACY_LADDER_001/KPI.md`. The contract is `docs/ohush/swarm/RESEARCH_CONTRACT.md`. The ledger is `docs/ohush/swarm/SCOREBOARD.md`.

## Where the plan is

The champion is no authorized mute. Nothing automatic is allowed to hide the game. Universal v1, the published count-200 fingerprint, is the research baseline: 25.0 commercial seconds covered, 0 program seconds, 2 of 136 football pods. That is 0.14%.

The published lines, scored and not installed, hold 116.0 of 17,648.4 commercial seconds and 0 game seconds. That is 0.66%. 134 of 136 commercials are never muted. The median start lag on that ceiling is 132.5 seconds. `docs/ohush/research/V1_SCORECARD_001/`.

What is already decided:

| Decision | State |
| --- | --- |
| Enrolled-show return at 0.10 | Locked in the live engine. A 30-second rolling max at or over 0.10 brings the game back and blocks a solo audio cover. It does not start a cover. `src/hush/voice_floor.py` |
| Count-200 fingerprint cover | Unchanged. Still the only research cover |
| Automatic cover, 180-second output clock | Wired. If a cover never lets go, the television comes back. This does not raise the 0.66% |
| Waiting for the song to drop before a return | Measured. Not installed. Median extra wait 16 seconds. On the long stays it would hide a touchdown |
| Outro fingerprint, then the booth two minutes later | Measured 19 October. Broken. The last 8 seconds before a break are not a repeated song, and the two-minute look hides 1,979 seconds of game even if every outro is handed to it. `docs/ohush/research/OUTRO_RETURN_001/` |
| Bounded audfprint as a finder | Closed |
| Enhanced feeds (schedule, DAI, timeout) | Not measured. No paired optical recording |

The open problem is the start. A new cover has to catch a break the fingerprint did not hold, and program seconds have to stay at zero. A higher score on the same tapes is not that result. October recordings were already inspected. Do not fit a threshold on them and publish it as held-out.

Sealed, and not to be opened: `hush_20260917_205513`, `hush_20260920_200635`.

## Open source

This repository is private. There is no license on the project itself. Publishing it, or treating the recordings as a public dataset, is a separate decision.

These pieces are other people's open source. Keep their notices with their code.

| Piece | Role | Terms |
| --- | --- | --- |
| [audfprint](https://github.com/dpwe/audfprint) | Spectral-landmark fingerprints. Submodule at `experiments/broadcast_intelligence/third_party/audfprint`, commit `cb03ba9` | MIT. Dan Ellis, Columbia University, and Google |
| SpeechBrain ECAPA (`speechbrain/spkrec-ecapa-voxceleb`) | Enrolled-show voice. Downloaded on the first live launch into `ohush_live/cache`. Not in git | SpeechBrain's own license |
| NumPy, SciPy, librosa, sounddevice, soundfile, scikit-learn, pandas | Research and capture. `requirements.txt` | Their own licenses |
| Next.js, React, TypeScript, Tailwind | Monitor in `apps/monitor` | MIT |

The private bucket is not an open dataset. `gcloud` access is required.

## Another computer

GitHub: https://github.com/bryan-benchmark/hush

The bucket is `gs://hushdev-748439071367-research` in Google Cloud project `hushdev`. Public access is blocked. Log in as the account that can read that project.

```bash
git clone --recurse-submodules git@github.com:bryan-benchmark/hush.git
cd hush
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
gcloud auth login
gcloud config set project hushdev
python scripts/restore_from_gcs.py
```

`scripts/restore_from_gcs.py` fills `recordings/` and the three enrolled-show voice files (`enroll_snf.npy`, `enroll_mnf.npy`, `enroll_tnf.npy`). It does not delete local files, and it does not replace this checkout with the cloud copy of the code.

Saved embeddings and other experiment outputs are under `gs://hushdev-748439071367-research/experiments/`. Virtualenvs are not in the bucket. Pull those outputs only when a training run needs them:

```bash
gcloud storage rsync gs://hushdev-748439071367-research/experiments ./experiments --recursive
```

The monitor:

```bash
cd apps/monitor
npm install
```

The desk, from the repo root:

```bash
./scripts/desk engine
./scripts/desk ui
```

Open http://127.0.0.1:3010/. The engine stays up if the page reloads. A new recording uploads closed chunks to `gs://hushdev-748439071367-research/live/`. The chunk still being written stays local.

## Where to read next

| Question | File |
| --- | --- |
| What may be claimed | `docs/ohush/swarm/RESEARCH_CONTRACT.md` |
| What has been scored | `docs/ohush/swarm/SCOREBOARD.md` |
| How a run is scored | `docs/ohush/research/ACCURACY_LADDER_001/KPI.md` |
| What was decided through the locked return | `docs/ohush/research/ACCURACY_LADDER_001/NEXT_DECISION.md` |
| Latest measurement, the outro path | `docs/ohush/research/OUTRO_RETURN_001/REPORT.md` |
| Which sessions are labeled | `docs/ohush/dataset_handoff/STATUS.md` |
| How the live desk is operated | `ohush_live/README.md` |
