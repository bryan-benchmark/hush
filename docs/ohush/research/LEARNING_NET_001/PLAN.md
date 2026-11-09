# Learning net

The next mute rule is a conclusion of this net. It is not an input. Each probe answers one question about the recordings. None of them is allowed to pick a cutoff on October.

## What is already known

These are settled. Running them again does not teach anything new.

- A run that hides any second of the game is broken and has no accuracy. Play, which mutes nothing, holds 0 commercial seconds. The full football commercial total is 17,648.4 seconds.
- One shared detector, past audio only. Windows of 2, 5, and 10 seconds are cached for the bridge games. The two sealed holdouts stay closed. Nothing here mutes the television.
- Fit on three pre-October games: NBC Sept 9, NBC Sept 13, Prime Sept 24. Lock a cutoff on ESPN Sept 14. Score October after that, including Thursday Night Football on Oct 8. The zero-ad control is `hush_20260913_150934`.
- An ESPN cutoff that merely maximizes commercial seconds hides other games. The absolute 5-second score holds 145 ESPN commercial seconds and 233.6 October program seconds. Requiring two agreeing seconds holds 280 and hides 753.6, plus 2 seconds of the zero-ad control. Comparing each second with the past median of the same game holds 422 and hides 337.6, plus 13 seconds of the control.
- That last ESPN cutoff also hides the training games: 7.0, 8.4, and 21.9 program seconds. Raising it until every pre-October game stays on leaves 122 ESPN commercial seconds, with 0 program seconds on those four games. October has not been scored at that cutoff.
- Generic similarity to audio from before the break does not find the return. A fingerprint reader that has to be told where to look is not a detector. Those stays retired.

## The five questions

Each probe below maps to one of these. A result that does not change one of them is noise.

1. **Repeat or new.** What fraction of commercial seconds is a copy of an ad already heard in an earlier game, and what fraction is a new spot?
2. **Separate or shifted.** Inside one game, do commercial seconds and program seconds land in different parts of the score? Across games, does the same cutoff still leave the game on?
3. **Which sound fails.** When a legal rule hides the game, is that second crowd, booth talk, a song, a network promo, or the edge of a break?
4. **How fast.** At 2, 5, and 10 seconds of past audio, how much do commercial and program already separate? The Thursday ceiling is already known: a perfect mute that waits out the whole window still leaves 46, 115, or 230 seconds of that game's ads audible.
5. **What a frozen tagger already says.** The cached AST model was trained on AudioSet's event classes. Its class head was not used. Do those class names already split ads from the game, and do they name the seconds the score got wrong?

## Wave 0

Run these on the caches and the recordings already on disk. No new encoder. No cutoff is chosen from October. Descriptive numbers on October are allowed. A mute rule is not.

### 1. Ranking versus cutoff

For each cached window and each bridge game, compute a ranking score between verified commercial seconds and verified program seconds. Report the score per game. Do not turn it into a threshold.

Read it this way. A high score on Sunday night means the embedding already separates that game and the failure is the cutoff traveling badly. A low score means this embedding cannot hear the difference on that game, and a new encoder is the relevant next feature, not a cleverer threshold.

### 2. The repeat map

Take every verified commercial second in the three training games. Find the nearest commercial second in a different game, and the nearest program second, using the cached vectors. Declare "this is a copy" from training pairs only: seconds inside the same ad should match each other, and program seconds should not. Then, once, measure what fraction of October commercial seconds meet that copy bar, and what fraction of program seconds do too.

Read it this way. A large October copy fraction means a memory of heard ads can cover a measured share of future ads, and the leftover new spots are the scaler's real job. A small copy fraction means memory of past ads does not scale, and the detector has to recognize a spot it has never heard. Program seconds that also match the copy bar are false copies and count against the idea.

### 3. Name the failures

Run the AudioSet class head on the same AST checkpoint, frozen. Compare the class mix on verified commercial seconds, verified program seconds, and the program seconds already hidden by the ESPN past-median rule. Keep the top classes and the seconds.

Alongside that, listen to a fixed sample: 20 hidden program stretches and 20 missed commercial stretches, one short note each, from a list such as crowd, booth, song, promo, silence, or edge of a break. The notes are the label. The model tags are the hypothesis.

Read it this way. One dominant class or note means the next feature only has to fix that sound. A mix means the errors are not one phenomenon and a single new model will not clear them all at once.

### 4. Boundaries

At each gold commercial start and end, measure loudness and low-energy gaps in the surrounding second. Compare those with the same measurement on ordinary program seconds and ordinary commercial seconds, using the training games and ESPN.

Read it this way. A gap that shows up at breaks and almost nowhere else is a boundary cue worth a later probe. A gap that is common in the game means silence-at-the-break is not a football detector.

### 5. One legal rule, scored once

Score the past-median rule at the cutoff that leaves all four pre-October games on: 10-second window, 180-second memory, median of the past, threshold 18.40. October and the zero-ad control are the test. Do not move the threshold after seeing them.

Read it this way. Zero program seconds on both means this family can travel, and the next work is covering more commercial seconds without giving those seconds back. Any program second means the features still call some later game audio more ad-like than the hardest pre-October program second, and the feature probes above are the ones that say what to change.

## Wave 1

Start only the branches Wave 0 actually opens. Leave the others unrun.

| If Wave 0 says | The one next build |
| --- | --- |
| Ranking is strong inside each game, and only the cutoff fails | Stay on these vectors. A rule must keep every pre-October game at 0 program seconds, then survive October once. |
| Ranking is weak on a later game | One frozen general-audio encoder, Dasheng-base first. Repeat probe 1 on its vectors. Do not fine-tune it on three games. |
| Most commercial seconds are copies, and program seconds are not | A copy-matcher whose coverage number is commercial seconds matched, with playback whenever there is no copy. The new-spot remainder stays on the classifier. |
| Failures are one named sound | A probe aimed at that sound, still locked on the pre-October games. |
| Breaks have a distinct edge and the middle of the game does not | A boundary cue as a separate measurement, not a mute policy, until it has its own false-accept count on program and on the zero-ad control. |

OpenBEATs is the alternate encoder if Dasheng-base is a poor fit to run. Dasheng-1.2B waits until the base encoder has failed the same ranking probe. A speech-to-text classifier waits until probe 3 says the confusions are words the booth and the ads share. A bigger model is not the way to find out which of those sentences is true.

## What stays out of the net

- Per-show models.
- Fine-tuning a large model on three broadcasts.
- Choosing a threshold, a window, or a memory from October.
- Opening the sealed holdouts.
- Retuning Universal v1, the frozen CNN14 distance, or the retired fingerprint counts.
- Changing the live mute.
- Treating a broken run's commercial seconds as accuracy.

## Order

Probes 1, 2, and 4 can run together from the caches. Probe 3 needs one GPU pass of the class head and one listening session. Probe 5 is a single replay. Wave 1 starts when those five numbers exist, and it starts as one branch.
