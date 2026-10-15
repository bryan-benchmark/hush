# Universal v3 speech evidence

This is not a mute policy. No threshold was chosen, and no play/cover timeline was built from these phrases.

The question was whether a strong announcer handoff is spoken before commercial audio starts, and whether the recognizer knows that fact before the start. Those two times are different. The spoken time is the end of the word that completes the phrase. The recognizer can emit the phrase only at the end of the 20-second chunk it just heard.

| Artifact | sha256 |
| --- | --- |
| `experiments/universal_v3/speech_evidence.py` | `f3c833c1d5cdc58ad7ba96ead379cc9a2ee2d35a1d70e46f7be0cd39369a2690` |
| `results.json` | `864876ac97efc492fd3d43d7969186ddbd99f66560a5e133c9e1cc7a3d968826` |

Model: faster-whisper `base.en`, int8, CPU, beam size 1, VAD off. Same settings and the same strong-phrase list as the earlier neighborhood scan. Chunks are 20 seconds, back to back, across all ten sports recordings, including RedZone. Gold was not used to place the chunks. Scripted recordings were not scanned.

All ten sports ranges were transcribed. Thursday has eight unreadable chunks inside the known 240-second hole. Sunday night has one unreadable chunk inside the known 35-second hole. A phrase split across a chunk boundary is missed. Nested phrases in one sentence are one moment: "after these messages" also matches "these messages".

## What was spoken, and when it was known

136 football pods.

| Count | Meaning |
| ---: | --- |
| 18 | Distinct strong-phrase moments in football audio. The raw phrase rows are 25 because some sentences match two list entries |
| 12 | Of those, the words finish in the 30 seconds before a gold start |
| 3 | Of those 12, the recognizer finishes before that start |
| 1 | RedZone moment. Three phrase rows, one sentence |

The three the recognizer knew in time:

| Source | Phrase | Words finished before the start | Recognizer finished before the start |
| --- | --- | ---: | ---: |
| NBC, Sept 9 | after these messages | 3.8 s | 1.0 s |
| Prime Video, Oct 8 | these messages | 18.7 s | 2.6 s |
| Cable, Oct 12 | when we come back | 7.3 s | 4.3 s |

The NBC line is a postgame toss ("Chevrolet post game comes your way right after these messages"). The Prime Video line is the same kind of toss ("after all these messages"). The cable line is a booth toss ("We'll get the call when we come back").

The other nine spoken-early moments are real tosses in the transcript, except one Monday line that reads as a garble ("yards back after this"). On those nine, the words end before the gold start and the chunk ends after it, so the transcript arrives once commercial audio has already started.

Five of the twelve spoken-early moments are the Monday cable game. ESPN and the September 24 Prime recording have none.

## Lines that are not a 30-second warning

Six other football moments match the list and are at least 15 seconds from every gold pod.

Three Sunday-night lines are dialogue ("I'll be right back", "walk mother upstairs and be right back"), thousands of seconds from the nearest pod. One NBC line is ad copy: "We'll be right back", then a USAA spot, 1,481 seconds from the nearest pod boundary. One NBC booth line, "We'll be right back", sits 99 seconds from the nearest gold boundary. One Saturday line, "we be right back", sits 35 seconds from the nearest boundary and is followed immediately by ad copy. That Saturday line is outside the 30-second window used here.

RedZone, which has no gold commercials in its two annotated hours, has one host line: "And with that we'll be right back", after which the host keeps reading scores and talks about commercial breaks in other games.

## What this does not authorize

A strong phrase is sometimes spoken before the commercial. The recognizer, on this chunking, knew that before the start for 3 of 136 pods. The same phrases also occur in ads, in show dialogue, and on RedZone while the show continues. That is not a commercial-mute rule. It does not change Universal v1, and it is not a 99.99% result.
