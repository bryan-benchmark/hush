# Hold the spot covers until the song drops

The six count-200 covers from the spot pieces stay up until music falls under 0.30. That hold marks **76.0** commercial seconds and **0** program seconds. No new cover was searched. The count was not moved. The live mute was not changed.

The quiet line and the 4-second music steps are the ones already logged for the whole-pod hold. A cover lets go at the first step, at or after it starts, where music is under 0.30. If that step is still inside the labeled break, the seconds in between are commercial. If it falls after the break, the run is broken. Three covers start. Later fingerprint hits inside the same break, before the song drops, are the same hold.

| Broadcast | Hold | Song drops | Commercial seconds | Program seconds | Ad still heard after the drop |
| --- | --- | ---: | ---: | ---: | ---: |
| Sept 14 ESPN, break 2658.534–2780.388 | 2770 | 2780 | 10.0 | 0 | 0.388 |
| Oct 8 Prime Video, break 139.874–376.900 | 145 | 196 | 51.0 | 0 | 180.9 |
| Oct 8 Prime Video, break 6363.797–6515.381 | 6385 | 6400 | 15.0 | 0 | 115.381 |

The ESPN hold ends 0.4 seconds before the label. Music at that step is 0.036. The Oct 8 opening lets go at the same step as the published whole-pod hold, 196, and it starts 5 seconds earlier, at 145 instead of 150. The second Oct 8 break lets go after 15 seconds. Most of both breaks is still heard.

These 76 seconds contain the 30 seconds the fingerprint itself marked. They are not a second copy of the published 116-second hold. That hold is the Oct 8 opening from 150 to 196 (46 seconds) plus the Oct 12 cover from 5090 to 5160 (70 seconds). The opening is the same let-go. Counting 76 on top of 116 would count 150–196 twice.

Taken once each, the two holds are the Oct 8 opening from 145 to 196 (51 seconds), the Oct 12 cover from 5090 to 5160 (70 seconds, already published), the ESPN cover from 2770 to 2780 (10 seconds), and the later Oct 8 cover from 6385 to 6400 (15 seconds). That is **146.0** commercial seconds and 0 program seconds. 146.0 / 17,648.4 is 0.83%. The published ceiling on these tapes was 116.0 seconds, 0.66%. This is not wired into the television. 134 of the 136 breaks are still never started, and the ones that do start still let go while the break has a long way to run.

The reader is `experiments/measurement/spot_hold_001.py`. Counts are in `results.json`.
