# TNF lab 001

Not a mute. Production Auto was not retuned. Playback defaults stay as they were. This file is the 15 October experiment receipt.

## Offline historical, October 8 Prime

These rows can see future audio. They are not a live rate.

| Rule | Commercial seconds covered | Program seconds covered | Incidents | Worst |
| --- | ---: | ---: | ---: | ---: |
| Count 200 | 20.0 | 0.0 | 0 | 0.0 |
| Count 10 | 558.1 | 57.2 | 12 | 7.2 |

## Causal, four measured Thursday windows

Bounded query, no audio after the query: 33, 137, 92, 26. Full-file causal fingerprint was not run again.

| Candidate | Commercial seconds covered inside 139.9–376.9 | Program seconds covered |
| --- | ---: | ---: |
| Gate 200, fail-open 180 s | 0 | 0 |
| Gate 10, cover only while the score holds | 20 | 0 |
| Gate 10, stay until 180 s fail-open | 180 | 0 |

The 180-second row is a timer, not a detected return. Retrieve-and-verify was not run.
