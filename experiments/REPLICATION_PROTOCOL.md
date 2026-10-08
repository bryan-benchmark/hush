# Replication protocol

Locked before any of the three new recordings. Feature discovery on `hush_20260914_212529` is finished. No new signal, no new threshold, and no Exp006 design comes from that game.

This ESPN session is development data. Matching its exact counts is not the success criterion.

## Where the project is

Four stages. The project is between 2 and 3.

| Stage | Status |
|---|---|
| 1. Discover useful signals | Done, on the ESPN game. |
| 2. Test those signals blindly on new data | Compute done and hashed. Evaluation is waiting on gold labels. |
| 3. Build the combined detector (Exp006) | Not started. It waits until Prime and the locked Hulu span have been scored. |
| 4. Stress-test, live use, hardware | Later. |

The new sessions have already been through the frozen pipeline. Speaker continuity, audio-world distance, the frozen cloud, ASR, phrase cues, ad vocabulary, and semantic distance exist, and they were hashed before any commercial truth. An unlabeled rate, such as freezes per hour, is not a performance number. It does not say whether a trigger landed on a commercial, on play, or on a return. Ground truth is the gate. More audio and another model are not.

Do not wait for the linear recording to label Prime and August Hulu. That recording is still the missing third cell. It does not block steps 1–4 below.

## What is frozen

| Spec | Role on a new session |
|---|---|
| `exp002-v1` | Blind. Speaker continuity, then the existing overlay. |
| `exp003-v1` | Blind. Adaptive audio-world distance, then the existing overlay. |
| `exp003b-v1` | Blind. The percentile freeze and both distance series. The pod comparison waits for labels. |
| `exp005-v1` | ASR, phrase cues, vocabulary hits, and the adaptive semantic distance are blind. |
| `exp001-v1`, `exp004-v1` | May be scored. They are not the replication question. |

Phrase lists, the 0.85 matcher, windows, hops, memory, percentiles, and models stay as written. A new session may change only the session id, the analysis span, and the output path. No per-genre threshold changes.

Holdouts stay sealed. The ESPN game is not reused as a replication slot. Two older dev sessions fill slots because the person who recorded them named the service. No other old session is substituted in.

## The one audit that is not a detector

Exp002, Exp003, and Exp003b can run blind. Exp005A and Exp005B can emit transcripts and cues blind. The adaptive Exp005C distance, the one that does not use a commercial start, can also be computed blind.

The frozen semantic snapshot cannot. On the ESPN game it was the mean of windows ending in (start−210 s, start−30 s], and the start came from the ledger. That showed the representation contains program-return information. It did not show that OHush can select the semantic memory operationally.

On each new session: generate and freeze the ASR and the semantic embeddings first. Run the known-start snapshot only after labels exist, and only inside the overlay. Do not use it to choose a freeze, a mute, or a PLAY.

## Locked slots

| Slot | Session | Status |
|---|---|---|
| Prime sports | `hush_20260924_220624` | Locked. Prime Video, Falcons at Packers. Analysis span 0–7600 s. The quiet tail starts at 7600 s and runs to the end of the file (7919.9 s). That cut is capture level, hashed before any commercial inspection. |
| Streaming scripted | `hush_20260827_135935` | Locked as ad-supported Hulu. Analysis span is session 300–7200 s (115 min). Identity probes: the first 45 s are not Gilmore Girls; probes at 5, 10, 15, 20, 30, 60, 90, and 120 min are. Output times are seconds since 300 s. |
| Streaming scripted (Oct capture) | `hush_20261007_220650` | Secondary. Hulu Gilmore Girls, identity written at capture. Span 20–11751 s, silence trimmed from level only. Unlabeled runs are finished and hashed. It does not replace the August cell. Label and score it after the primary Hulu overlay. |
| Linear scripted | none | Still missing. `hush_20260912_215850` is a 24/7 Rick and Morty stream with no commercials, so it does not fill this slot. |

One cable or antenna program, 60–120 minutes, with ordinary commercials, would fill linear scripted. The sealed holdouts stay sealed.

## The three recordings

| Slot | content_type | delivery | What it is |
|---|---|---|---|
| Prime sports | sports | streaming | `hush_20260924_220624`, Prime Video |
| Linear scripted | scripted | linear | One program, cable or antenna, ordinary commercials. Not recorded. |
| Streaming scripted | scripted | streaming | `hush_20260827_135935`, ad-supported Hulu, session 300–7200 s |

Aim for roughly 60–120 minutes of the program and several commercial breaks. Trim dead lead-in or tail from the capture notes before scoring. Do not choose the span by where the ads turned out to be.

## Secondary football check

Not a replication slot. Same frozen Exp002, Exp003, Exp003b, and Exp005, no tuning. The question is only whether the ESPN program-identity pattern was unique to that game. Delivery may stay unknown.

| Session | Span | Why this span |
|---|---|---|
| `hush_20260909_213047` | 0–9373.184 s | Full kept recording. |
| `hush_20260913_150934` | 0–7200 s | First continuous block. Chunks 9–14 were removed as flatline or digital silence, so 7200–12600 s is a hole. |
| `hush_20260913_210542` | 0–12480 s | Quiet tail from 12480 s to the file end, plus a removed silence chunk after 12600 s. |

Holdouts stay sealed. Do not add the other football hours unless these three fail in a way that is an obvious capture problem.

## Questions

Each cell is filled only after that session's labels exist. Until then it stays unknown.

| Question | Prime sports | Linear scripted | Streaming scripted |
|---|---|---|---|
| Exp002 speaker departure | ? | ? | ? |
| Exp003 audio-world departure | ? | ? | ? |
| Exp003b frozen audio stays unlike the pod | ? | ? | ? |
| Exp003b old audio identity returns | ? | ? | ? |
| 005A rare exact “welcome back” / “welcome back to” | ? | ? | ? |
| 005B ad-vocabulary enrichment | ? | ? | ? |
| 005C semantic departure | ? | ? | ? |
| 005C known-start semantic return audit | ? | ? | ? |

Generic “back to,” “timeout,” “coming up,” and “after this” stay off the success table. They did not earn a place as standalone evidence.

## Order for each recording

1. Capture, with identity already in `session.json`.
2. Run the unlabeled machinery. It must record `truth_ledger_read: false`.
3. Freeze the outputs and hash them.
4. Inspect unlabeled health only: the series exists across the declared span, nulls are the expected warmup, and the plots have no commercial shading. Do not hunt for breaks.
5. Label independently, under `experiments/gold/LABEL_POLICY_V1.md`. Listen. Do not use detector marks, and do not move a boundary onto a 15/30/60 grid.
6. Run the overlays already written. Same collars, same specs.

## What runs now

The unlabeled runs are finished and hashed. They are healthy frozen outputs, not replication results. Do not change thresholds from them. Do not fill the matrix from them.

Gold for the two primary cells is written, and hashed, before either cell's overlays are opened. A Prime overlay must not be in mind while the same person listens to Hulu.

```text
label Prime by ear → freeze that gold
label August Hulu by ear → freeze that gold
THEN inspect Prime overlays
THEN inspect Hulu overlays
THEN interpret those two primary results
```

`hush_20260827_135935`, session 300–7200 s, is the locked Hulu cell. `hush_20261007_220650` is a second Hulu Gilmore Girls capture. Identity was written at capture, and the span was cut on silence only. Nobody has listened through its 3.26 hours for a show change, so it does not replace the August cell. If it stays Gilmore Girls, it is a within-domain check after the primary Hulu overlay.

After those two overlays, the ladder is: October Hulu (same show and service, already hashed), then the three football files, then one linear scripted program, 60–120 minutes, one show, cable or antenna, ordinary commercials. The final matrix, and any Exp006 decision, wait until Prime, the locked Hulu span, and that linear show all have overlays. Exp006, if justified, weights whatever actually characterizes the program being watched. It is not designed from the ESPN game alone.

Unlabeled speaker drops are not breaks. Do not read them as commercial locations.

## What counts as replication

The same qualitative structure, not the ESPN fractions:

> The program establishes an identity. Ads replace it. A frozen copy of that identity stays distinguishable during the pod. The identity comes back after the break.

Scripted television may have many recurring voices rather than two announcers. That is the same mechanism. It does not have to look like football.

If that structure shows up in Prime sports, linear scripted, and streaming scripted, Exp006 fusion is justified, and it should weight whatever actually characterizes the program being watched. Until then, no fusion and no new detector.
