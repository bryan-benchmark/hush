# EXP005 result

Status: **measured, not closed**. Spec `exp005-v1` was frozen before this run's ledger was opened. The phrase lists, the 0.85 similarity rule, the exact commercial vocabulary, and the 15 s / 180 s semantic window were not changed after the cues were known.

Session `hush_20260914_212529`, 0–6899 s. This ESPN recording is development data. A result here is not independent confirmation.

The transcript is ASR dictation from faster-whisper `medium.en`, temperature 0, beam size 5, no initial prompt, no voice-activity filter. It is not broadcast closed captions. 16,009 words. Exp001 through Exp004 were not fused in.

## 005A — transition phrases

**Negative for departure. Exact “welcome back” is a rare return corroborator. The generic phrases are not standalone evidence.**

None of the 15 starts has a departure phrase in (start−10 s, start+15 s]. All 24 departure cues fall in ordinary programming, about 17 per program hour. The list never produced “we'll be right back,” “we'll be back,” “stay with us,” “after the break,” or “commercial break.” What it did produce is “coming up” (11), “timeout” including “time out” (10), and “after this” (3). Those are football words.

Four ends have a return phrase in (end−5 s, end+15 s]. Three of those are an exact “welcome back to,” at about 0.9 s, 2.0 s, and 2.5 s after the end. The fourth is “back to,” 9 s later. The other 21 return cues are in ordinary programming, about 15 per program hour, and most of them are “back to.” Two more exact “welcome back” lines occur during play and not at an end.

The matcher was not edited. Exact “welcome back” and “welcome back to” keep a place as a rare, high-specificity return corroborator. “back to,” “timeout,” “coming up,” and “after this” do not. They are ordinary football language, and they are not useful by themselves.

## 005B — commercial vocabulary

**Denser in pods. Too sparse to mark a pod by itself.**

32 of 47 vocabulary hits fall inside pods. That is 1.06 hits per pod minute and 0.18 per program minute, about six times as dense. Forty-seven hits across the whole game means many commercials do not say any of these words, or the ASR did not catch them. This can corroborate a departure that something else already found. It does not find the departure.

## 005C — semantic continuity

**Strong-ish for departure from the recent language. Promising as memory during the pod. Partial for return.**

On 14 of 15 starts, the median semantic distance in the 30 s after the start is higher than in the 30 s before. The one exception is the short break at 1030 s. Pod windows have median distance 0.85. Program windows have median 0.52. That is the same shape as the PANNs result: the program has a world, the commercials replace it, and the old world comes back only gradually.

The frozen snapshot is an audit that uses the known start. It is the mean of semantic windows ending in (start−210 s, start−30 s], taken after the unlabeled scores were frozen. It shows that the representation contains useful return information. It does not show that OHush can choose that snapshot blindly. There is no operational freeze for the semantic cloud. During the pod that audit distance sits about 0.78 to 1.00. The same windows, compared with themselves, sit about 0.31 to 0.42.

In the first 30 s after the end, some breaks fall to about 0.45–0.55 and some stay high. Four complete breaks are still far from the pre-break cloud there (the ends near 1767 s, 3290 s, 3785 s, and 4379 s). Ten breaks do touch the snapshot's own level within 120 s. Those latencies run from about 18 s to 86 s. Touching the level once is not the same as the return window sitting there: the end near 4379 s touches it at 21 s while the 30 s median is still 0.96.

## Reading

Departure is the easier problem on this recording. Speakers, the audio embedding, and this semantic embedding all say the thing being watched disappeared. Ad vocabulary and the low-level boundary support that. They do not carry it.

Return is a different problem. Exact “welcome back” is rare and specific. Frozen audio identity and frozen semantic identity both stay far during the pod and come back only partly, and often late. Speaker return, as currently scored, is noisy. The commercial clock is a weak prior. None of those is an unmute by itself.

A later return rule, if the same pattern shows up on other programs, would ask whether enough of the old program has come back at once and stayed back: frozen audio similarity, frozen semantic similarity, a known program speaker, a few seconds of persistence, an optional “welcome back,” and a plausible duration. Uncertainty stays on PLAY. That rule is not built here. The semantic snapshot above cannot be one of its inputs until a blind way to choose the snapshot exists.

## Stop

Feature discovery on this ESPN game stops. No further signal will be invented from it, and Exp006 will not be designed from it. The next measurement is replication, unchanged and blind, on three new sessions: Prime football, linear scripted television, and ad-supported streaming scripted television. The critical frozen runs are Exp002, Exp003, Exp003b, and Exp005. Exp001 and Exp004 can be scored. They are not the question.

The question on each new session is whether the program develops speakers, an audio world, and a semantic world; whether a pod removes that context; whether keeping the old identity leaves the pod distinguishable; and whether that identity comes back after the break. Fusion waits until those three replications exist.

## Where the numbers live

- Unlabeled plot: `hush_20260914_212529/language.png`
- Labeled plot: `hush_20260914_212529/plots_labeled/semantic.png`
- Cues: `cues.json`
- Vocabulary hits: `vocabulary_hits.json`
- Per-break table: `overlay_breaks.csv`
- Pre-break cloud: `overlay_frozen_language.csv`
- Counts: `overlay_summary.json`
