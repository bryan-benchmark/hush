# Voice return

Not a mute. The lines were already published. Voice back is a saved voice at or over 0.10. Quiet is music under 0.30. Nothing was refit. Holdouts stayed closed. Playback stays play. The cut into a commercial was not touched.

The question is the return only. Once the labeled commercial has ended and the game is back, how long until the voice is over 0.10 and the song has dropped.

92 commercials on NBC, ESPN, Prime, and Prime Video. 7 have no game after them in the next 3 minutes: 4 run out of tape, 3 run into audio already taken out of the game column. The other 85 all hear a saved voice. The median wait for that voice is 0 seconds. It is already there on the first game check.

Waiting for the song to drop is the extra wait. Median 16 seconds. Median time from the first game sample until both are true: 20 seconds. Of the 82 that do go quiet inside 3 minutes, 23 are already quiet, 38 are quiet within 12 seconds, 66 within 30 seconds, and 77 within 60 seconds. 3 never go quiet in the window.

Nine stays are still musical a minute after the voice is back. They are not one kind of thing.

- September 9 NBC, commercial ending at 1,048 seconds. The words at the return are “the Patriots up 7–0.” Music is 0.79. It never drops in the next 3 minutes. A Queen Latifah spot plays inside that same stretch. Holding for quiet would miss the return.
- September 13 NBC, ending at 3,716 seconds. The open is “presented by YouTube TV.” About 30 seconds later the call is “touchdown, Giants.” Quiet comes at 104 seconds. Holding for quiet would still be off at the score.
- September 9 NBC, ending at 806 seconds. The desk is on within 30 seconds, Maria Taylor and Mike Tomlin. Quiet comes at 60 seconds.
- September 9 NBC, ending at 1,255 seconds. “Presented by Progressive,” then the third quarter. Quiet comes at 80 seconds.
- September 24 Prime, ending at 7,020 seconds. The desk is on Derek Stingley and Ja'Marr Chase under music at 0.95. Quiet comes at 68 seconds.
- September 24 Prime, ending at 5,519 seconds. The voice is back, and within 30 seconds it is TNF Nightcap, not the live game. Quiet comes at 64 seconds.
- September 9 NBC, ending at 8,585 seconds. The next audio is the local news and the weather. That is not the game. The song never drops because the news bed stays up.
- October 8 Prime Video, ending at 9,754 seconds. The next labeled commercial starts 16 seconds later. No transcript. That gap is between two spots.
- October 8 Prime Video, ending at 9,770 seconds. No transcript. Quiet comes at 64 seconds. Music at the voice is 0.85.

The rule does not get installed. On a typical return it would add about 16 seconds. On the long ones it would hold the sound off through a touchdown and through the desk. Those are the announcer coming back over the music. A song hold cannot hear them.

Script: `experiments/measurement/voice_return_001.py`. Counts: `results.json`. One row per commercial: `receipts.jsonl`.
