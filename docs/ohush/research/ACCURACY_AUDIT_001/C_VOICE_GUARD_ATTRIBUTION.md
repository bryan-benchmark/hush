# Voice-guard attribution

A second is credited to the name whose match forced playback, and only where that interval overlaps a count-10 cover. Same recording means this broadcast contains a program enrollment for that name. Other recording means the name was enrolled on a different tape.

Each row is one name on one recording.

- other_recording_ad: 0.0 program seconds, 61.4 commercial seconds.
- other_recording_both: 10.1 program seconds, 0.8 commercial seconds.
- other_recording_program: 6.8 program seconds, 0.0 commercial seconds.
- redzone_other_recording: 10.0 program seconds, 0.0 commercial seconds.
- same_recording_ad: 0.0 program seconds, 26.7 commercial seconds.
- same_recording_program: 10.6 program seconds, 0.0 commercial seconds.

The RedZone 10.0 program seconds are in the `redzone_other_recording` row. That match is Mike Tirico, enrolled on an earlier NBC tape. Scott Hanson was not the name on those seconds.

Case rows are in `guard_match_cases.csv`.
