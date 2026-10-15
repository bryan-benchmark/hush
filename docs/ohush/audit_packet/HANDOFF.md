# OHush handoff — 13 October 2026

Paste `PROMPT_FOR_GPT.md` into ChatGPT with this zip. This file is the map. It is a status audit, not a claim that the live product works.

**scientific_authority: false** on every live-session file. Thursday night is `live_dev`. It is not a replication set and it must not be used to retune Exp001–005.

---

## 1. What OHush is

OHush tries to hear a television commercial break from the audio alone, cover it with something else on the Mac speakers, and bring the show back when the program returns.

```text
TV optical → USB (Cubilux SPDIF) → Mac
                ├─ WAV capture (untouched, 15-minute chunks)
                └─ live helper (Python) → Mac headphones
                     localhost monitor (Next.js, :3010)
```

Two layers exist, and they are not the same thing:

| Layer | Where | Job | Status |
|-------|--------|-----|--------|
| Research | `experiments/exp001`–`exp005`, `exp003b` | Prove which signals separate content from ads. Frozen specs. | Measured on one ESPN Monday Night Football game (14 Sep 2026). Departure is real. Return is not. Fusion was explicitly not built. |
| Live product | `ohush_live/` | Cover commercials during a real game on this Mac. | Ran Thursday 8 Oct 2026 (Buccaneers–Cowboys, Prime). Failed in specific, logged ways. A recovery experiment afterwards fixed lab reproductions of two of those bugs. It did **not** prove the night would have gone well. |

The product app (Firebase / GCP / a shipped client) is not built. The monitor is a local desk.

Git: branch `main`, one commit, `eedcb444c2546e06f6b3cea16dc2efb92b8d6506` (“Add OHush live desk, sports mute session, and gold backup trail.”). Almost everything since that commit, including the Thursday-night recovery, is an uncommitted dirty tree. Do not `reset` or `stash` it.

---

## 2. How a live decision is made

Three detector families can vote. Only two exist as processes.

| Family | Worker | What the score is | Live status |
|--------|--------|-------------------|-------------|
| Audio | `ohush_live/audio_worker.py` | PANNs CNN14 embedding distance from the previous ~180 s of *this* broadcast. Same checkpoint as Exp003 (`Cnn14_mAP=0.431.pth`). Class head unused. | Running. `departure` and `return` are the **same number**. High = sounds unlike the recent window. |
| Speaker | `ohush_live/speaker_worker.py` | Exp002-style online clusters, plus a trusted booth file `.booth.json`. | Running, but often null, and the booth file is unaudited. |
| Semantic | would be Exp005 (ASR + phrase / vocabulary / embedding) | — | **Never started.** Every one of 5,368 Thursday track rows has `semantic: null`. |

`ohush_live/state.py` `Machine` is asymmetric: leaving the show (mute / cover) and coming back (play) use different bars. `ohush_live/sports_daemon.py` applies that decision to the Mac output. Auto was on for the entire Thursday track.

Current product thresholds (`ohush_live/policy.py`). These are **not** Exp001–005 constants. They also are **not** the thresholds that were live for the whole game — the engine was edited and restarted during the broadcast. See §5.

| Constant | Current value | Meaning |
|----------|---------------|---------|
| `AUDIO_STRONG` | 0.22 | Audio distance high enough to count as “this is not the recent program.” |
| `AUDIO_RETURN` | 0.12 | Same distance, low enough to count as “sounds like the recent window again.” |
| `AUDIO_MIN_REFERENCE_S` | 15 | Live warm-up. Exp003 stays at 60 s and was not changed. |
| `MIN_AGREE` | 2 | If two families are alive, both must agree. |
| `SOLO_MUTE_PERSIST_S` | 4.0 | One live family (audio only) may cover, but must hold this long. |
| `MUTE_PERSIST_S` | 2.5 | Persist when two families agree. |
| `MIN_MUTE_HOLD_S` | 6.0 | After a cover, don’t uncover before this unless a verified booth voice is heard. |
| `BOOTH_RETURN_PERSIST_S` | 0.0 | Verified booth speech uncovers immediately. |
| `BOOTH_HOLD_S` | 8.0 | After the last verified booth line, keep a short outro hold. |
| `SPEAKER_BOOTH_MATCH` | 0.55 | Cosine bar for “this cluster is a trusted announcer.” |
| `SPEAKER_DROP` / `SPEAKER_RETURN` | 0.35 / 0.25 | Exp002-shaped speaker bars. |

Quorum rule now in the working tree: a missing family is “unavailable,” not a vote of no. Knowing announcer identities (`booth_locked`) must not by itself block a cover. A live verified announcer still blocks a cover and still uncovers immediately.

---

## 3. Research already finished (do not reopen these specs)

All of Exp001–Exp005 and Exp003b were scored on **one** recording: `hush_20260914_212529`, ESPN Monday Night Football, 0–6899 s, 14 Sep 2026. A result there is development, not confirmation. The written next measurement was blind replication on three *other* sessions (Prime football, linear scripted, ad-supported streaming scripted). That replication was not what Thursday was. Thursday was a product session.

### Exp001 — low-level acoustic boundaries

**Partial / negative** as a standalone detector. `euclid_60` peaks about every 4 seconds. 99% of the timeline is already within 10 s of a peak, so every commercial boundary has a nearby peak and so does the game. 1,363 of 1,488 local maxima sit more than 10 s from any boundary. Keep as supporting evidence. Do not tune.

### Exp002 — speakers

**Closed. Strong for departure. Negative for return.**

Of 13 evaluable commercial starts, 12 show the frozen continuity collapse within 15 s (median latency 9.6 s). Collapses are ~6.6× denser inside pods than during programming, and still too common to mute on (about 4.2 per program hour).

“Recurring speaker” is not “program speaker.” On that ESPN game, `c0001` is ~2,161 s of speech and ~4 s inside ads. Other recurring clusters (`c0009`, `c0011`, `c0042`) are almost entirely inside ads. The useful idea is narrower: a few dominant voices belong to the booth, and a break removes them. The frozen return rule (recurring voice absent ≥30 s, then back) did not earn a place: it fires during ordinary play all the time, because football pauses.

### Exp003 — adaptive audio world (PANNs CNN14)

**Closed. Strong for departure. Negative for return with the adaptive reference.**

All 15 starts have a higher median distance in the 30 s after the start than in the 30 s before. Pod median distance 0.213, program median 0.092. Top peaks are specific enough to keep; they are not specific enough to mute on alone.

Return fails for a structural reason: the reference is the previous 180 s, so a long pod becomes the new normal. The score relaxes *during the ads*. A later drop can be a new spot, the pod settling, or the game coming back. On 11 of 14 complete ends, the post-end median is flat or lower. This was not turned into a PLAY rule.

### Exp003b — freeze the pre-break cloud

**Measured, not closed.** Trigger: distance above the 99th percentile of the prior 10 minutes, on 3 of 5 consecutive seconds, after 5 minutes of history, then a 60 s refractory.

6 of 14 eligible starts freeze within 60 s. Two freezes fall just after a pod, not in the middle of play. Where a snapshot exists, frozen distance separates pods from later play better than the adaptive score (median 0.289 inside pods vs 0.091 outside). Several pods have already relaxed on the adaptive score by the last 30 s while the frozen distance is still high (examples: adaptive 0.21 / frozen 0.37; 0.16 / 0.32; 0.13 / 0.34).

The 99th-percentile trigger is not how a break should be started. The useful object is the frozen cloud as memory. Return to that snapshot was not an unmute event. No return threshold was fit.

### Exp004 — commercial clock

**Negative** for a precise 15/30/60 or 60/90/120 clock. Pods loosely pile near two minutes (11 of 14 complete pods between 110 and 140 s). That is a weak prior, not a boundary detector.

### Exp005 — language

**005A** departure phrases: negative. They fire on football words (“coming up,” “timeout”). Exact “welcome back” is a rare, specific return corroborator (3 of 15 ends) and also happens twice during play.

**005B** ad vocabulary: ~6× denser in pods, too sparse to mark a pod (47 hits all game).

**005C** semantic continuity: same shape as Exp003. 14 of 15 starts depart. Frozen semantic distance stays high during the pod. Return is partial and often late (about 18–86 s to touch the snapshot). There is no operational, blind way to choose that snapshot yet.

### What the research said to do next

Feature discovery on the ESPN game stops. Do not invent Exp006 from it. Do not fuse yet. Replicate, unchanged and blind, Exp002, Exp003, Exp003b, and Exp005 on three new sessions. The question on each is whether the program grows a speaker world, an audio world, and a semantic world; whether a pod removes them; whether a frozen identity stays distinct during the pod; and whether that identity comes back after.

Thursday night did not answer that question. It asked a product question with a half-built fusion: mute on adaptive audio, sometimes alone, and unmute on booth heuristics.

---

## 4. Thursday 8 Oct 2026 — Buccaneers vs Cowboys

| Item | Value |
|------|--------|
| Session id | `ohush_live/sessions/2026-10-08-tnf` |
| Show string | `bucs cowbows 5` (spelling as logged) |
| Service | Prime Video, TV optical, live |
| Input device | `Cubilux SPDIF ReceiverSolid ` (trailing space is part of the name) |
| Output | External Headphones |
| Product tag in the logs | `OHUSH_LIVE_V0_SPORTS` |
| Frozen copy | `docs/ohush/experiments/LIVE_RECOVERY_001/inputs/session_2026-10-08-tnf/` |
| WAV | 25 files, 904,864,844 bytes, ~0.905 GB. **Not in this zip.** Inventory + sha256 are. Odd-numbered chunk names (`audio_0001.wav`, `audio_0003.wav`, …) because of overlapping open-chunk recording. |
| Track | 5,368 rows, **32 engine runs**, clocks reset every restart. Sum of run spans ≈ 6,045 s. Do not merge runs. |
| Decisions | 177 rows. 85 are state transitions; 76 are bed changes (`event: replacement`); 16 are `return_hint`. |
| Human overrides | 130 (`overrides.jsonl`), many of them bed-switching (`sound_stadium`, `sound_rain`, `sound_hush`, …) rather than mute/play. |
| Ratings | `ratings.jsonl` is **empty**. Vibes were not scored. |
| Labels | 58 `label_fix` rows. Point markers. **Not interval gold.** |
| Booth file | `.booth.json` trusted ids: `c0001`, `c0002`, `c0015`, `c0017`. Not listened through. Not proven to be announcers rather than ad narrators. |
| Upload | One manifest line. Closed chunks were meant to upload to `gs://hushdev-748439071367-research/live/`. |

Reserved split, written before any interval gold exists (`gold-manifest.json`): track `run00`–`run24` are development; `run25`–`run31` are held out. Do not tune on 25–31 once gold exists. The split is by engine run, not by random seconds.

### 4.1 The night was many nights

The engine was restarted 32 times. Early runs and late runs are different programs. A single false-negative percentage for “Thursday” would mix:

- a cold start with no speaker and no solo-audio path,
- a middle stretch where solo audio started covering at a low threshold,
- a late stretch where a remembered booth both blocked covers and instantly uncovered ads.

| Track runs | What the rows show |
|------------|--------------------|
| `run00`–`run19` | Speaker almost never in speech. `booth_locked` is 0. Audio is alive after warm-up and often ≥ 0.22 (run00 max 0.35, run08 max 0.42, run11 max 0.43, run19 max 0.35) while the machine sits in PLAY for long stretches. This is the “audio sees the break, nobody covers” regime. |
| `run20`–`run23` | Speech appears (run21: 1,163 s, 897 speech rows, 597 `booth_present`) but `booth_locked` is still 0. Run21 is the longest single clock. |
| `run24`–`run31` | `booth_locked` turns on. Run25: 311 s, locked on all 236 rows, **zero speech**, audio ≥ 0.22 on 32 rows, machine stays PLAY. Run29: 779 s, locked the whole way, 676 speech rows, 661 `booth_present`, audio max 0.447. This is the veto / false-return regime. |

Semantic is null on all 5,368 rows. Speaker is null on 1,890 rows (~35%). Audio is null on 148 rows (warm-up and a few short restarts). Auto is true on every row.

Hearing roughly tracks the machine: 3,726 rows PROGRAM/PLAY, 1,642 rows REPLACEMENT/MUTED. That is “what the Mac was playing,” not “what fraction of commercials were caught.”

### 4.2 Early failure — auto never covered (written up in `MISS_REVIEW.txt`)

Two human-caught ads in the first long attempt:

| | About | Human mute | Scores at the mute |
|--|-------|------------|--------------------|
| Ad 1 | t ≈ 23.1 s | t = 23.85 | audio null, speaker null |
| Ad 2 | t ≈ 379.6 s | t = 380.16 | audio **0.2725** (strong), speaker null |

Zero automatic `PROGRAM_TO_REPLACEMENT` in that attempt.

How it failed:

1. **Startup blindness.** The audio worker needs a reference window before it can score. With the Exp003 warm-up (60 s) plus a 10 s window, the first scoreable second is ~80 s offline, and later ~35–36 s even with the live 15 s warm-up. An ad at 23 s is structurally invisible. Every family was null, so the vote count was 0.
2. **`MIN_AGREE = 2` with one live family.** At Ad 2 the audio distance was already strong and the speaker score was null. Semantic was not running. Two votes were required, so one strong family could not cover.
3. **Speaker vote absent for long stretches.** The worker clears on non-speech. A cluster becomes “recurring” only after `RECUR_MIN_SPAN_S = 60`. Sports and ad speech leave `speaker = null`, so the second vote never arrives.
4. **Semantic is a stub.** The family key exists. No `semantic_worker` is spawned.

A later miss the same evening, after a solo-audio path had been added: auto still did not fire because program audio peaked around **0.167** and `AUDIO_STRONG` was **0.18**. The note in `MISS_REVIEW.txt` says the following product change was then shipped: `AUDIO_STRONG = 0.14`, live min-reference 15 s, solo mute persist 2 s, and the machine reads the raw audio score. Exp001–005 were not touched.

### 4.3 Middle failure — solo audio started covering, and the human often undid it

Across the whole decision log (clocks reset; these are not one timeline):

| Transition | Count |
|------------|------:|
| Human cover (`PROGRAM_TO_REPLACEMENT`, human) | 30 |
| Human show (`REPLACEMENT_TO_PROGRAM`, human) | 23 |
| Auto cover | 13 |
| Auto uncover | 19 |

Of the 30 human covers, 7 have null audio, 17 have audio distance ≥ 0.22, 20 have distance ≥ 0.14, and 3 are below 0.14. Speaker is null on 14 of the 30. The person was still covering breaks the machine was not taking.

The 13 auto covers and their logged audio distances:

`0.193, 0.145, 0.158, 0.154, 0.188, 0.186, 0.222, 0.155, 0.189, 0.214, 0.245, 0.256, 0.231`

Only **3 of 13** are ≥ the **current** `AUDIO_STRONG` of 0.22. The other 10 fired in the 0.14–0.22 band, which matches the evening’s lowered bar (`0.14`), not the file that is in `policy.py` today. Raising the bar to 0.22 would have refused those 10 auto-covers. Whether that is a fix or a new miss is **unknown**: there is no interval gold. Several of those auto-covers were undone by the human a few seconds later (decision segment 6: auto at 92 s, human show at 97 s; auto at 139 s, human show at 167 s; auto at 176 s, human show at 184 s). That pattern is “the machine covered and the person put the show back,” which is either a false cover or a return the machine would not take.

### 4.4 Late failure — the machine uncovered ads the person had just covered

This is the worst behavior in the log. Decision segment 12 (its own clock, t ≈ 169 s through t ≈ 621 s; **not** the same index as track `run12`) is a fight:

The person covers. About one second later the machine uncovers. The person covers again. Repeat.

Logged auto-uncovers in that segment, then the human re-cover:

| Auto uncover t | Audio distance (this field is the return-kind score, and for audio that is the same distance) | Speaker return score | Return votes | Human re-cover |
|----------------|-----------------------------------------------------------------------------------------------:|---------------------:|-------------:|----------------|
| 189.0 | 0.283 | 0.0 | 0 | (later, 220) |
| 221.0 | 0.234 | 0.0 | 0 | +2.6 s |
| 224.0 | 0.264 | 0.0 | 0 | +1.7 s |
| 226.0 | 0.251 | 0.0 | 0 | +1.1 s |
| 228.0 | 0.260 | 0.0 | 0 | +2.3 s |
| 231.0 | 0.258 | 0.0 | 0 | +1.5 s |
| 235.0 | 0.216 | 0.0 | 0 | +1.5 s |
| 237.0 | 0.232 | 0.0 | 0 | +1.4 s |
| 241.0 | 0.195 | 0.0 | 0 | +1.2 s |
| 262.0 | 0.190 | **1.0** | 1 | human at 284 |
| 285.0 | 0.115 | **1.0** | 2 | immediately after human cover at 284 |
| 599.0 | 0.345 | 0.0 | 0 | +1.9 s |
| 610.0 | 0.390 | 0.0 | 0 | +6.5 s |
| 618.0 | 0.317 | 0.0 | 0 | +2.7 s |
| 621.0 | 0.318 | **1.0** | 1 | immediately after human cover at 620.8 |

How this fails, in two different ways at once:

**False return while the ad is still loud in the embedding.** Audio distance 0.19–0.39 means “unlike the recent program.” `AUDIO_RETURN` is 0.12, so this audio is not a return. `return_votes` is 0, so no family has `strong_return`. The machine still goes to PLAY within about a second of a human mute. `Latch.allow_auto_play` ignores the vote count and always returns true (`ohush_live/sports.py`). Human mute is documented as a one-shot correction that “keeps hunting for program return” — it does not hold the cover. Combined with `BOOTH_RETURN_PERSIST_S = 0`, any booth-shaped reading uncovers on the next tick.

The logged `return_votes` field counts only `strong_return`. It does **not** include the daemon’s extra “booth is speaking” hint. A booth-driven uncover can log `return_votes: 0` and `speaker_score: 0.0` if the Exp002 return score was 0. That matches Defect B below: the old rule treated `recurring` or `continuity >= 0.12` as “the announcer is back.”

**Verified-looking booth voice uncovering an ad.** Rows with `speaker_score: 1.0` are the worker forcing the return score to 1 because `booth_present` was true. At t = 285 and t = 621 the machine uncovers in the same second the human covers, on a voice it believes is the booth, while (at 621) the audio distance is still 0.32. That is either a real announcer heard for a moment inside a break, or an ad narrator who has been learned as a booth identity. Research (Exp002) already showed recurring clusters that live inside ads. The trusted ids `c0001`, `c0002`, `c0015`, `c0017` were not auditioned. Defect D is this risk. It is plausible and not proven from the archive.

**Permanent booth veto, the other side of the same bug.** On the defect-peak code (the audit zip from that night, before the recovery), `booth_locked` meant “we know who the announcers are,” and the quorum treated that memory as if they were still talking. The daemon would also synthesize a speaker reading from stored ids when the worker was null. Result: commercial audio could be screaming (distance ≥ 0.22) and the machine stayed on PLAY. Track rows with that shape are concentrated in `run25` (32 such seconds under a simple definition) and `run29` (43). The recovery replay measured **88 s** of veto-shaped stuck PLAY under the broken policy.

### 4.5 What the human labels are, and are not

58 labels. Verdicts are `commercial` or `program`, each with an `about` time, a `hearing` (what the Mac was playing), and the replacement bed. They are button presses with resetting clocks.

- Commercial marked while hearing was still PROGRAM: the person believes an ad was playing and the Mac was not covering it.
- Program marked while hearing was REPLACEMENT: the person brought the show back, or believed the show was back while cover was still up.

`gold-manifest.json` says interval gold is **empty**. There are no `program_end` / `commercial_start` / `commercial_end` / `program_return` spans, and no outro/bumper tags. Do not compute recall or “commercial-heard time” from these points. Overrides (F8/F9) are control actions, not content boundaries. Decisions are system actions, not ground truth.

---

## 5. LIVE_RECOVERY_001 — what was tried after the game

Frozen 8 Oct 2026. Governing rule that was honored: no evidence, no promotion. Live output was not enabled as a promotion. The dirty tree was kept.

Three code identities matter. Do not mix them up.

| Snapshot | What it is |
|----------|------------|
| Git HEAD `eedcb44` | `baseline/code/`. No `booth_locked` veto. This commit is *before* the Thursday hardening. |
| Defect peak | `baseline/defect_peak/`, taken from `ohush_live_false_negative_audit_2026-10-08.zip`. This is the broken live policy: permanent `booth_locked` veto, `BOOTH_HOLD_S = 12`, synthetic speaker when the worker is null, `_booth_heard` accepting `recurring` or `continuity >= 0.12`. |
| Working tree now | The recovery candidates, sitting uncommitted in `ohush_live/`. |

Defects A–C are **not** in git HEAD. They were introduced in uncommitted live work on 8 Oct, then patched further the same night, which is why the track mixes policies.

### Defects

| ID | Name | Status | Mechanism | What the fix claims |
|----|------|--------|-----------|---------------------|
| A | Permanent booth veto | **PROVEN** | Quorum required speaker+audio, or blocked forever, whenever `booth_locked` or `_booth_still_talking`. Daemon could invent a speaker from ids. | Identity known ≠ speaking now. `booth_locked` alone cannot veto. Fixture `A_permanent_booth_veto`: broken code stays PLAY; candidate mutes `solo_audio_depart`. |
| B | False announcer return | **PROVEN on defect-peak** | `_booth_heard` accepted `recurring` or `continuity >= 0.12`, which uncovered with reason `booth_voice`. | Return requires speech plus a verified match (`booth_present` or similarity ≥ `SPEAKER_BOOTH_MATCH`). Fixture `B_false_booth_return`: candidate stays MUTED. Fixture `C_verified_booth_return`: a real verified booth voice still uncovers. |
| C | Synthetic / stale speaker | **PROVEN in defect-peak daemon** | `sports_daemon.tick` built a speaker reading from `_booth_ids` when `families["speaker"]` was null. | Working tree: quiet worker → `speaker = None`. Outro linger only after a verified `booth_present`. Worker-health enum is still not a first-class `/state` field. |
| D | Contaminated booth identities | **PLAUSIBLE** | Defect-peak worker auto-added top recurring clusters into the booth set and updated prototypes for any `booth_present` cluster. Exp002 already showed ad voices recur. | Trusted ids = `.booth.json` only. New voices go to `.booth_candidates.json`. Embeddings refresh only for ids already trusted. Existing `.booth.json` was **not** deleted and **not** auditioned. |
| E | Startup blindness | **PROVEN as a timing fact. Not repaired.** | First scoreable audio ~35–36 s with live 15 s reference + 10 s window. Ad 1 at ~23 s cannot be scored. | Deferred. No threshold was retuned to hide it. |

### Candidates

| Candidate | What was run | Result | What it does not show |
|-----------|--------------|--------|------------------------|
| C1 booth semantics | Synthetic fixtures + Mode A decision replay of the frozen track through the Machine. No torch re-run. | **PASS.** Veto-shaped stuck PLAY **88 s → 11 s**. Mute events 22 → 26. Deterministic on repeat. Safety fixtures still protect a verified booth and a bounded outro. | Real-world precision/recall. The remaining 11 s are often `booth_present` outro linger, not zero. |
| C2 verified return | Bundled in the same `state.py` as C1. | **PASS** on fixtures. Real-world false-return rate **UNPROVEN**. | Whether Thursday’s segment-12 flaps would actually stop on audio that was never re-scored. |
| C3 worker health | Code inspection. | **INCONCLUSIVE.** Synthetic injection is gone. Health is not an explicit state field. | — |
| C4 identity freeze | Code + quarantine file. | **PASS** for “no silent auto-promotion.” Purity of the four stored ids is **INCONCLUSIVE**. | Whether `c0001` / `c0002` / `c0015` / `c0017` are Al Michaels and Kirk Herbstreit or a Geico narrator. |
| C5 startup | Not run. | — | The 23-second ad is still invisible. |

Mode A replay feeds the **recorded** family dicts through a new Machine. It does not re-run PANNs or the speaker model. The recorded speaker fields were written by whatever daemon was live in that run, including the broken one. The report calls this out: Mode A families are partly polluted by live daemon fields from the mixed evening. A PASS here means “given those recorded features, the new quorum behaves better on veto-shaped frames.” It does not mean “we re-heard the game.”

Replay mute/play transitions that differ are listed in `candidates/C1_booth_semantics/metrics.json` and `diff.md`. Candidate-only covers include track run19 t≈307 and 586, run21 t≈39, 943, 958, run25 t≈117, run29 t≈158, 234, 613, all tagged `solo_audio_depart`. Candidate still emits `booth_voice` where the recording says a verified booth is present (run21 t≈948, run29 t≈216 / 262 / 620). Without interval gold those are logged, not scored.

Tests that lock the invariants: `tests/test_ohush_live_recovery.py`, `tests/test_ohush_live_state.py`.

### Deployment gates, as written in the recovery report

| Gate | Status |
|------|--------|
| Mode A replay | Ready |
| Held-out interval gold | **Not ready** (the interval list is `[]`) |
| Shadow mode (decide, but don’t change the speakers) | **Not built, not run** |
| Live validation | **Not authorized** |
| Rollback | Defect-peak is the broken snapshot. Git HEAD is the pre-veto commit. Keep C1 code under `candidates/C1_booth_semantics/code`. |

---

## 6. Where the working tree is today (13 Oct 2026)

The recovery conclusions are already edited into the live modules. They are not a separate branch, and they were not promoted through a shadow run.

In the tree now:

- `state.py`: `booth_locked` does not veto. Solo audio may cover when the speaker is null or not protecting the booth. Verified booth speech uncovers immediately and blocks solo-audio cover. Generic recurring/continuity does not.
- `sports_daemon.py`: does not invent a speaker when the worker is quiet. Outro hold starts only from verified `booth_present` and expires.
- `speaker_worker.py`: no top-N auto-promotion into `.booth.json`. Candidates quarantined. Prototype refresh only for trusted ids.
- `policy.py`: `AUDIO_STRONG = 0.22`, solo mute persist **4 s** (the evening note said 2 s and `AUDIO_STRONG = 0.14`). This raise is not scored against gold. It would have blocked 10 of the 13 logged auto-covers.
- Semantic worker: still absent.
- Startup: still blind for the first ~35 s.
- Frozen pre-break cloud from Exp003b: **not wired** into the live machine. Live return still uses the adaptive distance Exp003 already showed relaxes during a pod.
- Interval gold: empty.
- Vibe library (`VIBE_STARTER_001`): 10 CC0/Freesound beds, loudness-normalized, opt-in only via `OHUSH_VIBES_EXPERIMENT=1`. Default vibe “Wednesday Night.” Detection unchanged. Thursday ratings file is empty, so this experiment has no preference result.
- Identity probes: finished 13 Oct 2026. All 23 clips are answered. Read `DATASET_2026-10-13.md` and `identity_listen.json`. Those 18-second samples are not interval gold. They do say the 10 Sep Netflix file, the 10 Oct folder, and the 11 Oct folder are each more than one program.
- Monitor (`apps/monitor`): local Next desk. Uncommitted UI work (service icons, tips, sports dashboard) is presentation. It did not decide mute/play.

`Latch.allow_auto_play` still returns true unconditionally. A human cover still does not hold against the next booth-shaped tick.

---

## 7. What failed, in one chain

Research showed three departure signals (speaker collapse, adaptive audio distance, semantic distance) and showed that none of them is a safe unmute. The useful return object was a frozen picture of the program from before the break, plus a known booth voice, plus persistence. That object was never given a blind trigger.

The live product then:

1. Ran with semantic missing, so one of the three signals was gone.
2. Required two families to agree, so with speaker null it covered nothing (Ad 1, Ad 2).
3. Was patched mid-game so audio alone could cover. That caught some breaks and also covered things the human immediately uncovered. The threshold moved from 0.18 to 0.14 during the night and sits at 0.22 now, unscored.
4. Treated “we have stored announcer ids” as “an announcer is talking,” which blocked covers (Defect A, 88 s of veto-shaped stuck PLAY on replay).
5. Treated “a recurring / continuous voice” as “the show is back,” which uncovered ads in about a second, over and over, while the audio distance was still 0.2–0.4 (Defect B, decision segment 12).
6. May have learned ad narrators into `.booth.json` (Defect D, not proven).
7. Could not see anything in the first half-minute (Defect E, not fixed).
8. Restarted 32 times, so the log is several policies concatenated. Any audit that averages them will lie.

The recovery experiment reproduced A and B on fixtures, cut veto-shaped stuck PLAY from 88 s to 11 s on a replay that does not re-hear the audio, froze auto-promotion, and stopped. It did not build gold, did not run shadow, and did not authorize another live game.

---

## 8. Next steps, in the order that actually unblocks an audit

The recovery report’s own highest-leverage step, which is still undone:

1. **Build interval gold for 3–5 long Thursday runs** (development runs and, separately, the reserved held-out runs 25–31). Spans need `program_end`, `commercial_start`, `commercial_end`, `program_return`, plus outro / bumper tags. Point labels and F8/F9 are review candidates only. The WAVs are local (`ohush_live/sessions/2026-10-08-tnf/`, ~0.9 GB) and are recoverable; they were left out of the original audit zip and out of this one.

2. **Score two times, not a vibe:** commercial-heard time (ad audio that reached the headphones) and program-covered time (game audio that was replaced). Do it per engine run. Do not merge clocks. Report the policy identity of each run if it can be recovered from the desk log; otherwise treat early vs late runs as different systems.

3. **Only then** decide whether `AUDIO_STRONG` 0.14 vs 0.18 vs 0.22 is a real trade. Doing it before gold will just move the miss.

4. **Audition `.booth.json`.** Listen to exemplars of `c0001`, `c0002`, `c0015`, `c0017` from the Thursday WAVs and from the ESPN Exp002 excerpts. If an id is an ad voice, remove it. Auto-promotion is already frozen; that does not clean history.

5. **Candidate 5 — startup,** after gold, without a multi-threshold thrash. The first break of a broadcast is currently invisible. Pre-warm is the named fix. It is not a license to lower `AUDIO_STRONG` until the cold start is over.

6. **Shadow mode before the next live game.** Log the new Machine’s decisions against the live audio for a full broadcast while the Mac stays on the television audio unless the human covers. Do not let another Thursday be the test harness. 32 restarts made this log unusable as a single experiment.

7. **Do not wire a clever return on the adaptive distance.** Exp003 already failed that. The return hypothesis that survived is Exp003b’s frozen cloud, plus a verified booth voice, plus a few seconds of persistence, with uncertainty staying on PLAY (cover stays up when unsure). Exact “welcome back” can corroborate. None of those is an unmute by itself. The semantic worker is still the missing third family; starting it is a product choice, not a retune of Exp005.

8. **Leave Exp001–005 frozen.** Thursday is `live_dev`. The research workstream is now written in `DATASET_2026-10-13.md`: mark October Hulu, then the three unlabeled football nights (NBC, not Peacock). Prime and August Hulu gold are already closed. The cable scripted cell is still missing. The 10 Sep, 10 Oct, and 11 Oct files must be split before anyone labels them.

---

## 9. Questions an auditor should actually answer

1. Of the 13 auto-covers, which decision segments sit under the 0.14 bar versus the 0.22 bar, and which track runs do they correspond to? The segment index in `tnf_digest.json` is **not** the track run index. Joining them requires walking both files’ timestamp resets. Do that explicitly or refuse the join.
2. Decision segment 12’s 1-second uncover loop: which recorded speaker fields (`recurring`, `continuity`, `booth_present`, `similarity_to_booth`, `booth_locked`) are set on those ticks in `track.jsonl`? Mode A did not re-score this as a false-return rate. The fixtures did. The track can still confirm the mechanism if the fields are present.
3. Would C1/C2, replayed on segment 12’s recorded families, have stayed MUTED for those human covers? If the recorded `booth_present` is already true, C2 will still uncover, by design. That is the difference between “the heuristic was too loose” (fixed) and “the identity file is wrong” (not fixed).
4. Are the four trusted ids announcers? The embeddings are in `.booth.json`. The proof is listening, not cosine.
5. Is the remaining 11 s of veto-shaped stuck PLAY acceptable outro protection or still a miss? Only gold can say.
6. Does `Latch.allow_auto_play` returning true, plus `BOOTH_RETURN_PERSIST_S = 0`, recreate a one-second flap even after Defect B, whenever a true `booth_present` blips inside an ad?
7. What did the 32 restarts cost? Short runs (`run01`, `run05`, `run06`, `run09`, `run10`, `run12`, `run14`, `run16`, `run18`, `run20`, `run22`, `run24`, `run26`, `run27`, `run30`) are a few seconds to half a minute. They are restarts and bed checks, not football. Drop them from any coverage rate.

---

## 10. File map inside this packet

| Path | What it is |
|------|------------|
| `HANDOFF.md` | This document. |
| `PROMPT_FOR_GPT.md` | The message to paste with the zip. |
| `DATASET_2026-10-13.md` | Which recordings to mark, which to split, which gold is already closed. |
| `identity_listen.json` | All 23 probe answers joined to wall time. |
| `identity_probes/clips/` | The 18-second wavs those answers refer to. |
| `tnf_digest.json` | Per-run track stats and every non-noop state transition. Generated from the frozen logs. |
| `LIVE_RECOVERY_001/REPORT.md` | The recovery decision. Read this before disagreeing with it. |
| `LIVE_RECOVERY_001/00-baseline.md` | Code identity, environment, what metrics can and cannot prove. |
| `LIVE_RECOVERY_001/01-defect-audit.md` | Defects A–E with file-level mechanisms. |
| `LIVE_RECOVERY_001/gold-manifest.json` | Provisional. Intervals empty on purpose. |
| `LIVE_RECOVERY_001/candidates/C1_booth_semantics/` | Hypothesis, decision, failures, fixture metrics, replay metrics, replay decisions, code snapshot. |
| `LIVE_RECOVERY_001/candidates/C2_verified_return/` | Verified-return hypothesis and decision. Code snapshot. |
| `LIVE_RECOVERY_001/candidates/C4_identity_freeze/` | Identity-freeze hypothesis and decision. Code snapshot. |
| `LIVE_RECOVERY_001/baseline/defect_peak/` | The broken Thursday policy. |
| `LIVE_RECOVERY_001/baseline/code/` | Git HEAD product snapshot (no booth veto). |
| `LIVE_RECOVERY_001/inputs/session_2026-10-08-tnf/` | Frozen session json, labels, decisions, overrides, booth, MISS_REVIEW, track. |
| `LIVE_RECOVERY_001/inputs/wav_inventory.json` | Hashes and durations. Not the audio. |
| `research_results/EXP00*_RESULT.md` | Frozen research writeups. |

Not in the zip, on disk in the repo if you need them:

- `ohush_live/sessions/2026-10-08-tnf/*.wav` (~0.9 GB).
- Current `ohush_live/policy.py`, `state.py`, `sports_daemon.py`, `speaker_worker.py`, `audio_worker.py`.
- `tests/test_ohush_live_recovery.py`, `tests/test_ohush_live_state.py`, `tests/test_ohush_live_sports.py`.
- `experiments/exp001` … `exp005` numeric tables and plots (the result writeups are the verdicts).
- `ohush_live/vibes/` processed audio (gitignored).

---

## 11. Rules for anyone auditing this

- Do not retune Exp001–005 against Thursday or against the ESPN ledger.
- Do not report a commercial-recall percentage from `labels.jsonl`.
- Do not merge the 32 clocks.
- Do not describe C1 as “fixed Thursday.” It fixed a proven veto on fixtures and on a feature replay. Real-world false-return and real-world recall are unproven. Live use was not authorized.
- Do not delete `.booth.json` as part of speculation. Quarantine is already the rule; deletion needs a listen.
- The honest return design is still the one Exp005’s writeup named and did not build: enough of the old program comes back at once and stays back (frozen audio, frozen language, a known booth voice, persistence), and when that is uncertain the cover stays up.
