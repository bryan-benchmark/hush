# Voice floor

This is the return. The labels were made so the audio comes back when the show is back. The cut into a commercial is a different model. 0.10 is a placeholder for the return, not an optimized start.

Not a mute. Playback stays play. The published SpeechBrain cosine stays 0.25. This floor is a separate module, `src/hush/voice_floor.py`. The play decision asks it when the show returns. It does not start a commercial. Only a published count-200 fingerprint can cover.

The score is the highest saved voice on that show over the previous 30 seconds. The tapes are NBC, ESPN, Prime, and Prime Video. Postgame tape, the local news, and the unmarked spots already taken out of the game column stay out. The original commercial marks were not edited.

| Line | Commercial seconds off | Game seconds off | Share of the game |
| --- | ---: | ---: | ---: |
| 0.10 | 288 | 4 | 0.006% |
| 0.15 | 1,036 | 112 | 0.17% |
| 0.20 | 2,612 | 324 | 0.48% |
| 0.25 | 4,956 | 736 | 1.09% |

The game column is 67,428 seconds. The commercial column is 17,648.4 seconds. 288 commercial seconds is 1.6% of that column. 1,036 is 5.9%.

The floor is 0.10. At that line the only game-column hit is 4 seconds on the September 14 ESPN tape, “Giants, Rams, at eight on ABC and ESPN.” That is a promo.

0.15 is the first line that turns the show off. Of its 112 seconds, 52 are the Allstate halftime, 44 are a Kenneth Walker interview and a wedding answer, and 16 are a hockey promo, a sign-off, the same Giants–Rams promo, and a Chili’s spot. Joe Buck’s “Isaiah Likely, one of two touchdowns” stays on. It scores 0.172, so 0.20 turns that call off. That is why 0.20 is not the floor.

A score under 0.10 does not start a commercial. The commercial seconds in the table are what this placeholder would hold if it were also used as the cut. That is not its job. The module brings the audio back when the show is at or over 0.10, and otherwise stays on play. Cover still has to come from the published fingerprint.

Counts: `results.json`. Stretches: `receipts.jsonl`. The same rows are in `src/hush/voice_floor.py`.
