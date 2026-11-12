# Lab → live → Mac realtime

Until the owner changes it: **Windows builds better muters; Mac tests them on the television as soon as they ship.**

| Machine | Job |
| --- | --- |
| **Windows lab** | Fit / score / KEEP on labeled tapes under `C:\OHushData\gpu_lab\` and `experiments/` |
| **This repo (`ohush_live`)** | The only prod muter. Wire the kept recipe here in the same effort |
| **Mac desk** | Pull, fetch weights, run `ohush_live` on optical TV audio in realtime |

## Loop (every kept win)

1. **Measure** on Windows (Prime/TNF tapes, sealed holdouts stay sealed).
2. **Ship into live** — same session as the KEEP:
   ```powershell
   .\.venv\Scripts\python.exe scripts/ship_live_muter.py
   # then wire code if the recipe changed (worker / controller / vetoes)
   git add ohush_live LATEST_MUTER.md ohush_live/MODEL_MANIFEST.json
   git commit -m "Ship live muter <short name> for Mac realtime."
   git push
   ```
3. **Mac pulls and runs**:
   ```bash
   git pull
   # follow LATEST_MUTER.md for any new weight fetch
   ./scripts/desk restart-engine   # or restart sports_daemon
   open http://127.0.0.1:3010/
   ```
4. **Realtime test** on the Mac: optical in, headphones out, Auto on, watch covers/returns. Log misses with desk buttons. Do not treat a GPU scoreboard row as the test.

## Rules

- A KEEP that never reaches `ohush_live` is unfinished.
- Prefer Mac CPU/MPS-capable paths. If CUDA-only, port or shrink before calling it shipped.
- Update `LATEST_MUTER.md` + `MODEL_MANIFEST.json` with **exact filenames**, SHA-256, and fetch URLs so Mac Cursor does not hunt GitHub for a mystery `mute.pt`.
- Holdouts stay sealed. Do not retune thresholds on game night.

## Current live cover starter

Acoustic kept stack: `research_audio_worker` (`frame_mn10` + `frozen_head` + 0.90/0.50 × 8/2). Details: [`LATEST_MUTER.md`](../../LATEST_MUTER.md).
