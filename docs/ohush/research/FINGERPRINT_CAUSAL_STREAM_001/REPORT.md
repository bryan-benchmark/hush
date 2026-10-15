# Fingerprint causal stream 001

Not a mute. The published reader, its decisions, the two counts, and the gold were not modified. Holdouts stayed sealed. Playback stays PLAY.

This reader carries the resampler, the high-pass filter, and the forward peak threshold across chunks. A peak is finalized only after a frozen number of later frames have arrived, and that backward pass uses exactly that many frames. The decision time is the last recording sample required to finalize the query, including the resampler guard.

First gate: **FAIL**.

## Baselines rechecked

Published `decisions.jsonl` is `08b1b8d9a56c33681b493dff1d3337951ac9a51b812c83d2e6009afdefb86713`. Count 10 on football remains 3903.2 commercial seconds covered, 432.1 program seconds, 72 incidents. Published read holes are 275.0 s. The warm replay's holes are 280.0 s. That extra 5.0 s is why a warm count-200 total can look 5 seconds higher. It is not an advertisement gained.

The two published count-200 covers are still in the file: score 272 at hush_20261008_205100 t=145 against hush_20260924_220624 at 234.244, and score 208 at hush_20261012_204200 t=5085 against hush_20260914_212529 at 6852.564.

## Horizon

On the first 180 seconds of `hush_20261011_135700`, the backward window was tried at 43, 86, 129, 172, 258, and 344 frames. That last value is 7.989 seconds. Interior hashes still disagreed at every step, including 258 against 344 (16,841 hashes against 16,619). The longest window was kept only so the chunk test had a fixed rule. A peak at that window is not final: more audio still changes it.

## Chunk test

`hush_20261011_135700` was read as 7-second pieces and as 45-, 90-, and 180-second chunks, with the resampler, high-pass, and forward threshold carried across the cuts. At the fixed 344-frame window, all four reads produced the same 556,154 hashes, the same ready-sample times, and the same self-match scores. None of these reads had a hole.

The chunk cut is no longer what moves the hash. The amount of audio after the peak still does.

## Ledger

The ledger below uses that 344-frame window. Each decision is stamped 8.005 seconds after the five-second query, which is when those frames have arrived. It is not stamped when the hash has stopped changing. Count 10 and count 200 were not refit. This is not the published fingerprint shifted later. The log floor is a running maximum, the buffer-wide mean is gone, and the backward pass sees 8 seconds rather than the rest of a 90-second block.

Football at count 10: 5,356.0 commercial seconds covered, 5,557.6 program seconds, 959 incidents, longest interruption 35.0 seconds. Premature let-go is 8,464.7 commercial seconds across 370 incidents. RedZone, separate, covers 285.1 program seconds and 56 incidents. Hulu October 7 covers 975.5 program seconds.

Football at count 200: 37.4 commercial seconds covered, 2.6 program seconds, 1 incident. That 2.6 seconds is on ESPN. Published count 200 covers no program.

This read left 155.0 football seconds unscorable (Prime 150.0, Sunday night 5.0). The published mask is 275.0, and the warm replay is 280.0. The commercial totals are not on the same mask. The higher commercial number is not an advertising gain, and the warm replay's extra 5.0 seconds at count 200 is not one either.

October recordings were already inspected. These figures are not a correction to the published 432.1.

## Controls

- hush_20261008_205100 t=145.0: causal score 289 against hush_20260924_220624 at 234.244. Published score 272 against hush_20260924_220624 at 234.244. Same pod: True. Decision at 158.005238, window end 150.0.
- hush_20261012_204200 t=5085.0: causal score 35 against hush_20260914_212529 at 6852.564. Published score 208 against hush_20260914_212529 at 6852.564. Same pod: True. Decision at 5098.00415, window end 5090.0.

## Prospective recording

No new recording was made. The acceptance bar below was written into the script before this ledger was scored. It applies only to audio recorded after this file, labeled without seeing these decisions. The two sealed holdouts are not that recording. October is not that recording. The afternoon tape used to find the block cut is not that recording.

On that recording, count 10 with this reader passes only if commercial seconds covered are at least 95 percent of the published count-10 reader on the same labels, program seconds and the longest interruption are both lower than that reader, and RedZone program seconds are not higher. If count 10 on that tape covers no program, the result is INCONCLUSIVE.

The first gate already decides this experiment. Chunk agreement passed. The gate fails because the hash was still changing at the longest window tested. A later recording is not opened on this reader.

## Command

```
.venv/bin/python experiments/measurement/fingerprint_causal_stream_001.py
```

PLAY. Universal v1 unchanged. Holdouts sealed. No deployment.
