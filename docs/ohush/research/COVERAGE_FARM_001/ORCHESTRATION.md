# Three farm operations

```text
1 RECORD  →  2 LABEL (Ollama)  →  3 HUMAN (only if gated)
     ↑ always save                     ↑ intervals

Scheduled:  farm loop  (every 15 min)
```

## Autonomous loop (preferred)

**Command:** `python -m tools.windows_lab farm loop`

One pass:

1. If capture lock held → exit (no Ollama during record; no second take)
2. Memory gate — skip record if free RAM &lt; 4 GB; hold 2nd instance until ≥8 GB + own VB-Cable
3. `label --tick` every **other** idle pass only; unload qwen after drafting (`ollama stop`)
4. Human gate → `indexes/farm_human_needed.flag` only when required
5. Refresh capture plan + retain package index (B2 dry-run until rclone remote exists)
6. Chrome peek (tap center) for channel guess → else `ON_AIR_CONTINUE`
7. If healthy → **record on-air** (ADB stills; OK minimized). Lag critical → 10 min chunks

Install Task Scheduler (every 15 min):

```powershell
python -m tools.windows_lab farm loop install-task --register
# script: C:\OHushData\farm\register_farm_loop.ps1
```

Probe only: `python -m tools.windows_lab farm loop health`  
Schedule: `python -m tools.windows_lab farm loop schedule`

### Day / night split (measured)

| Window (ET) | Mode | Behavior |
|---|---|---|
| **06:00–24:00** | `day_capture` | Prefer on-air record; light label every other idle pass (~20 clips) |
| **00:00–06:00** | `overnight_label` | **No new record**; burn Ollama backlog (~80 clips/pass) |

Cost on this box: **~7 s/clip** (qwen2.5:14b). A 20‑min take @ 60 s clips ≈ **2.3 min** to draft. Six overnight hours ≈ **~3000 clips** capacity — far above daytime intake from one streamer.

## 1 — Autonomous recording

**Command:** `python -m tools.windows_lab farm record`

- Hierarchy by daypart / DOW (locals any US DMA anytime)
- Live windows from the guide calendar (TNF/Sun/Mon/Sat CFB) preempt fill
- Coverage gaps decide priority
- Ready instances (distinct loopbacks) get assignments — **≤2**; Streamers lags even on one
- Tune with **fresh** UI dump after the picture settles (lag makes dumps stale); record `av` @ 1 fps stills
- Stills are **ADB framebuffer** (not gdigrab) — OK if BlueStacks is minimized, resized, or not front-center
- `streamers_lag` on the dashboard scores recent takes (window loss, short still yield, early end)

## 2 — Autonomous labeling (open source)

**Command:** `python -m tools.windows_lab farm label --tick`

- Import `authorized_sources/streamers_*` → `work/capture/streamers/` takes (`farm import`)
- Prepare takes → `timeline_facts.jsonl` (retain audio+JSON; no video on B2)
- Whisper + `qwen2.5:14b` drafts
- Auto-accept only clear `paid_ad`
- **Behind tracker:** `takes_unprepared`, `draft_review_asks`, `level`

```powershell
python -m tools.windows_lab farm label          # how far behind
python -m tools.windows_lab farm label --tick   # do a labeling pass
```

## 3 — Human in the loop (only when required)

**Command:** `python -m tools.windows_lab farm human`

- `required=false` → do nothing
- `required=true` → open http://127.0.0.1:3010/farm and grab-label until backlog is ok
- Gate opens on warn/critical backlog or when you see Ollama failing

## Dashboard

```powershell
python -m tools.windows_lab farm status
# or: python -m tools.windows_lab farm
```

Writes `C:\OHushData\indexes\farm_orchestrate.json`.
