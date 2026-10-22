# Song transition

**NO-GO.** Keep the finding in the research record. Do not keep it as a detection feature, and do not let it mute.

The scan walked every fully annotated sports recording on its own clock. Labels were applied after the events existed. The lines are the ones already published: music under 0.30, then music at least 0.70 with speech at least 0.50, the low window 8 to 24 seconds earlier. A 4-second window hops every 4 seconds. One event stands until music falls under 0.30 again. Holdouts stayed closed. The lines were not refit. The live gate was not changed. Playback stays play.

The rise is real, and it is early. 103 of 136 football breaks have an event in the 30 seconds before the labeled start. The median lead is 10.7 seconds. The 20th percentile is 5.2 seconds and the 80th is 15.8. One of those 103 landed 1.4 seconds after the cut. 113 of 136 have an event in the prior minute. 23 have none in that minute.

That lead is still programming. Acting when the event completes would mute the game for those seconds on a correct call.

The same event is ordinary during play. There are 375 events in 18.8 hours of football that is not a labeled commercial and not in the 30 seconds before one. That is 19.9 events an hour. RedZone, which has no labeled commercials, has 46 events in 2.0 hours, 23 an hour. About 160 of the 375 football events follow another one within 60 seconds, because the music score dips under 0.30 and crosses back. Collapsing a run of those dips into one episode, and starting a new episode only after 2 minutes of quiet, still leaves 165 episodes, 8.8 an hour.

| Network | Breaks with an event in the prior 30 seconds | Events per hour of play |
| --- | ---: | ---: |
| Cable / antenna | 30 / 44 | 23.4 |
| ESPN | 15 / 15 | 21.2 |
| NBC | 28 / 41 | 18.1 |
| Prime | 11 / 13 | 13.3 |
| Prime Video | 19 / 23 | 13.4 |
| FOX RedZone | no labeled breaks | 23.0 |

The September 13 NBC late stretch, about 10,110 to 12,270 seconds, holds 26 of that recording's 60 play events. The rest are spread through the games. On that stretch the score flips from under 0.30 to over 0.70 every few windows while speech stays high. Those flips are separate events under the published rule. They are one unsteady passage of audio.

Inside labeled commercials there are 290 more events, about 59 an hour of commercial time. The rise also happens between spots.

Universal v1, audio only, covers 25.0 football commercial seconds and 0 program seconds. Both of those covers already had a transition in the prior 30 seconds, so requiring the transition keeps 25.0 seconds and still adds 0 program seconds. It leaves the rest of the commercial audio heard. No combined decision from this evidence covers more commercial audio without muting programming.

On the question of whether this is a commercial cue or just how television changes segments: inside football, RedZone matches the play rate with no commercials in the span. The pattern is a common sports-broadcast texture. Scripted television was not scanned.

Uncertainties that remain: the 4-second hop and the 0.30 line turn a dipping score into extra events, and a sustained-low rule was not fit; halftime, touchdowns, replays, and sign-offs are inside the play count and were not labeled apart; these recordings had already been inspected, and the sealed holdouts were not opened.

The production mute path still has no output-clock deadline. The TNF lab path does. This experiment did not touch that failure, and it is still the higher priority.

Scripts: `experiments/measurement/song_transition_001.py`, `experiments/measurement/song_transition_events.py`. Counts: `events.json`. Scores: `scores.jsonl`.
