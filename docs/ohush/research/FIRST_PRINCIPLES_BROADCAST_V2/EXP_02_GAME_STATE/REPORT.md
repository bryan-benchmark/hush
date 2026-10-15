# EXP-02 — Game state and television timeouts

No sports-data subscription was purchased. Nothing in this report is a retrieved `tv_timeout`. The rule text and the vendor documentation are separated from the audio measurements below.

## What the 2026 rulebook says

Source: [2026 Official Playing Rules of the NFL](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf), Rule 4, Section 5, Article 1, Item 2.

> Charged team timeouts shall be two minutes in length unless the timeout is not used by television for a commercial break. Timeouts shall be 30 seconds in length when the designated number of television commercials has been exhausted in a quarter, if it is a second charged team timeout in the same dead ball period, or when the Referee so indicates.

The rule distinguishes a stoppage television uses for a commercial from one it does not. It refers to a designated number of television commercials in a quarter. That number is not stated in this section, and it was not filled in from a secondary source. No count of breaks per quarter or half was coded.

NFL Football Operations' sideline description names a TV liaison, one per game, who coordinates commercial breaks with the network. That description was not available at the production URL tried during this run. It is context for why a timeout and a commercial are operationally related. It is not a measurement on these recordings.

The two-minute timeout and the audible pod are different clocks. The closed football pods already have a median length near 133 seconds, with a wide spread. This experiment does not turn the rule into an unmute timer.

## What Sportradar documents, and what was retrieved

Documented, from [NFL FAQ](https://developer.sportradar.com/football/reference/nfl-faq) and [Tracking Live Games](https://developer.sportradar.com/football/docs/nfl-ig-live-game-retrieval):

- Play-by-play event types include `timeout`, `tv_timeout`, `two_minute_warning`, `period_end`, and `game_over`.
- The Push Pulse feed also documents `tv_timeout` and `tv_timeout_over`.
- While a game is `inprogress`, the play-by-play feed is described as refreshing on a 3-second TTL.
- The same guide says the initial play result typically lands 5 to 10 seconds behind the broadcast. That sentence is about play type, yardage, down, and the primary ball carrier. It is not a measured latency for `tv_timeout`, and it was not checked against these files.
- Marketplace packages are NFL Base, NFL Pulse Push, and NFL Push. No public list price was found. Non-realtime overage in the master terms can be $100 per 1,000 calls. Realtime overage is left to the order form. A recurring contract would sit beside the one-time device price. That cost was not quoted.

Retrieved `tv_timeout` events: none.

The public [nflverse 2026 play-by-play](https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.csv) was inspected at the header only. It has `timeout`, `timeout_team`, and `time_of_day`. It does not have `tv_timeout`. A team timeout in that file is not a television timeout, so those rows were not aligned to the audio.

## Synchronization

`viewer_audio_time ↔ game_event_time` was not built. There is no event feed to align, and the recording's wall-clock start was not treated as the field clock. Until an offset and its uncertainty are measured on a real game, a television-timeout event is unavailable for a mute decision. Prime and other delayed streams make that offset a property of the viewing path, not of the stadium.

## Audio-only state, from the handoff windows

EXP-03 transcribed the 20 seconds before football commercial starts and matched program controls. The same transcripts were searched for frozen game-state tokens. This is not a full-game state track.

| Token in the 20 seconds before the boundary | Football starts | Program controls | RedZone windows |
| --- | ---: | ---: | ---: |
| A quarter name or the word overtime | 5 / 133 | 6 / 135 | 2 / 40 |
| The word timeout | 1 / 133 | 0 / 135 | 1 / 40 |
| A digit clock such as 2:00 | 0 / 133 | 0 / 135 | 0 / 40 |

Quarter language is as common in ordinary program windows as it is before a commercial. A spoken clock in digits did not appear. The fraction of each recording with a reliable quarter and game clock is unmeasured, because the rest of the game was not transcribed. Absence of these tokens is not evidence that the game was in a particular state.

Halftime and overtime are mentioned in a few of the handoff transcripts. There are not enough labeled overtime pods in this gold to support an overtime model, and none was fit.

## Verdict

| Claim | Status |
| --- | --- |
| The rulebook separates televised timeouts from shorter noncommercial ones | Supported, as text |
| A designated commercial inventory exists | Supported, as a reference with no public count |
| `tv_timeout` can be read from an authorized feed on these games | Not measured |
| That feed can be synchronized to the optical audio tightly enough to help | Not measured |
| Speech in the 20 seconds before a start reconstructs quarter and clock | Refuted for these windows |
