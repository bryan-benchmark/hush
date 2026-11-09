# MacBook Air — MNF tonight

Two different systems. Do not mix them.

| | **Live booth (tonight)** | **Research stack (lab)** |
|---|---|---|
| Code | `ohush_live.sports_daemon` | `frame_mn10` + frozen GRU + Clarissa/Whit/Palmer/Fitz |
| Device | MacBook Air CPU/MPS | Windows CUDA lab |
| Show cast | `mnf` → Buck + Aikman (`enroll_mnf.npy`) | TNF desk panel |
| Voice role | **Return floor 0.10 only** — does not start covers | Cover latch (research, not locked live) |

Tonight: run the **live booth** with show **Monday Night Football / mnf**. Do not expect TNF research-stack desk KPIs.

## Expected KPIs (from prior MNF tape)

Session `hush_20261012_204200` — full MNF, **TRAIN** for the frozen head (in-sample, optimistic). Thin ontology labels (almost no desk rows). Receipt: `C:\OHushData\gpu_lab\audio_learn\mnf_expect_1012\EXPECT.md`.

| cell | cool (frozen + cooldown_8s) |
|---|---:|
| non_broadcast coverage | **0.909** |
| broadcast_muted_s | **128** |
| desk_s (labeled) | **0** (labels thin — real desk FP sits in unlabeled_program ≈116s) |
| longest_false_mute_s | **48.75** |
| false_mute_episodes | 30 |

`hush_20261019_211721` is only ~26 min — skip as a KPI baseline.

**Realtime expectation on Mac:** ballpark coverage high on ads if the live audio+speaker gate behaves; desk false covers can still land ~1–2 minutes longest until Buck/Aikman return floor kicks in. This is **not** a prediction that live will match 0.909 — that number is research frozen on a train tape.

## Assets (GitHub alone is not enough)

GitHub has code + labels. **Not** in git:

| asset | where | size / note |
|---|---|---|
| `enroll_mnf.npy` (+ snf/tnf) | `gs://…/enroll/` | tiny; **required** for Buck/Aikman return |
| SpeechBrain ECAPA | Hugging Face on first speaker launch | ~85 MB |
| `Cnn14_mAP=0.431.pth` | Zenodo (see below) | **required** for audio family; without it audio worker stays unavailable |
| `recordings/` | GCS `raw/` | optional tonight (offline only) |

Bucket: `gs://hushdev-748439071367-research` (project `hushdev`).

## Mac setup (once)

```bash
git clone --recurse-submodules git@github.com:bryan-benchmark/hush.git
cd hush
# use the branch that has the desk you want tonight
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install -e .
# live workers (not all in root requirements.txt)
python -m pip install torch speechbrain silero-vad panns-inference
gcloud auth login
gcloud config set project hushdev

# 1) enroll matrices (thin pull — skip full recordings for game night)
mkdir -p ohush_live/cache experiments/exp003/models
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_mnf.npy ohush_live/cache/
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_snf.npy ohush_live/cache/
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_tnf.npy ohush_live/cache/
# or: python scripts/restore_from_gcs.py

# 2) audio CNN14 (Zenodo; same file live audio_worker expects)
curl -L -o "experiments/exp003/models/Cnn14_mAP=0.431.pth" \
  "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1"

cd apps/monitor && npm install && cd ../..
```

Beds: soft covers are generated in `ohush_live/sounds.py` (no download). Mixkit stadium/rain optional.

**Sanity before kickoff:**

```bash
test -f ohush_live/cache/enroll_mnf.npy && echo enroll_ok
test -f experiments/exp003/models/Cnn14_mAP=0.431.pth && echo cnn14_ok
.venv/bin/python -c "import speechbrain,silero_vad,torch,panns_inference; print('py_ok')"
```

## Game night

1. TV speakers down. Optical → USB capture. Headphones on the Mac.
2. Preflight:

```bash
source .venv/bin/activate
.venv/bin/python -m ohush_live.sports_daemon --preflight --input-device USB --output-device "External Headphones"
```

3. Split desk:

```bash
./scripts/desk engine
./scripts/desk ui
```

4. Open http://127.0.0.1:3010/ → show **Monday Night Football** / service ESPN → Start.

5. First launch downloads ECAPA into `ohush_live/cache` (needs network once).

6. Hotkeys in the engine terminal: F8 mute, F9 play, F10 auto.

## What to watch live (realtime test)

- Longest cover before return
- Whether Buck/Aikman enroll_rolling_max ≥ 0.10 clears return
- Missed ads vs muted show (buttons on the desk — reports, not gold)

Do **not** lock the TNF Clarissa/Whit/Palmer/Fitz cover latch into this Mac engine tonight.
