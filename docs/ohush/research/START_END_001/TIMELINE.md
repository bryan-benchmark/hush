# Timeline of the misses

“Not caught” is not a description. Each of the 134 missed starts now has a trace, one step every four seconds, from 60 seconds before the labeled cut to 20 seconds after it. 133 traces were read. One Prime cut is too close to the start of the file.

A step is the four seconds that end at that time. It records the speech score, the music score, the loudness, the pitch, the brightness, the pulse in the loudness, the nearest person from that show’s own booth and the cosine, the words when a full transcript exists, and the changes since the previous step. The file is `timeline_receipts.jsonl`. Nothing here is a mute. The lines are the ones already published: music under 0.30, music at or above 0.70, booth cosine 0.25.

Sixty-nine misses have a word at every step. The October recordings do not have a full transcript, so those traces have the sound and the booth and not the sentence.

## Where the pattern moves

When a speech window exists, the booth cosine is 0.49 in the span from 60 to 20 seconds before the cut, 0.55 in the last 20 seconds before the cut, and 0.10 in the 20 seconds after it. The person the show enrolled is still the nearest voice while the bed arrives. After the label, that voice is gone.

The music rise, quiet under 0.30 then at or above 0.70, happens on 105 of the 133 traces. The median step is **11.4 seconds before the cut**. A fifth of those rises are earlier than 20.8 seconds. A fifth are later than 1.7 seconds.

The pattern at each clock, counting every miss:

| Seconds relative to the cut | Booth, little music | Booth over a song | Song, booth gone | Little music, booth gone |
| ---: | ---: | ---: | ---: | ---: |
| −48 | 38 | 7 | 13 | 72 |
| −20 | 41 | 11 | 18 | 59 |
| −12 | 25 | 31 | 42 | 23 |
| −4 | 11 | 41 | 67 | 11 |
| +4 | 0 | 2 | 86 | 23 |
| +12 | 0 | 0 | 94 | 21 |

A minute out, the common states are the booth over a quiet bed, or quiet with no booth window. By four seconds before the label, 108 of the traces are already a song. Four seconds after the label, 86 are a song with the booth gone. The rhythm breaks when the song arrives under the person who is already talking. The cut is the later moment, when that person leaves and the sentence changes.

## One trace, read in full

NBC, Sunday Night Football, labeled start 623.347 seconds. The fingerprint never covered it. Tirico and Collinsworth are the only booth this show is allowed to name.

| Rel | Music | Speech | Nearest booth | Cosine | What changed | Words in that four seconds |
| ---: | ---: | ---: | --- | ---: | --- | --- |
| −55 | 0.14 | 0.05 | none | | speech fell | six |
| −51 | 0.32 | 0.81 | Tirico | 0.15 | speech rose | six snaps. It's a heavier load for perimeter people |
| −39 | 0.14 | 0.86 | Tirico | 0.07 | | to affect the game. They've been running the ball |
| −27 | 0.74 | 0.89 | Tirico | 0.14 | music rose | to the fourth quarter of the Super Bowl |
| −15 | 0.11 | 0.88 | Collinsworth | 0.09 | music dipped | hang out here for halftime |
| −11 | 0.70 | 0.91 | Tirico | 0.18 | music returned | Coach Tomlin actually caught up with his old rival |
| −3 | 0.93 | 0.93 | Tirico | 0.09 | | when we come back |
| +1 | 0.94 | 0.92 | Collinsworth | 0.01 | | about their travel plans, though, when we come back |
| +5 | 0.94 | 0.93 | Tirico | 0.29 | booth cosine crosses 0.25 | Want some sports trivia? Just ask Siri |
| +9 | 0.96 | 0.94 | Tirico | 0.18 | back under the line | Who is the all-time passing touchdowns leader |
| +13 | 0.89 | 0.06 | none | | speech fell | |
| +17 | 0.59 | 0.62 | none | | speech rose | Touchdown! Yeah! |

The game talk is still the sentence at −39, with almost no music. The song is in by −27, and the same booth is still the nearest name, under the published line because the song is in the embedding. The sign-off “when we come back” is the last four seconds of the broadcast. Siri is the commercial. The cosine never cleanly tracks him across that handoff. The music score does.

That is the shape on the traces that have a rise: the bed changes about eleven seconds before the label, the enrolled voice is still the nearest name while it happens, and the voice is gone once the new sentence is the ad.

Script: `experiments/measurement/miss_timeline_001.py`.
