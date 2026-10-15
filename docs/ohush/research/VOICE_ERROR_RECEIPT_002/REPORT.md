# Voice error receipt 002

Not a mute. Count 10 was not changed. No new speaker embeddings were computed. Gold was not edited. Holdouts stayed sealed. Playback stays PLAY.

The 72 football incidents are the same ones as the ceiling study. This receipt checks the arithmetic, reads the NBC incidents from the existing five-second transcripts, and tests the 90-second pattern on the October 11 afternoon recording.

## The published 27.5 seconds is the real union

The old speech column added up every embedding window that touched an incident. Windows overlap, so NBC incident 6 lasted 20 seconds and was charged 23.5 seconds of speech. Eight football incidents did that.

Clipping each window to the incident and merging the overlaps changes the football speech total from 131.0 seconds to **79.3 seconds**. That is the duration of voiced audio inside the wrong mutes, on recordings that already have embeddings. It is still not a count of known announcers.

The named-voice giveback does not have this bug. Removing the guard with a set difference, which counts each second once, still returns **27.506 seconds**. That matches the published voice-guard shadow. The 88.9 commercial seconds given back are unchanged. The trade is 3.2 seconds of advertising coverage per second of programming returned. That is a trade, not an accuracy improvement.

## RedZone did not hear the named voice during the mute

Both RedZone incidents, 1175–1180 and 1265–1270, show 0 seconds of embedding overlap and 5 seconds of named match. They are the same match. One Mike Tirico window at 1100.9–1102.1 scored cosine 0.342. The next embedding window on that recording does not end until 1318.4. The guard holds playback across that whole gap, and both wrong mutes happen to sit inside it. The voice that matched was about 73 seconds before the first incident. This is not evidence that a program voice was speaking at 1175 or 1265.

On the football recordings the same hold is short. 27.3 seconds of the triggering embedding windows themselves sit inside the wrong mutes, and the published 27.5 seconds are the seconds the guard protects after those windows end. The football number is not the RedZone gap.

## October 11 afternoon is one fingerprint defect

`hush_20261011_135700` has 15 wrong mutes and 79.6 seconds. Thirteen of them, **65.0 seconds**, are a single 5-second query that starts exactly on a 90-second fingerprint read. The reads are the blocks the fingerprint scanner cuts at 90 seconds. The query hop is 5 seconds, so the mute is the five seconds after each block begins.

Those 13 queries score 11 to 25. Universal v1 requires 200, so v1 does not make these mutes. Nine of the thirteen match the same earlier reference, NBC `hush_20260913_210542` at 9680.14 seconds. The same short slice of an old commercial is colliding with the start of block after block. A commercial that was actually playing would not sit at score 25.

On this recording, 13 of 42 block-start queries that land in program score at least 10. Only 3 of the other 748 program queries do. The two incidents that are not on the grid are different: one score-10 hit 80 seconds from a pod, and one score-102 spill that touches a gold commercial.

Ignoring every block-start query, as a diagnostic and not as a rule, would uncover 65.0 program seconds on this tape and also uncover 25.0 commercial seconds on it. Across all football recordings the same ignore uncovers 85.0 program seconds and 190.0 commercial seconds. Monday cable would lose 65 commercial seconds to save 5 program seconds. A global ignore is the wrong fix. The defect is concentrated on this afternoon tape.

No speaker embedding was run on this recording. The 65 seconds are a fingerprint collision, not a missing announcer.

## NBC's 14 incidents are promos and pod edges

The words below are the existing five-second transcripts. No new listen was recorded, and no saved roster name overlaps any of these 14 intervals. Recognizable program speaker, meaning a person already named on that span: **0 seconds**.

| What the transcript shows | Incidents | Seconds |
| --- | ---: | ---: |
| Cover touches a gold commercial | 8 | 62.8 |
| Ad or promo copy inside program, away from that edge | 6 | 60.0 |

The eight edge incidents include The Voice, Traitors, Peacock, a copyright slate, and “make this your most rewarding season.” The cover runs out of an annotated pod and the words on the spill are promo copy. That is annotation-boundary uncertainty, not a missed booth announcer.

The six interior incidents are also not booth talk. Two near the open are “self-drive, self-optimizing,” 40 to 50 seconds from the nearest pod. Three are Traitors promos, the longest 20 seconds and 2,439 seconds from the nearest pod. One, at 7525, is play talk (“on the plate”) and is the incident the current guard returns in full. The named match there comes from an earlier enrollment, not from a name saved on this clip.

Union speech inside the NBC wrong mutes is 65.1 seconds. The guard returns 11.9 of them. The rest of the words are promos the fingerprint already recognizes from an earlier NBC game.

## What was not run

The other October wrong mutes, about 208 seconds after removing this afternoon cluster, are mostly the same kind of weak hit: scores of 10 to 30 against a handful of old references, including that same NBC offset at 9680.14. They are not on the 90-second grid. Embedding those tapes would ask a voice model to veto a bad fingerprint. That is the wrong tool for the cluster that is now explained.

No open-set speaker model. No threshold change. No live mute.
