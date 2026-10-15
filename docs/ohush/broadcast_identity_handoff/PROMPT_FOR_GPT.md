# Broadcast identity handoff

Today is 15 October 2026. Read this zip before the GitHub copy of the enrollment report. Commit `18c7179` on `bryan-benchmark/hush` still says zero verified enrollments. That sentence is stale. The files in this zip replace it.

No mute is authorized. Playback stays play. Universal v1 is the research baseline. Count 10 is an ablation, not a live rule.

## Read in this order

1. `docs/ohush/research/BROADCAST_IDENTITY/PROGRAM.md`
2. `docs/ohush/research/UNIVERSAL_V4_SPEAKER_ENROLLMENT_001/REPORT.md` and `results.json`
3. `docs/ohush/research/VERIFIED_SPEAKER_001/REPORT.md` and `results.json`
4. `docs/ohush/research/VOICE_GUARD_001/REPORT.md` and `results.json`
5. `docs/ohush/research/VOICE_ROSTER_001/names.jsonl` only if you need the typed words. The latest save for each clip id wins.
6. `docs/ohush/swarm/SCOREBOARD.md` for the ledger row. The 14 October speaker-enrollment row is the old counter. The 15 October rows supersede it.

`verified.jsonl` is not in this zip. It is an append log of 274 saves, including edits, ads, and crowd. It is not the enrollment count.

## What is already measured

A person named 14 people across 29 speech spans. Scott Hanson has two. Joe Buck, Troy Aikman, Mike Tirico, Cris Collinsworth, and Al Michaels are in the same list.

At the published ECAPA cosine of 0.25, the two Hanson examples match each other: 15 of 15 held-out windows, median about 0.48, weakest window 0.255. The same line also matches other announcers, other RedZone booths, and a few ads.

VOICE-GUARD-001 forced the published count-10 candidate back to play when a named voice matched. It gave back 27.5 of 432.1 false program seconds and also gave back 88.9 commercial seconds. 273.0 of the 432.1 are on recordings with no speaker embeddings. 3,789.3 scorable commercial seconds remained beyond Universal v1's 25.0. None of those 25.0 were given back. Hanson's enrollment did not cover RedZone's 10.0 false program seconds. An earlier Mike Tirico enrollment matched them.

## Do not

- Call the enrollment count zero.
- Treat a cluster id, `.booth.json`, or `booth_present` as a person.
- Retune 0.25, count 10, or count 200.
- Promote count 10 or the voice guard to a live mute.
- Unseal `hush_20260917_205513` or `hush_20260920_200635`.
- Edit gold. This RedZone recording has zero commercials. That is this tape only.
- Treat a gap in a voice as an advertisement.
- Invent a WeSpeaker or pyannote result. Those models were not run.

Quote the file for every number.
