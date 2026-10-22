# Research contract

Status: active. This file is the shared interface for the four workstreams. It does not authorize a mute policy, a live change, or a claim of 99.99% accuracy.

## Mission

Measure automatic commercial start and end detection on NFL broadcasts, then on other programming. The research target is 99.99% correct treatment of audible programming versus advertising. That target is a north star. It is not a product claim.

99.99% of a three-hour game is 1.08 seconds of total incorrectly treated audio. 99.99% of the current 85,076.4-second closed corpus is 8.51 seconds. About 31 hours of closed audio cannot certify either number.

## Lanes

| Lane | Question | Directory |
| --- | --- | --- |
| A | What makes a commercial handoff acoustically different from a football edit? | `docs/ohush/swarm/AGENT_A_AUDIO_FORENSICS/` |
| B | When does the broadcast have a real opportunity to leave the game? | `docs/ohush/swarm/AGENT_B_BROADCAST_CONTEXT/` |
| C | Can the content be identified, rather than scored as unusual? | `docs/ohush/swarm/AGENT_C_CONTENT_IDENTITY/` |
| D | Which result reduces heard advertising without hiding the game, on another broadcast? | this directory |

A, B, and C write only inside their directories. D owns the inventory, the blinded queue, the scorer, and the scoreboard. The coordinating session owns promotion. No lane edits gold, sealed holdouts, frozen Exp001–005, historical research outputs, live output, or `.booth.json`.

## Two systems

| System | Inputs |
| --- | --- |
| Universal | Optical audio on the device. Any source. |
| Enhanced | Audio plus an approved external feed or metadata. |

An Enhanced number is never reported as a Universal number. Video is a separate upper bound and is not in this contract.

## Champion

The champion is **no authorized mute**. A candidate replaces it only when all of the following are true:

1. The feature computation is reproducible from a frozen script and hash.
2. The evaluation is causal: at time t the feature does not read audio after its stated availability.
3. On recordings held out from its fitting, it reduces a named pile of user-visible seconds.
4. It does not add an unacceptable pile of hidden programming.
5. Failures and uncertainty are written down.
6. Code and parameters are frozen before the score is recorded.

A higher classification score is not, by itself, an improvement. Standalone recall is not decision accuracy. A missing observation is not evidence against a commercial. Oracle analysis, which may use future games or the gold end, is labeled oracle and is not the champion.

## When the owner locks a result

A lock is the behavior on the television, not a report. Wiring it into `src/hush` or the scoreboard does not lock it.

The same session wires the locked rule into `ohush_live` and restarts the running engine, so the process that is playing audio is the new one. A return brings the game back and blocks a cover. A cover starts only the cover that was locked. The number is not retuned while it is wired. Holdouts stay sealed.

## Clocks and tolerance

All captures in the closed set are 48 kHz stereo PCM. A 10, 20, 40, or 100 ms window is a measurement window. It is not a requirement that a person label every boundary to that precision.

If two detectors differ by less than the annotation uncertainty, they are tied. DCASE event-based evaluation has used a 200 ms onset collar. A difference of 80 ms is not a win when the human mark is uncertain by about 300 ms.

## What this contract does not allow

- Relabeling closed gold in place. Precision marks go in `docs/ohush/swarm/adjudication/judgments.jsonl`.
- Opening `hush_20260917_205513` or `hush_20260920_200635`.
- Treating `.booth.json`, cluster ids, or `booth_present` as a person's identity.
- Treating Thursday's engine-clock decision log as gold. The capture-order clock `hush_20261008_205100` is the audio clock for that file.
- Fitting a threshold on the same recordings used to publish the score.
- Starting a fusion or mute policy before the first independent lane reports exist and D has compared them to the frozen DSP and CNN14 results.
- Hardware optimization before a causal accuracy result exists.

## Signal schema

A lane that emits events writes a table with: experiment id, configuration hash, recording id, audio range, earliest availability, feature value and unit, event type, score (not called a probability unless a calibration report exists), missing-evidence reason, and provenance. Raw scores stay raw.
