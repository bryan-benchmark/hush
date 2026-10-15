# Accuracy north star

99.99% is the research target, not a claim about the current system. Computation is not a reason to drop a method during research. An input the optical device cannot see is not an audio-only result.

Two systems are scored separately from here on:

- **Universal.** Optical audio only, local, any source.
- **Enhanced.** That audio plus optional game metadata, a schedule, or a supported feed. Enhanced numbers are never reported as Universal.

Video may be used as an upper bound and is a third column. No video was used here.

A single per-second percentage is the wrong score. One covered touchdown can hide inside a very high percentage. The ledger below keeps the failure types apart.

| | |
| --- | --- |
| Three-hour broadcast | 10,800 seconds |
| 99.99% of those seconds | 1.08 seconds of total error |
| One second heard at each of 20 breaks | 20 seconds, about 99.81%, with everything else perfect |
| This football corpus | 17,648 commercial seconds and 67,428 published program seconds |
| 99.99% of that corpus | 8.51 seconds |

| Artifact | sha256 |
| --- | --- |
| `experiments/first_principles_broadcast/error_ledger.py` | `342ccaf5b9850fb338d09727a38b3a945f365323c31538ce8ef3f759370318a7` |
| `docs/ohush/research/ACCURACY_NORTH_STAR_001/results.json` | `52ac72bf6784c4481edfce6abdb58936831c4a031a3485d2ecd8ef2ba7d0b9ee` |

Command: `MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src:. .venv/bin/python experiments/first_principles_broadcast/error_ledger.py`

The join uses the frozen continuous-DSP start table and the closed pod lengths. It does not train a model and it does not change a mute.

## What the frozen audio scan leaves on the table

**Ceiling.** Unmute at the gold end. The device does not know that end. The number isolates the start trigger.

| Start rule | Pods muted | Seconds of delay on those pods | Pods missed | Seconds in the missed pods | Commercial seconds still heard |
| --- | ---: | ---: | ---: | ---: | ---: |
| First DSP hit within 3 s | 86 | 72.9 | 50 | 6,406.8 | 6,479.6 |
| First DSP hit within 30 s | 131 | 582.0 | 5 | 534.9 | 1,116.9 |
| Every pod caught at the observed 1.12 s median | 136 | 152.3 | 0 | 0 | 152.3 |

The 73 seconds are the cost of being a little late on breaks the scan already sees. The 6,407 seconds are breaks it does not see in time. Stretching the wait to 30 seconds trades a late mute for coverage and still leaves 1,117 commercial seconds, about 130 times the 8.51-second corpus budget, with program error set to zero by the oracle unmute.

Catching every break at 1.12 seconds would still hear 152 commercial seconds. That is about 15 seconds in a three-hour game with the 13 or 14 breaks this corpus averages, against a 1.08-second budget. A reactive detector that needs a second of the new audio cannot reach 99.99% even when it is right about every boundary. Advance information has to carry that gap. More GPU does not remove it.

**Causal.** Mute only while a frozen OR episode is on. No hold, no learned return.

| Where the episode sits | Episodes | Seconds |
| --- | ---: | ---: |
| Ordinary football program | 3,993 | 5,862 |
| RedZone | 947 | 1,369 |
| Inside a pod, away from the 3 s edges | 1,723 | 2,604 |
| Fresh at a start | 50 | 73 |
| Already running at a start | 41 | 121 |

Those 3,993 program episodes are 5,862 seconds of football that would be covered if the alarm itself were the mute, and they are 3,993 separate interruptions. The published longest wholly-program episode is 18 seconds, so this is many short hits rather than one long hide. A one-second hit on a touchdown is still a failed product. The same policy overlaps only about 2,800 seconds of the 17,648 commercial seconds, because an episode is usually a second long and then lets go. Most of each ad is still heard.

## Ranked by user-visible seconds

1. **Missed fast starts.** 50 pods, 6,407 commercial seconds, even if the return were perfect and the deadline were 3 seconds. This is the large commercial-coverage hole in the Universal audio we already have.
2. **False mute, if a DSP episode is treated as a decision.** 5,862 football-program seconds and 3,993 incidents, plus 1,369 RedZone seconds. The scan is a candidate, not a mute.
3. **Late but eventual detection.** 582 seconds of delay if a hit any time in 30 seconds is allowed to start the mute, under a perfect return. Real, and much smaller than the misses.
4. **The last second of delay on breaks already caught within 3 seconds.** 73 seconds. Not the place to spend the next experiment.
5. **Return.** Unmeasured in seconds. The ceiling above pretends the gold end is known. No causal unmute in this ledger is allowed to use it.
6. **Enhanced game state.** Not measured. No `tv_timeout` feed was retrieved.

About 31 hours of closed audio can show these holes. It cannot support a consumer-grade 99.99% claim across networks, overtime, injuries, or streaming delay.

## What research is allowed to use

Large audio models, speech recognition, speaker identification, millisecond production measurements, fingerprints, broadcaster rules, ensembles, and GPU inference are all in bounds while accuracy is still moving. A method is dropped when a frozen comparison shows it does not remove a named pile of seconds, not because it is expensive.

Universal and Enhanced stay in separate columns. An event feed or a video upper bound can raise Enhanced, or show a ceiling, and does not count as the optical product.

The sequence is: build the strongest causal start and end system, add game state and measure the increment, replay every recording with only information available at that sample, rank the remaining mistakes by seconds and cause, then add the cheapest new information that removes a pile. Shrink the system after the accuracy has stopped moving. Do not tune that loop on the sealed holdouts.

## Next measurement

The next experiment is a high-accuracy Universal start-and-return system, scored in seconds on this ledger, with large models allowed.

It should attack the 6,407 seconds of missed fast starts and the absent return, and it should report false-mute incidents separately from commercial seconds heard. Shaving the 73-second delay on breaks the DSP scan already catches, and refusing a model because it needs a GPU, are not the next step. An Enhanced `tv_timeout` column waits on an approved feed and is reported beside the audio result, not instead of it.
