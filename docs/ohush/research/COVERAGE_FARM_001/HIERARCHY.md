# Capture + label hierarchy

Clock is **US/Eastern** for planning. Streamers can open **any US local (any DMA) anytime** — use that to stretch dayparts (e.g. LA morning show while ET is afternoon; West Coast late news after ET midnight).

Farm corpus stays separate from sealed football optical gold.

## Always first: live preempt

Only when a **real** game/event is on air (picture + audio). Empty NFL/NCAA numbered rows are not content.

| When (ET) | What |
|---|---|
| Thu ~20:00–23:30 | TNF / football feeds if live |
| Sat ~11:00–23:30 | College football if live |
| Sun ~12:00–23:30 | NFL window if live |
| Mon ~20:00–23:45 | MNF if live |

Spare instances during live: still fill **main linear / news** on the other cable.

## Fill order by daypart (no live)

### Weekdays (Mon–Fri)

| Daypart (ET) | Record in this order | What that means on Streamers |
|---|---|---|
| **Morning** 05–12 | 1 main_linear → 2 main_news → 3 fast → 4 aux_sports → 5 talk | Big-DMA ABC/CBS/NBC/FOX morning shows; NBC News NOW / CBS News 24/7; Pluto/Roku filler; sports only if studio/live |
| **Afternoon** 12–17 | 1 main_linear → 2 main_news → 3 talk → 4 fast → 5 aux_sports | Network daytime on locals (talk/court/soaps = ordinary ad pods); news; entertainment; FAST; sports if live |
| **Primetime** 17–23 | 1 main_linear → 2 aux_sports → 3 main_news → 4 fast → 5 talk | Network primetime on locals (how people watch); sports nets if live/studio; news; FAST |
| **Late** 23–05 | 1 main_linear → 2 main_news → 3 fast → 4 talk → 5 aux_sports | Late local news — prefer West Coast DMAs while they’re still in late-news; national news; FAST |

### Weekend (Sat–Sun)

Same live preempt. When not live:

| Daypart | Order |
|---|---|
| Morning | main_linear → main_news → aux_sports → fast → talk |
| Afternoon / Primetime | aux_sports → main_linear → main_news → fast → talk |
| Late | main_news → main_linear → fast → aux_sports → talk |

## Local markets (rotate)

Any US DMA is legal fuel. Prefer, in order:

1. New York  
2. Los Angeles  
3. Chicago  
4. Dallas–Fort Worth  
5. Atlanta  
6. Philadelphia / Houston / Boston / SF / DC  

Open via **US ABC / CBS / NBC / FOX SECTION** groups (search for `ABC`/`FOX` returns movies first).

## Stills rate

**1 frame per second** (`--still-interval 1`, default). Farm `av` rejects sparser intervals. Dense stills live under `stills/still_tNNNNN.N.jpg`. Densify an old probe with video:

```powershell
python -m tools.windows_lab farm densify-stills
```

## Labeling start → finish (after capture)

1. Session lands unlabeled in the catalog / streamers take folder.  
2. `farm seed-queue` (or next propose job) cuts review clips.  
3. `farm draft --model qwen2.5:14b` — Whisper + Ollama drafts.  
4. Auto-keep only clear high-confidence `paid_ad`.  
5. You open **http://127.0.0.1:3010/farm** — fix disagreements / `uncertain` first.  
6. Validate **main_linear** before grinding FAST volume.  
7. Board ticks validated minutes; agent re-plans gaps.

## Parallel instances

Instance A = #1 in fill order (usually a big-DMA local).  
Instance B = #2 (usually national news or the other network).  
Grow clean concurrent captures only with distinct loopbacks.

## Commands

```powershell
python -m tools.windows_lab farm hierarchy
python -m tools.windows_lab farm status
```
