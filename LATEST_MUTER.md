# Latest muter — stop looking on GitHub

**There is no muter model file in this GitHub repo.**  
Clone/pull will never give you a `.pt` / `.pth` / “latest muter” release asset for the live desk.

The live system is **code in git** + **three outside assets**. Exact names and places:

| What people call it | Exact filename | Local path after install | Where it actually is |
| --- | --- | --- | --- |
| Audio family (CNN14) | `Cnn14_mAP=0.431.pth` | `experiments/exp003/models/Cnn14_mAP=0.431.pth` | Zenodo (not GitHub) |
| Enrolled-show return | `enroll_mnf.npy` / `enroll_snf.npy` / `enroll_tnf.npy` | `ohush_live/cache/enroll_*.npy` | GCS bucket (not GitHub) |
| Speaker ECAPA | `speechbrain/spkrec-ecapa-voxceleb` | `ohush_live/cache/spkrec-ecapa-voxceleb/` | Hugging Face on first launch |

Machine-readable copy of the same map: [`ohush_live/MODEL_MANIFEST.json`](ohush_live/MODEL_MANIFEST.json)  
Mac game-night steps: [`docs/ohush/MACBOOK_MNF_TONIGHT.md`](docs/ohush/MACBOOK_MNF_TONIGHT.md)

## Do not search GitHub for these strings

- `muter model`, `latest model`, `best model`, `mute.pt`, `muter.pth`
- `frame_mn10_strong_1.pt` — research stack only, **not** the live desk
- `frozen_head.pt` — research stack only, **not** the live desk

## Install the live assets (Mac)

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p ohush_live/cache experiments/exp003/models

# 1) enroll matrices (private GCS — requires gcloud on project hushdev)
gcloud config set project hushdev
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_mnf.npy ohush_live/cache/
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_snf.npy ohush_live/cache/
gcloud storage cp gs://hushdev-748439071367-research/enroll/enroll_tnf.npy ohush_live/cache/
# or: python scripts/restore_from_gcs.py

# 2) CNN14 (Zenodo)
curl -L -o "experiments/exp003/models/Cnn14_mAP=0.431.pth" \
  "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1"

# 3) ECAPA downloads itself on first speaker launch into ohush_live/cache/
```

## Prove you have the right files

```bash
test -f experiments/exp003/models/Cnn14_mAP=0.431.pth && echo cnn14_ok
shasum -a 256 experiments/exp003/models/Cnn14_mAP=0.431.pth
# expect: 0dc499e40e9761ef5ea061ffc77697697f277f6a960894903df3ada000e34b31

test -f ohush_live/cache/enroll_mnf.npy && echo enroll_mnf_ok
test -f ohush_live/cache/enroll_snf.npy && echo enroll_snf_ok
test -f ohush_live/cache/enroll_tnf.npy && echo enroll_tnf_ok
```

## What “live muter” actually means right now

- **Champion:** no authorized automatic mute that starts a cover.
- **Locked live:** enrolled-show return at **0.10** (`enroll_rolling_max`) — returns the game; does not start a cover.
- Engine: `ohush_live.sports_daemon` → http://127.0.0.1:8770/  
- UI: `apps/monitor` → http://127.0.0.1:3010/
