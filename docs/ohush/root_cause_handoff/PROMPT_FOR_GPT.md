# Root-cause the OHush record

You are auditing a closed research record and naming the next measurement. You are not building it.

Read `docs/ohush/root_cause_handoff/CATALOG.md` first. Then open the report it cites for any number you use. If the catalog and the report disagree, the report and its json win. Quote the file.

Today is 15 October 2026. No mute is authorized. Universal v1 is the research baseline. Playback stays play.

## What to produce

One memo. Four parts, in this order.

1. **Contradictions.** List claims in older handoffs that a later file refutes. Start with `docs/ohush/swarm/MASTER_RESEARCH_STATUS.md` sections 8 and 10. Add any catalog figure you cannot find in the cited json.

2. **Why the fast starts and the slow returns are different problems.** The DSP scan hits 86 of 136 football starts within 3 seconds and still leaves 6,406.8 ad seconds in the other 50. The human listens in `docs/ohush/research/BOUNDARY_EVIDENCE_001/REPORT.md` say those misses are not a 200 ms gold error: the misses and the hits have the same outro, hole, and spot. Join `docs/ohush/research/CONTINUOUS_DSP_001/starts.csv` to `docs/ohush/research/BOUNDARY_EVIDENCE_001/cue_table.csv` on session and boundary time. Say what, if anything, differs between on-cut misses and on-cut hits in the columns that already exist. Do not invent a feature. If the columns do not separate them, say so.

3. **Return root cause.** IDENTITY-RETURN-001 already showed that a frozen pre-break cloud comes back slowly, and that a clean causal freeze exists on a minority of breaks. Known-ad fingerprints at count 200 are specific and sparse, and losing an ad match is not a program return. Verified announcer enrollment is 0. The 20-clip return page has no judgments. Say which of those is the binding constraint, in missed program seconds, using only numbers already published. Name the file for each number.

4. **One next measurement.** Specify it so it can be frozen before anyone looks at the outcome. Include the sessions, the clock, the information the decision is allowed to have seen, the commercial seconds and program seconds that would count as success, and the result that would retire it. The comparison target is the Universal v1 ledger, not a new isolated score. Success has to cover commercial seconds the current baseline misses without covering program, including RedZone.

The NBC listen at `hush_20260909_213047` t=240 s found an AWS break the gold does not contain. Treat that as one confirmed miss. Do not relabel the ledger. You may say how to search for more of them without changing gold.

## Do not

- Unseal `hush_20260917_205513` or `hush_20260920_200635`.
- Fit a threshold on the October sessions. They were already inspected.
- Retune Exp002, Exp003, Exp003b, Exp005, the DSP thresholds, the CNN14 logistic, the mel logistic, the fingerprint counts, the anomaly distance, or the microgap floors.
- Recommend a live mute, a Universal v5, or another generic similarity cutoff.
- Score Thursday's `decisions.jsonl` as commercial accuracy. That clock is not the gold clock, and the track has 32 resets.
- Treat `.booth.json`, a cluster id, or `booth_present` as a verified announcer.
- Call an oracle-start result operational. Those rows are told the commercial start.
- Re-embed audio, re-run ASR, or rebuild a fingerprint index. If the answer is not in the files, the measurement is missing. Say that.
- Paste a new detector, a new architecture, or a threshold sweep.

## Clocks, once

Truth times are recording seconds. August Hulu features are recording time minus 300 s. RedZone `hush_20260913_150934`, 0–7200 s, is the negative control and has no commercials. A coverage row with `fully_annotated: true` was heard through. No commercial in that span means no commercial.

Disagree where the files disagree. Cite the path.
