# What to do with this packet

Read `STATUS.md` first. Then read the three reports in the order listed there. The tables, plots, and series next to each report are the artifacts those reports summarize. Do not treat a report sentence as stronger than the matching row in the csv or json.

This packet is the measurement record through 13 October 2026. It is not a request to retune a live muter, fit a threshold, or invent a detection rate.

## Clocks

`hush_20260909_213047` is September 9 NBC, Patriots at Seahawks. Times are the recording clock. Coverage is 0–9373 s.

`hush_20260913_210542` is September 13 NBC, Cowboys at Giants. Times are the recording clock. Coverage is 0–12600 s. Features end at 12480 s.

`hush_20260913_150934` is September 13 FOX, closed 0–7200 s, program note `redzone`, zero commercials. A capture hole after 7200 s is outside that range and was not scored.

`hush_20261008_205100` is Thursday 8 October on the captured-audio clock. It is not the live-engine clock. `run19` was not joined to `audio_0023.wav`. Do not score Thursday's mute log.

## Do not

- Relabel a closed range because a detector disagrees.
- Unseal `hush_20260917_205513` or `hush_20260920_200635`.
- Treat a distance series as a mute decision. No commercial-heard time was simulated.
- Fit a threshold on any recording in this packet and call it confirmation.
- Recommend deleting `.booth.json`. Booth audio is not in this zip. No identity correction was made.

## What a useful answer is

Say whether the inconclusive audio-signal result should send the next measurement to a shorter window on the same embedding, or whether some row in these artifacts contradicts that. Name the session, the clock, and the artifact file. Separate a frozen oracle snapshot from a causal one, and a score from a playback decision.
