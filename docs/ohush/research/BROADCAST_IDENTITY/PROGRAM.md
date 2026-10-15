# Broadcast identity

This program asks who is speaking, and which broadcast that person belongs to. It does not ask whether a second sounds like an advertisement, and it does not authorize a mute. Playback stays PLAY.

Generic detectors stay where they are. A named voice is evidence about the program. Silence, a different voice, or a gap in that voice is not an advertisement. A correct name during a promo is still that person, and it is not by itself the game. A commercial still has to be recognized on its own.

## What is already enrolled

The voice roster is the catalog. The latest save for each clip is in `docs/ohush/research/VOICE_ROSTER_001/names.jsonl`. The count is in `docs/ohush/research/UNIVERSAL_V4_SPEAKER_ENROLLMENT_001/REPORT.md`: 14 people, 29 named speech spans. Scott Hanson has two spans. Joe Buck, Troy Aikman, Mike Tirico, Cris Collinsworth, and Al Michaels are in that list.

An October 14 report said there were zero verified enrollments. That file had not been regenerated after the saves. `verified.jsonl` is the append log, 274 rows, and it is not the count. Anonymous cluster ids are still not enrollments. The ESPN cluster of about 2,161 speech seconds is the group the Troy Aikman sample came from. The name is on that sample. The cluster id is not the person.

## What was already measured

`docs/ohush/research/VERIFIED_SPEAKER_001/REPORT.md` scores those names with the existing ECAPA embeddings at the published cosine of 0.25. Nothing was refit.

The two Hanson examples match each other: 15 of 15 held-out windows, median cosine about 0.48. The weakest window is 0.255. The same line also matches Mike Tirico, Joe Buck, the Lions booth inside this RedZone recording, and a Honda, Vyper, and Subway ad. After the first Hanson example, about half of the later speech windows still pass the line. A match that common cannot by itself mean the program is RedZone.

Joe Buck, Cris Collinsworth, and Mike Tirico match their own held-out clips. Joe Buck also matches other named announcers on 22 of 44 windows. Al Michaels and Troy Aikman have one clip each, so they were not held out.

This September 13 RedZone recording has zero gold commercials. That is true for this tape only. It cannot test whether a Hanson match would also fire on a RedZone advertisement.

## What is not started

A second RedZone recording that actually contains ads. Recognition of these voices on a later, separate recording. Local baseball, basketball, hockey, news, and racing rosters. WeSpeaker and pyannote. Any rule that keeps audio playing because a name matched, or that mutes because a name disappeared.

The order, when one of those is authorized, is the same one already used here: enroll a person by ear, test that name at the published ECAPA line, and keep the match separate from advertisement status.

## Voice guard

`docs/ohush/research/VOICE_GUARD_001/REPORT.md` applied that line to the published count-10 candidate. Where a named voice matched, the candidate was forced back to play. It gave back 27.5 of the 432.1 false program seconds and also gave back 88.9 commercial seconds. Playback was not changed.
