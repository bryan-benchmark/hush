# OHUSH_AD_DETECT_001 — Step 1

Question under test: is this second **advertising** or **programming**?  
Not under test: who is speaking.

## Logic

1. Gold already labels commercial vs program on these tapes.
2. The frozen tool is the NBC logistic on AST CLS embeddings, 10-second mean, line **0.1632588496059179**. Hot means “treat as advertising.”
3. Desired: commercial seconds hot, program seconds cold.
4. Speaker cosine is off. Open-set identity is a different ledger.
5. This step does **not** train a new head. It dumps raw scores on a fixed hard board plus a random control sample so we can see where the frozen tool already fails before changing anything.

## Hard board (box level)

| Board | Expect | Median mean10 | Hot fraction | Agrees gold | Verdict |
| --- | --- | ---: | ---: | ---: | --- |
| DraftKings (Thompson reading ad) | commercial | 5.429 | 1.00 | 1.00 | ok |
| FanDuel (unknown male) | commercial | 2.384 | 1.00 | 1.00 | ok |
| Wendy's (unknown female) | commercial | 3.418 | 1.00 | 1.00 | ok |
| Fitzpatrick pregame | program | 2.570 | 0.75 | 0.25 | **MISS — program scored hot** |
| Thompson postgame | program | 0.034 | 0.40 | 0.60 | ok |
| Whitworth (dropped pass) | program | −1.013 | 0.38 | 0.63 | ok |
| Sherman (same stretch) | program | 1.993 | 0.80 | 0.20 | **MISS — program scored hot** |

The three ads are not the problem for this score. The desk / sideline talk is.

## Random controls (sanity)

20 commercial + 20 program stamps per Prime tape, seed 0.

| Tape | Gold | Hot fraction | Agree fraction | Median mean10 |
| --- | --- | ---: | ---: | ---: |
| October | commercial | 1.00 | 1.00 | 4.694 |
| October | program | 0.00 | 1.00 | −6.141 |
| September | commercial | 0.95 | 0.95 | 3.982 |
| September | program | 0.10 | 0.90 | −3.843 |

Ordinary ad interiors and ordinary play still separate. The hard board does not.

## Raw stamps to review

### FanDuel ad (expect commercial) — all hot, gold commercial

| t | gold | mean10 | hot | top1 | Speech | Music |
| ---: | --- | ---: | --- | --- | ---: | ---: |
| 573.0 | commercial | 2.160 | yes | Music | 0.272 | 0.282 |
| 574.0 | commercial | 2.399 | yes | Speech | 0.298 | 0.211 |
| 575.0 | commercial | 2.384 | yes | Speech | 0.307 | 0.252 |
| 576.0 | commercial | 2.322 | yes | Speech | 0.280 | 0.262 |
| 577.0 | commercial | 2.795 | yes | Speech | 0.267 | 0.260 |

### Fitzpatrick desk (expect program) — mostly hot, gold program

First / mid / last stamps:

| t | gold | mean10 | hot | top1 | Speech | Music |
| ---: | --- | ---: | --- | --- | ---: | ---: |
| 6590.0 | program | −0.831 | no | Speech | 0.285 | 0.187 |
| 6595.0 | program | 3.000 | yes | Speech | 0.299 | 0.211 |
| 6598.0 | program | 4.158 | yes | Speech | 0.332 | 0.225 |
| 6604.0 | program | 2.746 | yes | Speech | 0.339 | 0.102 |
| 6609.0 | program | −1.173 | no | Speech | 0.330 | 0.103 |

Same Speech-led shape as FanDuel. The mean goes hot in the middle of the desk bit.

### Sherman (expect program) — mostly hot

Median mean10 1.993, hot 0.80. Gold program. This is the other miss class: talk that is not a pod but looks commercial to the mean.

## Files

| File | Contents |
| --- | --- |
| `step1_meta.json` | Logic, box verdicts, control summary |
| `step1_hard_seconds.jsonl` | Every stamp on the hard board |
| `step1_controls.jsonl` | Random control stamps |

## What Step 1 shows

The frozen commercial score **already finds the hard ads**. It **falsely heats** Fitzpatrick and Sherman. Speaker identity cannot fix that: FanDuel is unknown, Fitzpatrick is a broadcaster, and both can look hot.

## Step 2 — new audio-only heads

### Logic

1. Same job: advertising vs programming. Speaker unused.
2. Fit only on the two NBC games (21,400 labeled seconds). The Prime hard board is held out.
3. Each candidate is a logistic on audio features, then the same 10-second causal mean.
4. The start line for each new head is placed on NBC only: midpoint of commercial p10 and program p90 of that mean.
5. Heads:
   - `frozen_cls` — published reference
   - `class527` — logistic on 527 AudioSet class probabilities
   - `watch_seq` — watch classes plus 10s causal rolls of Speech / Music / Crowd / Jingle
   - `class527_hard` — `class527` with weight 5 on the 1,081 NBC program seconds the frozen mean already heats

### NBC line placement

| Head | Commercial p10 | Program p90 | Gap | Line |
| --- | ---: | ---: | ---: | ---: |
| frozen_cls | (published) | (published) | open on CLS | 0.163 |
| class527 | −0.051 | 0.832 | **−0.883** | 0.390 |
| watch_seq | −0.394 | 1.155 | **−1.549** | 0.380 |
| class527_hard | −0.326 | 0.538 | **−0.864** | 0.106 |

The new heads do not open a positive gap on NBC. Program p90 sits above commercial p10. The midpoint line is already a compromise inside overlapping mass.

### Hard board (held-out Prime)

| Board | Expect | frozen | class527 | watch_seq | class527_hard |
| --- | --- | --- | --- | --- | --- |
| DraftKings | ad | ok | ok | ok | ok |
| FanDuel | ad | ok | ok | ok | ok |
| Wendy's | ad | ok | ok | **MISS cold** | ok |
| Fitzpatrick | program | **MISS hot** | MISS hot | **ok cold** | MISS hot |
| Thompson postgame | program | ok | **MISS hot** | **MISS hot** | **MISS hot** |
| Whitworth | program | ok | ok | ok | ok |
| Sherman | program | **MISS hot** | MISS hot | MISS hot | MISS hot |

Net vs frozen on this board: **1 improvement, 4 regressions.**

`watch_seq` is the only head that cools Fitzpatrick (median 0.26, hot 0.40). It also freezes Wendy's (hot 0.00) and heats Thompson postgame (hot 1.00). Sherman stays hot. Upsampling NBC program-hot seconds (`class527_hard`) does not fix Fitzpatrick or Sherman and makes Thompson postgame worse.

### Raw medians (mean10)

| Board | frozen | class527 | watch_seq | class527_hard |
| --- | ---: | ---: | ---: | ---: |
| FanDuel | 2.384 | 0.882 | 0.607 | 0.548 |
| Fitzpatrick | 2.570 | 1.086 | 0.258 | 0.798 |
| Wendy's | 3.418 | 0.427 | 0.107 | 0.198 |
| Sherman | 1.993 | 0.520 | 0.350 | 0.439 |

### Step 2 verdict

No candidate beats the frozen CLS mean on this board. Sequence tags can trade one false mute for a missed ad. Class probabilities alone do not separate desk talk from short in-broadcast ads when fit only on NBC. Do not install any of these heads. Mute unchanged.

### Files

| File | Contents |
| --- | --- |
| `step2_meta.json` | Placements, box verdicts, compare-to-frozen |
| `step2_hard_seconds.jsonl` | Per-stamp scores for every head |

## Step 3 — pod vs desk when stage A is hot

### Logic

1. Stage A stays the frozen mean at 0.163. Unchanged.
2. Stage B fits only on NBC seconds that are already hot under A (5,661 commercial + 1,081 program).
3. B asks: commercial pod or false-hot program? Features are causal shape cues: mean10, raw, hot-run length, onset rise, hot stability, Speech/Music/Crowd/Jingle now and rolled 10s.
4. Final commercial = A hot AND B commercial.
5. Prime hard board held out. Speaker unused. Mute not installed.

### NBC fit

| | |
| --- | ---: |
| Hot seconds used | 6,742 |
| B line (midpoint) | 0.447 |
| Gap (commercial p10 − program p90) | −0.175 |
| Accuracy at 0.5 | 0.848 |
| Program reject at 0.5 | 0.884 |
| Commercial recall at 0.5 | 0.841 |

Largest |coef|: `music` −2.55, `speech_roll10` −2.17, `hot_stability` +1.68, `onset_rise` +1.07. On this NBC hot set, higher instantaneous music and rolled speech pull toward program; a rising / unstable hot onset pulls toward commercial. The sign pattern did not transfer cleanly to Prime FanDuel.

### Hard board

| Board | Expect | Stage A only | A∧B @0.45 | A∧B @0.5 |
| --- | --- | --- | --- | --- |
| DraftKings | ad | ok | ok (p≈0.96) | ok |
| FanDuel | ad | ok | **MISS cold** (p≈0.35) | **MISS cold** |
| Wendy's | ad | ok | **MISS cold** (p≈0.30) | **MISS cold** |
| Fitzpatrick | program | MISS hot | MISS hot | **ok cold** (barely) |
| Sherman | program | MISS hot | **ok cold** | **ok cold** |
| Thompson postgame | program | ok | ok | ok |
| Whitworth | program | ok | ok | ok |

Net vs stage A at 0.5: **2 improvements** (Fitzpatrick, Sherman), **2 regressions** (FanDuel, Wendy's). Midpoint is worse on ads and does not fully clear Fitzpatrick.

### Raw: FanDuel vs Fitzpatrick (threshold 0.5)

FanDuel stays stage-A hot, but B scores it like desk until the last stamp:

| t | A hot | B prob | hot_run | final |
| ---: | --- | ---: | ---: | --- |
| 573 | yes | 0.316 | 2 | no |
| 574 | yes | 0.363 | 3 | no |
| 575 | yes | 0.349 | 4 | no |
| 576 | yes | 0.240 | 5 | no |
| 577 | yes | 0.795 | 6 | yes |

Fitzpatrick mid-desk is A-hot and B often **higher** than FanDuel (0.68–0.83), so B does not veto the false mute in the middle of the bit. A duration gate (trust A until hot_run≥8) saves FanDuel but leaves Fitzpatrick/Sherman mostly hot again.

### Step 3 verdict

The second stage learns a real NBC distinction (hot commercial vs hot program) but **does not transfer** to Prime in-broadcast ads. FanDuel/Wendy’s look more like NBC false-hots than like NBC pods. Sherman can be cooled; short sportsbook reads get killed. Do not install. Mute unchanged.

### Files

| File | Contents |
| --- | --- |
| `step3_meta.json` | Placement, coefs, box verdicts |
| `step3_hard_seconds.jsonl` | Per-stamp A/B/final |

### Step 4 (expert next)

NBC pods are the wrong positive for in-broadcast ads. Either find NBC **in-break / embedded** commercial seconds as a separate positive class, or add a non-audio cue that desk and FanDuel do not share (scorebug / scene cut). Purely reweighting the same audio shape on NBC pods will keep swapping desk mutes for missed short ads.
