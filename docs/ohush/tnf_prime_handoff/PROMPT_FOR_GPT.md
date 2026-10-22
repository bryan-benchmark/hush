# Paste this with the zip

You are auditing the 15 October 2026 Thursday Night Football stopping point for OHush. Read `docs/ohush/tnf_prime_handoff/STATUS.md` first. Then read the files in the order below. A json or csv row beats a sentence in a report. Quote the file for every number.

No mute is authorized. Playback stays play. Universal v1 is the research baseline. Universal and Enhanced do not share an accuracy number. October recordings have already been inspected and are not a blind test. Holdouts `hush_20260917_205513` and `hush_20260920_200635` stay sealed.

`docs/ohush/swarm/SCOREBOARD.md` and `docs/ohush/research/ACCURACY_LADDER_001/NEXT_DECISION.md` were written before `EXACT_AUDIO_CONFIRM_001`. They still name candidate retrieval plus waveform verification. That later report retires the build. Do not treat the earlier next-decision as the current instruction.

## Read in this order

1. `docs/ohush/tnf_prime_handoff/STATUS.md`
2. `docs/ohush/swarm/SCOREBOARD.md`
3. `docs/ohush/research/UNIVERSAL_V1/REPORT.md` and `results.json`
4. `docs/ohush/research/FINGERPRINT_BOUNDED_QUERY_001/REPORT.md`, `NEXT_DECISION.md`, `results.json`
5. `docs/ohush/research/CAUSAL_REFERENCE_PARITY_001/REPORT.md`, `NEXT_DECISION.md`, `results.json`
6. `docs/ohush/research/EXACT_AUDIO_CONFIRM_001/REPORT.md`, `NEXT_DECISION.md`, `results.json`, `pair_inventory.csv`
7. `docs/ohush/research/REFERENCE_CONTENT_AUDIT_001/REPORT.md` and `matched_pairs.csv`
8. `docs/ohush/research/IDENTITY_RETURN_001/IDENTITY_RETURN_001.md` and `NEXT_DECISION.md`
9. `docs/ohush/research/LABELING.md`
10. `docs/ohush/research/ACCURACY_LADDER_001/NEXT_DECISION.md` last, as the stale pointer

Listening clips and the Universal v1 decision logs are not in this zip. `reviewer_label` is null on the content-audit pairs. Nobody listened for the confirm pass.

## Do not

- Authorize a mute or change live playback from play.
- Retune count 10, count 200, cosine 0.25, or the confirmation line 0.85.
- Average the bounded-query scores 33, 137, 92, 26, 102 with the confirm scores 52, 192, 43, 35, 178. They are different reads.
- Treat a supplied waveform lag as a detector. The parity check was told where the reference sits.
- Build the bounded-latency candidate generator. Exact audio confirm closed it.
- Call the 95.1 remaining program seconds a collision cleanup. They are copies at or above 0.85, including the FanDuel promo the gold calls program.
- Sum fingerprint seconds and voice-guard seconds.
- Open the sealed holdouts or edit gold.
- Score the 8 October live mute log against `hush_20261008_205100`. The clocks are not joined, and the tape is still unmarked.
- Recommend a live change for tonight's Prime game. This packet is the research stop, not a deployment.

## What to return

1. Check `EXACT_AUDIO_CONFIRM_001` against `results.json`. Name any figure in `STATUS.md` the file does not support. Say whether commercial coverage under half of 3,903.2 is what the file shows, and whether that is the predeclared stop.
2. The parity `NEXT_DECISION.md` still says to build candidate retrieval plus waveform verification. The confirm `NEXT_DECISION.md` says not to build the bounded-latency generator. Which file is later, and does the later file close the earlier recommendation? Name what, if anything, is still open.
3. Keep the two causal Thursday rows apart. Bounded query: 33, 137, 92, 26. Confirm, audio available at the decision: 52, 192, 43, 35. Is any fingerprint variant in this zip both causal and at or above 200 on those Thursday windows without being told the alignment?
4. The FanDuel hops at 75, 80, 90, and 95 seconds stay above 0.85, on a span the gold calls program. What next step is allowed that is not a new threshold fit on this ledger?
5. From `UNIVERSAL_V1/results.json` and `LABELING.md`: which Thursday Prime claims are allowed before interval marks exist? Use the identity-return file for the Prime return figures, and do not import them into the Universal v1 seconds.
