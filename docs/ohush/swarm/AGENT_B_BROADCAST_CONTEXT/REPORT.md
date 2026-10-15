# Agent B — NFL and broadcast intelligence

Copied from the three reports below. No new measurement, no purchased feed, no rerun transcription. Gold, live code, `.booth.json`, and holdouts were left closed.

- `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_02_GAME_STATE/REPORT.md`
- `docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_03_HANDOFF_LANGUAGE/REPORT.md`
- `docs/ohush/research/BROADCAST_INTELLIGENCE_001/EXP_C_BREAK_CLOCK/REPORT.md`

## 2026 rule: televised timeout versus 30-second stoppage

Source: [2026 Official Playing Rules of the NFL](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf), Rule 4, Section 5, Article 1, Item 2.

Charged team timeouts are two minutes unless television does not use the timeout for a commercial. They are 30 seconds when the designated number of television commercials has been exhausted in a quarter, when it is a second charged team timeout in the same dead ball period, or when the Referee so indicates.

The section names a designated commercial inventory and does not state the number. That number was not filled in from a secondary source. No count of breaks per quarter or half was coded. The two-minute rule and the audible pod are different clocks. Closed football pods already have a median near 133 seconds, with a wide spread. This text was not turned into an unmute timer.

## `tv_timeout` is documented and was not retrieved

Sportradar’s NFL FAQ and live-game guide document play-by-play types `timeout`, `tv_timeout`, `two_minute_warning`, `period_end`, and `game_over`. Push Pulse also documents `tv_timeout` and `tv_timeout_over`. While a game is `inprogress`, play-by-play is described as refreshing on a 3-second TTL. The same guide says the initial play result typically lands 5 to 10 seconds behind the broadcast. That sentence is about play type, yardage, down, and the primary ball carrier. It is not a measured `tv_timeout` latency, and it was not checked against these files. No public list price was found.

Retrieved `tv_timeout` events: none.

The public nflverse 2026 play-by-play file was inspected at the header only. It has `timeout`, `timeout_team`, and `time_of_day`. It does not have `tv_timeout`. A team timeout in that file is not a television timeout, so those rows were not aligned to the audio.

`viewer_audio_time ↔ game_event_time` was not built. The recording’s wall-clock start was not treated as the field clock. Until an offset and its uncertainty are measured on a real game, a television-timeout event is unavailable for a mute decision. Prime and other delayed streams make that offset a property of the viewing path.

## Handoff phrases

`faster-whisper` 1.2.1, `base.en`, int8, CPU, not fine-tuned. Strong phrases were frozen before any transcript was read: `we'll be right back`, `we will be right back`, `be right back`, `when we come back`, `after these messages`, `these messages`, `commercial break`, `going to commercial`, `we'll return`, `we will return`, `back after this`. Weak phrases (`two-minute warning`, `two minute warning`, `end of the quarter`, `end of the half`, `end of quarter`) were reported and not counted. The word `timeout` is a game-state token, not a handoff hit.

Three football starts lacked a full window, so the football denominator is 133. A hit is a strong phrase whose word starts before the label.

| Set | Strong phrase before the split |
| --- | ---: |
| Football starts | 12 / 133 |
| Football program controls | 0 / 135 |
| RedZone | 0 / 40 |
| Scripted starts (Hulu) | 0 / 29 |

Recall on football starts is 0.090. Automatic lead times, including two bad hits, have median 6.1 seconds. The shortest intelligible leads are 1.4 and 1.7 seconds. Six of the twelve automatic hits, and five of the ten intelligible ones, are one Monday cable game. ESPN is 0 of 15. Sept 24 Prime is 0 of 12. Reading the twelve changes two: the Oct 8 Prime line is already advertising copy, and one Oct 12 line is an ASR garble. A phrase is not permission to mute, and it does not say when the game has returned.

RedZone has no commercial in the scored span and still says “two-minute warning” twice (weak count 2 / 40). A two-minute warning is not a mute cue.

In the same 20-second windows, a quarter name or overtime appears in 5 / 133 football starts, 6 / 135 program controls, and 2 / 40 RedZone windows. The word timeout: 1 / 133, 0 / 135, 1 / 40. A digit clock such as 2:00: 0 / 133, 0 / 135, 0 / 40.

## A duration prior must never unmute

EXP-C froze 120 and 135 second timers before reading the histogram. Verdict: fail as an unmute. The duration distribution is real. A point timer is not a return decision. Timer-only unmute is not authorized.

| Set | n | Median | p10 | p90 | Near 120 (±7.5 s) | Near 135 (±7.5 s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Football | 136 | 132.8 s | 48.7 s | 181.9 s | 31 | 40 |
| All target commercials | 166 | 123.9 s | 49.6 s | 174.4 s | 31 | 40 |

Near either fixed time: 71 football pods. The football 10th percentile is 48.7 seconds. The mass of football pods sits between roughly 50 and 180 seconds.

If that timer were the unmute, on the 136 football pods:

| Rule | Median absolute error | Ad seconds still playing | Program seconds still muted |
| --- | ---: | ---: | ---: |
| Fixed 120 s | 17.5 s | 3138.8 | 1810.4 |
| Fixed 135 s | 14.6 s | 1967.5 | 2679.1 |
| Within-game running median (131 pods) | 16.2 s | 2387.1 | 2391.5 |

Five football pods are the first of their recording, so the running median has no prediction for them. Unmuting because a timer expired would expose on the order of 2,000–3,000 ad-seconds across these 136 pods, or cover a similar amount of the game. The clock is a wide prior for a later audio check. It must never unmute by itself.

## Status

| Claim | Status |
| --- | --- |
| Rule 4 Section 5 Item 2 separates a 2-minute televised timeout from a 30-second noncommercial timeout | Supported, as text |
| A designated commercial inventory exists | Supported, as a reference with no public count |
| Sportradar documents `tv_timeout` | Supported, as documentation |
| `tv_timeout` was retrieved on these games | Not measured |
| nflverse 2026 play-by-play has `tv_timeout` | Refuted at the header; it has `timeout` and not `tv_timeout` |
| Viewer audio was synchronized to a game-event clock | Not measured |
| A frozen sign-off precedes some NFL starts and was absent from the matched controls | Supported (12 / 133, 0 / 135, 0 / 40; median lead 6.1 s) |
| That phrase covers most breaks, scripted shows, or the return | Refuted (0 / 29 scripted; six hits on one Monday cable game) |
| “Two-minute warning” is a mute cue | Refuted; it appears on RedZone |
| Speech in the 20 seconds before a start reconstructs quarter and clock | Refuted for these windows |
| Football pod lengths cluster, with a wide spread around about 2 minutes | Supported as a prior (football median 132.8 s) |
| A fixed 120 s or 135 s timer, or a within-game median, may unmute | Refuted |
| A fused game-state machine improves mute accuracy | Not measured |
