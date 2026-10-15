# Agent C — Content identity

Sources copied, not rerun: `docs/ohush/research/KNOWN_AD_FINGERPRINT_001/REPORT.md` and `docs/ohush/research/BOOTH_IDENTITY_AUDIT.md`. Gold, live code, `.booth.json`, and holdouts were not edited. Fingerprints were not rerun. Cluster ids and `.booth.json` are not treated as identity.

## Commercial audio

Verdict of KNOWN_AD_FINGERPRINT_001: **INCONCLUSIVE**. The matcher is audfprint, commit `cb03ba99feafd41b8874307f0f4e808a6ce34362`, MIT, copyright 2014–2015 Dan Ellis, Columbia University, and Google. The license covers the matcher. It does not authorize selling or redistributing the captured broadcasts, even after they have been hashed.

Frozen analyzer settings, written before matches were read: 11,025 Hz mono, density 100 peaks per second, match window ±2 frames. Reference time-shifts stay at 1. The ad note also builds references at 4 shifts; that multiplier was not applied. CNN14 was not refit. No mute rule was changed. Holdouts stayed closed.

Eligible counts were 5, 10, 20, 50, and 200. The operating count is the smallest whose ESPN leave-one-recording program probes stay at or below 1 false identification per probed hour. ESPN selected **count 10**: oracle program probes were 1 hit in 4,410 seconds (0.82 per hour). Count 5 was 33 hits (26.9 per hour). Counts 20, 50, and 200 were 0 on that ESPN probe.

Count 10 failed transfer onto evaluation football. Chronological library, program probes: **about 2.08 false identifications per probed hour** (33 / 57,210 s). The same setting recognizes **13 of 41** evaluation DSP-missed starts within 5 seconds. RedZone at count 10 is 1.00 per probed hour (2 / 7,170 s). The 5-second opening rate is 33 / 121, above that RedZone fraction, and still above the false-identification budget of 1 per probed hour. PASS required all of those conditions together.

The published count of **200** has **0 program false identifications** on the evaluation probes and 0 on RedZone. It matches **0 of 121** evaluation openings within 5 seconds and **6 of 121** within 10 seconds. It matches none of the 41 evaluation DSP-missed starts within 5 seconds. FAIL does not trigger, because 6 openings match within 10 seconds. The result stays inconclusive.

Sept 9 NBC, chronological library, is **0 / 20** at 5 seconds and **0 / 20** at 10 seconds at count 10. The prior library for that game is only the August 27 Hulu pods. Oracle matches, which may use later football games, are 10 / 20 at both 5 and 10 seconds, and 0 / 20 at count 200. An advertisement that is not already stored cannot be returned as a known item.

A match is earlier **commercial-region audio**, not a named creative. A pod is a container. A hit may be one advertisement, a bumper, a sponsor bed, or other recycled material. Individual spots are not labeled. Twelve closed ranges supplied 166 pods. The strongest cited pairs (Prime Video on Oct 8 against a Sept 24 Prime pod; cable on Oct 12 against an ESPN pod) are known commercial-region audio and have no creative name in the gold. Enrollment used gold commercial intervals as an offline assumption. That is not an automatic enrollment system. The oracle library is an upper bound under verified commercial enrollment, not a deployable method.

**Disappearance is not a return.** The end of a match is not a program return. Disappearance of a matched spot was not scored and would not establish that the game had returned. A program passage that happens to sit inside some stored commercial interval remains program.

## Speaker identity

`BOOTH_IDENTITY_AUDIT.md` is listening material for the Thursday session. It does not delete or replace `.booth.json`. It does not record a verified announcer.

The frozen session file trusts `c0001`, `c0002`, `c0015`, and `c0017`. `run29` readings carry `booth_ids` of `c0001`, `c0002`, `c0004`, `c0005`, and later swap `c0005` for `c0003`. Those two lists are not the same set. Excerpts from `audio_0044.wav` are candidates for a listen, not a sample-locked join and not an enrollment. No id was removed.

**Verified speaker enrollments: 0.**

## Next measurement

The next identity measurement is **human-verified announcer enrollment from program audio**.

Another min-count is not justified. Count 200 is already clean on program and RedZone probes and already matches 0 of 121 evaluation openings within 5 seconds. The oracle library already contains every other recording's commercial pods and still matches 0 of 121 evaluation openings within 5 seconds at count 200. Another CNN14 threshold is not the next measurement. CNN14 was not refit here, and an acoustic-distance cutoff has already failed transfer from the ESPN selection game to evaluation football. Identifying the program's own recurring voices is the return question this fingerprint probe cannot answer.
