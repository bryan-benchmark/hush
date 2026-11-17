# Capture capacity (lab → cloud)

Locked decisions (12 Nov 2026):

- **Lab now:** 1–2 Streamers on this Windows PC (measure VM SKUs from real load).
- **Object store:** **GCS Standard** for data we still iterate on (shadow, draft, gold, training). **Not** cold/archive class while in active use.
- **True cold later:** B2 or GCS Archive only after a session is fully processed and rarely read (VM-scale retain).
- **Accounts:** one Streamers/Salvation login, **cloned** across instances for now.
- **Labelers:** humans compensated with stock; gold stays thin and gated.
- **Mute:** not on the capture wire. Shadow labels only. Archive stays raw.

Farm corpus never merges into sealed optical football gold.

## Measured on this PC (TNF live take)

Host: Ryzen 7 7800X3D · 32 GB · RTX 4070 Super.

| Item | Observed |
|---|---|
| BlueStacks `HD-Player` RSS | ~2.5 GB |
| Capture Python RSS | ~0.3 GB |
| **Budget / stream** | **4 GB RAM · 2 vCPU** |
| Disk (`av` = WAV + 1 fps stills) | **~0.9 GB/hour** (~22 GB/day) |
| Clean concurrent here | **2–3** (re-measure; see probe) |
| Hard stop here | watch `streamers_lag` / UI dump latency — not a fixed cable limit |
| Audio isolation | **Process-PID loopback** (per `HD-Player`) — no extra cable/VB-Cable for a 3rd |

**2026-11-13 probe (75s, 3× HD-Player + process audio + UI dumps):** verdict `3_ok_this_run` — CPU mean/max **3.8 / 8%**, dump mean/max **1.5 / 2.0 s**, 0 dump failures, all 3 WAVs ok. That was light load (no triple gdigrab AV yet). Re-run under full `av` capture before treating 3 as day-to-day:

```powershell
python -m tools.windows_lab capacity-probe-3 --seconds 75 --instances Nougat32 Nougat32_1 Tiramisu64
```

Re-measure anytime:

```powershell
python -m tools.windows_lab farm capacity-probe
```

Writes `C:\OHushData\indexes\capacity_probe.jsonl`.

## Value order (24/7 fill)

1. **P0** Live sports (real guide card: TNF / Sun NFL / MNF / Sat CFB)  
2. **P1** Primetime big-DMA linear (ABC/CBS/NBC/FOX SECTION)  
3. **P2** News (national + West Coast late)  
4. **P3** Aux sports nets (ESPN…) when not empty slots  
5. **P4** FAST · **P5** talk/other  

**US locals are nationwide on purpose.** Streamers `US ABC/CBS/NBC/FOX SECTION` opens any US affiliate anytime — rotate NY/LA/CHI/DFW/ATL… so the corpus gets real market diversity (not one AK/WV filler). Tag takes with `network` + `market` + `call_letters`. West Coast DMAs extend morning/late windows after ET has moved on.

```powershell
python -m tools.windows_lab open local --network FOX
python -m tools.windows_lab open local --network ABC --market "Los Angeles"
python -m tools.windows_lab us-locals board
```

Search show/team first for sports cards. Empty `AMZN##` / “No event” = skip.

## Fleet vs hot (this PC)

| Layer | Rule |
|---|---|
| **Ready fleet** | Up to ~**10** `Nougat32` clones — same SKU, Salvation logged in, mostly powered off |
| **Hot concurrent** | Add **one at a time** via progressive-capacity until lag breaks; start at **2** |
| **Audio every take** | Process loopback of that instance’s `HD-Player` PID |
| **Retired** | `Tiramisu64` (Android 13) — disabled; do not use for capture. Clone Nougat instead. |

| Stream | Role | Audio |
|---|---|---|
| `Nougat32` | P0/P1 primary | Process loopback of that instance’s `HD-Player` PID |
| `Nougat32_1` … `_9` | Ready pool / fill when lag OK | Same PID loopback recipe |

**Capacity find (do this after clones exist):**

```powershell
# Full-AV ramp — stop when verdict is not N_ok
python -m tools.windows_lab progressive-capacity --step 1 --minutes 2
python -m tools.windows_lab progressive-capacity --step 2 --minutes 2
python -m tools.windows_lab progressive-capacity --step 3 --minutes 2
# …raise N only while lag stays ok
# Then: setx OHUSH_DESK_MAX_STREAMS <N_ok>
```

Clone recipe (Multi-Instance Manager): stop source → clone `Nougat32` → `Nougat32_2` … → boot → `instances discover` → `salvation status` (clone should already be logged in). Keep idle clones **stopped** so they do not burn RAM.

```powershell
python -m tools.windows_lab instances running
python -m tools.windows_lab instances stop --instance Tiramisu64   # or any engine
python -m tools.windows_lab instances stop --disabled              # all enabled=false
python -m tools.windows_lab instances launch --instance Nougat32_2
```

MZ-631M / MG248 are fine as speakers; capture does **not** depend on distinct device loopbacks. Bottleneck = **Streamers lag**, not cables.

Checklist: `C:\OHushData\farm\MULTI_INSTANCE_SETUP.md`

```powershell
python -m tools.windows_lab instances discover
python -m tools.windows_lab progressive-capacity --minutes 2
```

## Cloud VM SKU (from lab math)

| Streams / VM | vCPU | RAM | Disk I/O | Notes |
|---|---:|---:|---|---|
| 1 | 4 | 8 GB | ≥50 GB SSD | + OS headroom |
| 2 | 8 | 16 GB | ≥100 GB SSD | 2× Cable; watch Streamers lag |
| 3+ | — | — | — | Prefer another VM, not denser packing |

GPU not required for raw `av` capture. GPU/CPU boxes separate for overnight draft + shadow.

## Storage plane (access frequency first)

| Layer | Where | Class | What |
|---|---|---|---|
| **Hot local** | `C:\OHushData\authorized_sources` | Disk | Live + anything under active label/shadow this week |
| **Warm shared** | **GCS Standard** `gs://$OHUSH_RAW_BUCKET/farm/raw_sessions/` | Frequent access | Audited sessions we will re-read (models, labelers, VMs) |
| **Review clips** | crowd bucket / ohush.co | Standard | Small help clips for humans |
| **Cold archive** | B2 or GCS Archive | Infrequent | Only after gold+shadow done and reads go quiet |

Do **not** put working ML corpora on Nearline/Coldline/Archive — restore latency and early-delete fees fight the iteration loop.

```powershell
# dry-run — Standard class uploads only
python -m tools.windows_lab farm upload-gcs --session SESSION_ID
python -m tools.windows_lab farm upload-gcs --session SESSION_ID --execute
```

Env:

- `OHUSH_RAW_BUCKET` (default: same as `FARM_BUCKET` / crowd bucket)
- `FARM_BUCKET` / `CROWD_BUCKET` for help-clip sync (unchanged)
- Never set lifecycle→Archive on `farm/raw_sessions/` while that prefix is the active corpus

## Atomic loop

```text
GUIDE → OPEN shortcut → RECORD raw → AUDIT → GCS Standard (if shared/iterate)
 → SHADOW sidecar → DRAFT overnight → HUMAN (stock) gold → SCORE
 → cold archive only when reads go quiet
```

## 30-day lab goal (1–2 streams)

- **≥250 h** audited raw on GCS (1 stream) · stretch **400 h** if stream 2 stays healthy  
- Shadow 100% of uploaded hours with versioned `model_id`s (no mute)  
- Board: ≥30 validated human minutes in main_linear / main_news / fast, then grow gold  
