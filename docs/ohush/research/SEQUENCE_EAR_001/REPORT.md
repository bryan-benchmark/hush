# The sequence the ear hears

The lines were already published. This pass joins them. It does not search a new cutoff, and it does not change the live mute.

A start has the sequence when the song arrives during the outro and a cut follows. The song arrives when music is under 0.30 at 30 seconds before the mark and, at 5 seconds before the mark, music is at least 0.70 and speech is at least 0.50. The cut is a 12 dB hole in the 2 seconds centered on the mark. That window has been heard one second later. A return candidate is the same hole at the labeled end. A two-minute clock is not a return.

September is the description. The later games are the same lines, not a place to move them.

| Game | Breaks | Song, then a cut | Cut at the start | Cut at the end | 12 dB holes in the game |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sept 9 NBC | 20 | 8 | 15 | 15 | 14 / 88 |
| Sept 13 NBC | 21 | 12 | 18 | 19 | 21 / 138 |
| Sept 14 ESPN | 15 | 3 | 7 | 6 | 9 / 72 |
| Sept 24 Prime | 13 | 7 | 11 | 7 | 26 / 84 |
| September | 69 | 30 | 51 | 47 | 70 / 382 |
| Later games, same lines | 67 | 24 | 42 | 45 | 151 / 608 |

The sequence is real on 30 of 69 September breaks. It is absent on the other 39. ESPN has it on 3 of 15. October 10 has it on none of 6.

The cut by itself is more common, and it is also inside the game. On September, 70 of 382 samples taken every minute away from a break have the same 12 dB hole. That is about one sample in five. October 11 night has the hole on 94 of 223 game samples. A model that mutes on the cut the ear notices will mute play.

Pod length on those September breaks: 3 are within 7.5 seconds of 30, 13 of 120, and 24 of 135. Forty of 69 are none of those. A fixed two-minute unmute, already scored on all 136 football pods, would still be playing ads for 3,138.8 seconds and would still be muted for 1,810.4 seconds of the game.

The way back has a cut on 47 of 69 September ends. The same hole rate inside the game means that cut is not proof the show has returned. Waiting for the song to fall under 0.30 before accepting the booth was already measured. It adds a median 16 seconds, and on the long stays it holds the mute through a score. The return that is locked is the enrolled booth at 0.10.

Script: `experiments/measurement/sequence_ear_001.py`.
