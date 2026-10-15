# Hypotheses, ranked, not implemented

Baseline measurements of the live algorithm do not exist yet. Thursday has no interval gold. The closed games already have research overlays, and those specs stay frozen. None of the hypotheses below were coded.

The smallest next experiment that can actually fail is not a new model. It is a sample-locked join for `run19` (`audio_0023.wav`, 0.30 s duration delta) and a blind interval pass on that one run. If the start of that file is not the start of `run19`, the join is rejected and labeling waits.

## H3 — Trusted voice, first among the signal hypotheses

Question: after the similarity contradiction is refused, does a verified live match still mark return, and do the stored ids name announcers?

Why first: the October 8 flap split into a false flag (similarity 0.15, now refused) and a high similarity on the wrong cluster id (0.87 and 0.71, still allowed). The excerpts in `booth_excerpts/` are the falsifier. A listen that finds an ad voice in `c0016` or in `.booth.json` kills prototype-return. A listen that finds announcers keeps it, with the 2.5 s human-cover hold.

Baseline: current `state._booth_match`. Dataset: the excerpts, then a later sample-locked run. Frozen: Exp002. Do not delete ids from the listen notes alone; a second listener confirms before any id is removed.

## H2 — Frozen multi-prototype program memory

Question: does a protected memory of several program sound-worlds separate an ad-to-ad cut from an ad-to-game cut better than the adaptive 180 s distance?

Already shown, and not to be retuned: on ESPN and Prime the frozen cloud stays high inside pods after the adaptive score has relaxed; on August Hulu the gap is small. The next falsifier is one new football broadcast (FOX or NBC), blind, after its intervals exist. Not another threshold on ESPN.

## H1 — Faster departure

Question: can a causal short-window change, spectral or embedding, mark a suspicious boundary sooner than speaker-collapse (median 9.6 s on ESPN, about 7 s on Prime) without a false-cover rate the product cannot accept?

Run only on a closed development range, causal (no future audio), then once on Prime without refitting. Stop if the false-cover incidents per program hour are not lower than muting on the current audio distance alone.

## H4 — Repeated-ad fingerprints

Question: can a small local fingerprint hit the same commercial in two games at high precision, and can it avoid calling a sponsor bumper or a theme the same thing?

Falsifier: matches on ESPN versus Prime that a listener tags as the same spot, against a set of recurring music and bumpers that must not match. A known spot ending is not a pod ending. This does not see a commercial the library has never heard.

## H5 — Cold-start classifier

Question: when the device has no program memory yet (the first ~35 s, or a recording that opens on an ad), can a conventional classifier or a compact audio model say "commercial-like" without a reference?

Last. It is the only hypothesis aimed at the 23-second miss. It waits until H3's identity listen and a real Thursday gold slice exist, so a cold-start hit can be scored as commercial-heard time rather than as a new threshold.

## Explicitly not next

A language model, a new speech model, new hardware, a product app, vibe tuning, an adaptive-distance return rule, or an Exp006 designed from the ESPN game.
