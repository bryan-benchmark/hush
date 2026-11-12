# Latest muter — what to install

**Home prod = live desk.** Kept accuracy wins ship into `ohush_live`. See `.cursor/rules/live-muter-prod.mdc`.

The **cover-starting** muter is now the kept research stack (acoustic path):

| Asset | Exact filename | Local path | Where to get it |
| --- | --- | --- | --- |
| Frame encoder | `frame_mn10_strong_1.pt` | `ohush_live/cache/research_muter/frame_mn10_strong_1.pt` | **GitHub release** (PretrainedSED) |
| Frozen GRU head | `frozen_head.pt` | `ohush_live/models/frozen_head.pt` | **In this git repo** |
| PretrainedSED code | `Frame_MN_wrapper.py` | `third_party/PretrainedSED/` | Clone / submodule with the repo |
| Enrolled-show return | `enroll_*.npy` | `ohush_live/cache/enroll_*.npy` | GCS `hushdev` |
| Speaker ECAPA | `spkrec-ecapa-voxceleb` | `ohush_live/cache/spkrec-ecapa-voxceleb/` | Hugging Face on first launch |
| CNN14 (fallback only) | `Cnn14_mAP=0.431.pth` | `experiments/exp003/models/` | Zenodo — used only if research assets missing |

Machine-readable: [`ohush_live/MODEL_MANIFEST.json`](ohush_live/MODEL_MANIFEST.json)

## Look for these exact names (Mac Cursor)

```
frame_mn10_strong_1.pt
frozen_head.pt
ohush_live/research_audio_worker.py
ohush_live/research_muter.py
third_party/PretrainedSED
```

Do **not** search for `mute.pt` / `muter.pth` / “latest muter model” as a single mystery file.

## Install (Mac)

```bash
cd "$(git rev-parse --show-toplevel)"
git checkout research/windows-lab-node-01
git pull
git submodule update --init --recursive   # if PretrainedSED is a submodule
# or ensure third_party/PretrainedSED exists with models/frame_mn/

mkdir -p ohush_live/cache/research_muter ohush_live/cache experiments/exp003/models

# 1) cover-start weights (THIS is the live muter encoder)
curl -L -o "ohush_live/cache/research_muter/frame_mn10_strong_1.pt" \
  "https://github.com/fschmid56/PretrainedSED/releases/download/v0.0.1/frame_mn10_strong_1.pt"
shasum -a 256 ohush_live/cache/research_muter/frame_mn10_strong_1.pt
# expect: 4a0fe320d5369987b772394c51881fb20a602967e6842f72f3e5c8181065ece7

# 2) frozen head is in git
test -f ohush_live/models/frozen_head.pt && echo head_ok
shasum -a 256 ohush_live/models/frozen_head.pt
# expect: 58b8ad09f2da60b519b05558935d25c9b79a20ef288b15838c337748abc20bf2

# 3) enroll matrices (return floor)
gcloud config set project hushdev
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_mnf.npy ohush_live/cache/
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_snf.npy ohush_live/cache/
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_tnf.npy ohush_live/cache/

# 4) torch + deps in the root venv
source .venv/bin/activate
python -m pip install -U torch torchaudio speechbrain silero-vad
```

## What plays live

- **Starts covers:** `research_audio_worker` — frame_mn10 + frozen head + 0.90/0.50 × 8/2 controller + 8s causal post-return play hold.
- **Returns game:** enrolled-show floor **0.10** + booth speech + controller return.
- **Not wired yet:** Clarissa/Whit/Palmer/Fitz cover-only voice vetoes (need portable prototypes + live Clarissa ad gate).

Engine: http://127.0.0.1:8770/ · UI: http://127.0.0.1:3010/  
`decision_mode` should read `research_stack` when assets are present.
