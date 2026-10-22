# Voice over a song

Not a mute. The lines were taken from one Prime sign-off that had already been listened to, then applied to the rest of the labeled football. October recordings were already inspected. Holdouts stayed closed. Playback stays play.

The question is when a voice riding a song shows up before a labeled commercial, and how often the same thing shows up in ordinary play.

The ear is the AudioSet speech and music heads already in the project, checkpoint `Cnn14_mAP=0.431.pth`. They were not refit. A 4-second window counts as voice over a song when speech is at least 0.50 and music is at least 0.70. Those two numbers are the Prime break at 234 seconds. They were not searched again.

Windows end 60, 30, 20, 10, 5, 3, 2, and 1 second before each labeled start, and one window begins half a second after it. Ordinary play is one 4-second window every 120 seconds, kept 30 seconds away from every labeled break, capped at 180 windows. RedZone is the same kind of sample, every 150 seconds, 40 windows, on a span with no labeled commercials.

| Seconds before the cut | Breaks with voice over a song | Median music | Median speech |
| --- | ---: | ---: | ---: |
| 60 | 11 / 136 | 0.06 | 0.84 |
| 30 | 15 / 136 | 0.06 | 0.85 |
| 20 | 25 / 136 | 0.07 | 0.86 |
| 10 | 75 / 136 | 0.86 | 0.86 |
| 5 | 88 / 136 | 0.92 | 0.87 |
| 3 | 85 / 136 | 0.92 | 0.87 |
| 2 | 79 / 136 | 0.92 | 0.86 |
| 1 | 64 / 136 | 0.92 | 0.83 |

Speech stays high the whole minute. The song does not. It is absent at 60 and 30 seconds, on the same numbers as ordinary play, and it arrives between 20 and 10 seconds before the cut.

On 86 of 136 breaks the music score is under 0.30 at 30 seconds and at least 0.70 at 5 seconds. On 73 of those, a voice is over the song at 5 or 3 seconds. 114 of 136 breaks have voice over a song at some clock in the minute. 22 never do. 23 never reach music 0.70 in the last 10 seconds.

Ordinary play: 20 of 180 windows are voice over a song, and 21 reach music 0.70. Median music there is 0.07. Median speech is 0.85. Ten of the twenty sit in one late stretch of the September 13 NBC recording, from about 10,110 seconds to 12,270. RedZone: 2 of 40 windows, median music 0.08.

The spot itself is often still voice over music. 63 of 136 breaks still meet the line in the window that starts half a second after the cut, and 77 still have music at 0.70. The mark is the song arriving in a minute that did not have one, not the presence of music after the cut.

Script: `experiments/measurement/voice_over_song_001.py`. Counts: `results.json`.
