# OHUSH_NFL_EVENT_ENGINE_001

OHush now keeps a running football ledger from the live-game audio. It transcribes, writes structured events, and updates a scorekeeper. Automatic muting stays off. The speaker path and the sports daemon were not changed.

## How to run

Transcribe a live-game scope (already done for both Prime tapes):

```
C:\Python313\python.exe -m experiments.nfl75.event_asr
```

Build the ledger from that transcript:

```
python -m ohush_live.football_replay
```

Feed the same interpreter one finished chunk at a time, the shape a live worker would use:

```
python -m ohush_live.football_shadow
```

That shadow reads JSON lines on stdin and writes event and state lines. It does not open a speaker. `applied` stays false. The running daemon does not spawn it.

Tests:

```
python -m unittest tests.test_football_brain -q
```

16 tests, OK.

## What was built

| Piece | File |
| --- | --- |
| Event schema, phrase interpreter, scorekeeper | `ohush_live/football_brain.py` |
| Offline replay of both development games | `ohush_live/football_replay.py` |
| Live-shaped stdin worker, disconnected from playback | `ohush_live/football_shadow.py` |
| Full-game 5-second transcripts | `experiments/nfl75/event_asr.py` |
| One-minute overlapping-window check | `experiments/nfl75/event_overlap.py` |
| Ledger receipts | this folder: `football_events.jsonl`, `game_state.jsonl`, `summary.json`, `overlap_sample.json` |

The transcript itself stays at `docs/ohush/research/NFL75_EVENT_FIRST_001/asr_chunks.jsonl`. 2992 chunks, exit 0, 1314 seconds of wall time. October covers 0 through 9604.9 s (1921 chunks). September covers 0 through 5354.8 s (1071 chunks).

Speech recognition is faster-whisper `base.en`, int8, CPU, 5-second chunks, no future audio. Processing delay after a chunk ends: October median 0.38 s, 90th percentile 0.55 s, max 6.34 s. September median 0.28 s, 90th 0.46 s, max 4.47 s. A word said at the start of a chunk is available about five seconds plus that delay. A word said at the end of a chunk is available in under a second.

## The record

October, 70 live events and 13 uncertain. Three duplicate windows were dropped. September, 20 live events and 3 uncertain. No duplicates dropped.

October live counts: touchdown 14 (11 scoring sequences), timeout 13, interception 5, two-minute warning 5, quarter end 4, two-point 4, program return 4, halftime 7, kickoff 2, extra point 2, fumble recovery 2, challenge 2, punt 1, injury 1, overtime 1, sign-off 1, announced break length 2.

September live counts: touchdown 7, interception 4, program return 3, halftime 2, extra point 1, two-point 1, challenge 1, announced break length 1. No timeout, punt, quarter end, or two-minute warning was kept.

Opening October score, one sequence:

| Audio | Available | Status | What was heard |
| ---: | ---: | --- | --- |
| 55.0 | 60.4 | uncertain | "can they get a touchdown" |
| 80.0 | — | live, score-1 | "for the touchdown." |
| 105.0 | 114.5 | live, score-1 | "breaks the plane, easy touchdown" |
| 120.0 | 125.4 | uncertain | "49 yards and a touchdown for Kailin" |

The question and the stat line do not open a score. The call and the follow-up twenty-five seconds later stay on score-1. The extra-point and "the score is 21 to 17" path is covered by the unit test: those three lines share one sequence and the scorekeeper stores 21–17.

Other lines that behaved as specified:

- 1965 s, "We're back in 30 seconds," kept as a 30-second duration and a halftime mention. It is not stored as a two-minute break.
- 2390 s, "we're back in 30," kept as a 30-second duration. That is the short pod at 2396 s.
- 6350 s, "that's the end of the quarter."
- 8780 s, "After all these messages," kept as a sign-off. On this tape that sentence is ad copy in front of the postgame show.

Lines the interpreter still treats as a new score, and should not:

- 4200 s, "that last Bucks touchdown really infused some energy"
- 5295 s, "185 yards of touchdown"
- 5925 s, "respect that touchdown"
- 6045 s, "a two touchdown lead"
- 9000 s, "89 yards in the touchdown and he didn't"

A one-minute overlap check on October 90–140 s, windows of 5 seconds stepping every 1 second, produced 46 transcripts. "Easy touchdown" was emitted once, at audio 104 s, available about 109.3 s. Three later windows of the same call were suppressed. The "49 yards and a touchdown" recap stayed uncertain. The full game was not re-transcribed on a 1-second hop.

## Diagnostic only: did a live event sit in front of a commercial?

Gold was read after the ledger was finished. It did not choose any event.

October: 17 of 20 in-scope breaks had some live event whose audio time was inside the prior 90 seconds and whose transcript was already available. The three without one start at 4419 s, 5671 s, and 7169 s. September: 4 of 9. The five without one start at 1.6 s, 234 s, 1490 s, 1743 s, and 2797 s.

This is not a coverage number. Fourteen touchdown rows in one game is more than the scoring that game can contain, so a "touchdown" in the prior 90 seconds is often a mention, a recap, or a mis-hear. September's 4 of 9 shows the other failure: the phrase list never heard the stoppage that was actually there.

There is no independent play-by-play on these tapes. Correct, false, and missed event rates are not claimed. The lines above are the review set.

## Acceptance

1. Both games run from transcript through ledger.
2. Replay and the stdin shadow call the same `FootballEngine.observe`. A unit test feeds two engines the same chunks and they agree.
3. State changes only from a live event. Each row stores audio time, availability time, the transcript, the kind, and the status.
4. Hypothetical, replay, and look-back wording stay uncertain and do not open a score. A stat line of the form "and a touchdown" stays uncertain. Some recap wording still gets through, listed above.
5. An overlapping window with the same text, or the same kind inside 15 seconds, does not add a second event. A second touchdown inside 90 seconds stays on the open scoring sequence. A touchdown after that opens a new sequence.
6. Recording, live controls, and speaker output were not edited. `applied` is false.
7. Counts, latency, and the review lines are in this report and in `summary.json`. Separate reviewer wav clips were not cut. The evidence for each row is the transcript text and the audio time, which is enough to listen at that second of the recording.

## Smallest next ticket

`OHUSH_NFL_EVENT_REVIEW_001`. Listen to the 11 October touchdown sequences and the 7 September touchdown rows. Mark each real, replay, stat line, or mis-hear. Do that before any watch or mute. A watch built on the current touchdown list would arm on "two touchdown lead."

After that review, the watch ticket can turn the surviving events into opportunities that stay open while the booth keeps talking. That ticket still does not mute.
