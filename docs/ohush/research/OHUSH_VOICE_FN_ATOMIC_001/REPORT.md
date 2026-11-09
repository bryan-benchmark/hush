# OHUSH_VOICE_FN_ATOMIC_001

The mute opens on two different failures, and they are not the same size.

On the development rows, 33 false mutes totaling 278 seconds already had a finished ECAPA cosine at or above 0.25 in the second the mute opened. In 32 of those 33 the runner-up was at least 0.15 lower. The winner was Kirk Herbstreit on 16, Al Michaels on 11, Clarissa Thompson on 4, and Andrew Whitworth on 2. The mute rule never reads that cosine. That is a decision failure. The person is still your label to confirm. The margin between enrolled names is already wide.

The seven September episodes that never reached 0.25 are a different 85 seconds. One has no reference yet. One has speech and no finished embedding window. Two, 40 seconds, are full of detector speech and no enrolled name gets above 0.18. Those are the turns worth labeling before anyone touches a model, a threshold, or a mute rule.

Nothing here was trained, retuned, or put on the television. The cosine line is still 0.25. The holdouts were not opened. Sixteen queue rows are marked `eval` and are not in the counts below.

## What the model actually received

The recording is 48 kHz stereo. The embedder averages the two channels and resamples that one stream to 16 kHz. Silero, at its frozen settings, marks speech. ECAPA then sees a 2.0 second window, hopping 1.0 second, and only if that window holds at least 1.0 second of speech. The cosine is to the Thursday prototype. A clip from an earlier game is available at kickoff. A clip from the same game becomes available when that clip ends. September 24 has no earlier Thursday game in the label file, so its prototype starts empty.

A score is usable when the window ends. A window that finishes after the mute ends cannot explain that mute. Names below are the enrolled name with the highest cosine. They are not a person you have confirmed.

## October 9156, the dropped pass

The mute is 9156.0–9169.0, 13 seconds, prior note announcer commentary. The 0.14 and the 0.70 are real, and they are 12 seconds apart.

| Window | Usable at | Speech in the window | First | Second |
| --- | ---: | ---: | --- | --- |
| 9153.2–9155.2 | 9155.2 | 0.8 s | Clarissa Thompson 0.144 | Tony Gonzalez 0.096 |
| 9154.2–9156.2 | 9156.2 | 1.7 s | Tony Gonzalez 0.219 | Andrew Whitworth 0.162 |
| 9156.3–9164.3 | through 9164.3 | 2.0 s each | Gonzalez or Whitworth, 0.07–0.20 | the other, lower |
| 9163.3–9165.3 | 9165.3 | 2.0 s | Tony Gonzalez 0.432 | Andrew Whitworth 0.395 |
| 9164.3–9166.3 | 9166.3 | 2.0 s | Andrew Whitworth 0.556 | Tony Gonzalez 0.480 |
| 9166.3–9168.3 | 9168.3 | 2.0 s | Andrew Whitworth 0.700 | Tony Gonzalez 0.447 |

The 0.144 is usable 0.8 seconds before the open, and it is under 0.25. The first window that clears 0.25 is usable at 9165.3, 9.3 seconds after the open, and Gonzalez leads Whitworth by 0.037. Whitworth takes the lead at 9166.3. The 0.700 is usable at 9168.3, with 0.7 seconds of the cut left. Those later windows are full 2-second speech windows, the same length as the windows that scored 0.10. The score moves because the audio in the window changes. Who is in it, and whether music or a second voice entered, is open. Queue clip `fn0054`.

Lowering 0.25 would not name one person here. At the first crossing, both names are above 0.25. The 0.700 cannot keep the mute from opening.

## The seven September episodes

These are the misses from the false-mute inventory, not a false-negative rate over all announcer speech.

| Clip | Span | Seconds | Detector speech | Finished windows | What the cosine did | Class |
| --- | --- | ---: | ---: | ---: | --- | --- |
| fn0001 | 64–73 | 9 | 6.8 s | 4 | every score empty | missing reference |
| fn0006 | 4532–4546 | 14 | 4.4 s | 4 | Herbstreit 0.098, Michaels 0.058 | below 0.25 |
| fn0025 | 5574–5578 | 4 | 2.2 s | 0 | next window, at 5579.5, is Thompson 0.467 vs Whitworth 0.083 | no finished window |
| fn0008 | 6266–6292 | 26 | 25.8 s | 26 | Whitworth 0.180, Gonzalez 0.065 | below 0.25 |
| fn0009 | 6592–6606 | 14 | 14.0 s | 14 | Whitworth 0.177, Gonzalez 0.055 | below 0.25 |
| fn0010 | 6796–6807 | 11 | 5.0 s | 4 | Thompson 0.206, Herbstreit 0.193 | below 0.25 |
| fn0011 | 6818–6825 | 7 | 4.7 s | 2 | Whitworth 0.148, Herbstreit 0.125 | below 0.25 |

September's first usable references are Al Michaels at 183.4 seconds (a crowd clip) and Kirk Herbstreit at 201.6 seconds (a loud clip). Clarissa Thompson's first clip ends at 4600, Andrew Whitworth's at 4750, Tony Gonzalez's only clip at 5780. At 64 seconds there is nobody to compare against. The four windows and 6.8 seconds of speech are real. The miss is the empty prototype.

The injury desk, fn0008, is the opposite. By 6266 both Whitworth and Gonzalez have a reference, Gonzalez's only one. Twenty-six windows finish inside the cut. Twenty-six of them are full of detector speech. Whitworth stays first, and 0.180 is the best he gets. Gonzalez stays near 0.06. This is not a pause, not a missing window, and not two names trading the lead above 0.25. The prior note says other commentary. If you hear an enrolled announcer, the embedding missed that voice for the whole turn. If you hear someone else, it is not a false negative.

fn0009 is the same pattern for 14 seconds of uninterrupted detector speech, same two names, same distance under the line.

fn0025 is window timing. The detector found 2.2 seconds of speech and no embedding window finished before 5578. The next window ends at 5579.5, 1.5 seconds after the cut, and Thompson leads Whitworth by 0.38. Once a window exists, the enrolled names separate. During the cut, none does.

fn0006, fn0010, and fn0011 have some detector speech, two to four windows, and a top score between 0.10 and 0.21 with the runner-up close behind. The winning name is not meaningful at that height. Herbstreit has been enrolled since 202 seconds, so fn0006 is not an empty prototype.

## Where the seconds sit

Development rows only. A class describes the cosine and the speech detector. `identity_verified` is false on every row.

| Rank | What happened | Episodes | Seconds | Confidence |
| --- | --- | ---: | ---: | --- |
| 1 | A cosine at or above 0.25 had already finished in the opening second, and the runner-up was at least 0.15 lower | 32 | 262 | High that the decision ignored a separated enrolled name. The person is unlabeled. |
| 2 | The first cosine at or above 0.25 finishes 1 to 3 seconds after the open | 15 | 162 | High on the clock. One of the 15 is Whitworth 0.30 versus Gonzalez 0.21. The other 14 are a wide margin, mostly Michaels. |
| 3 | The first such cosine finishes more than 3 seconds after the open | 9 | 146 | Mixed. Herbstreit at 0.58 arrives 13.8 seconds into one cut and 15.8 seconds into another, with Michaels far behind. The dropped pass is in this row and is a name collision. |
| 4 | The first such cosine finishes within 1 second after the open | 7 | 82 | High that this is the 2-second window ending one hop late. Six of the seven are a wide margin. One is Whitworth 0.28 versus Gonzalez 0.23. |
| 5 | Detector speech fills the cut and no enrolled name reaches 0.25 | 2 | 40 | High that the embedding stayed far from every enrolled voice. Low on the cause until you name the speaker. |
| 6 | Detector found no speech and no window was written | 14 | 87 | Ten of these, about 49 seconds, carry a prior note of stadium. Two commentary spans, 12 seconds and 19 seconds, also have zero detector speech. |
| 7 | Windows finished and the best cosine stayed under 0.25, on partial speech | 7 | 55 | Low. Includes a 5-second bumper whose cosine is about zero, and October 9332, where Whitworth reaches 0.61 only at 9340, after the cut, with Gonzalez at 0.50. |
| 8 | Speech, and no reference had started | 1 | 9 | High. |
| 9 | Speech, and no embedding window finished during the cut | 1 | 4 | Medium. The following window separates Thompson cleanly. |

The one decision-ignored row with a smaller gap is September 6616–6632, Whitworth 0.26 versus Gonzalez 0.11. Whitworth still leads. It is a low score, not a swapped name.

## Speaker by speaker

Al Michaels and Kirk Herbstreit are the stable pair. When either name wins, the next enrolled name is usually far below, on the ignored opens and on the short delays. Their September references exist from about three minutes in. The long delays at 1396 and 4200 still resolve to Herbstreit at 0.58 and 0.54. What those cuts need is a label for when his speech actually starts. The cosine, once it arrives, is not swapping him with Michaels.

Clarissa Thompson is stable when a window finishes. Four ignored opens name her with a wide margin, including 0.67 versus 0.11. The 4-second miss at 5574 is a window that does not finish in time.

Andrew Whitworth and Tony Gonzalez are the pair the prototype does not separate. Gonzalez has one September reference, available at 5780. On the dropped pass the lead changes inside full speech windows, and the first clearance has them 0.037 apart. The same pair collided on the labeled Gonzalez clip in the voice-identity run: his own reference scored 0.59 and Whitworth scored 0.67, so a different threshold still picks Whitworth. That is a reference problem.

The injury desk does not belong to that collision. Whitworth leads by a wide gap and neither name is close to 0.25.

## Enrollment clips, including the four songs

The queue includes the four September song clips and the later song clips, so you can hear them. The voice-identity run already compared each September song clip, at 3 seconds, with the other clear clips of that person:

| Clip | Marked person | Cosine to self | Cosine to the next person |
| --- | --- | ---: | ---: |
| e0101 | Kirk Herbstreit | 0.63 | 0.08 |
| e0112 | Al Michaels | 0.65 | 0.04 |
| e0116 | Clarissa Thompson | 0.54 | 0.13 |
| e0124 | Andrew Whitworth | 0.65 | 0.46 |

Each song clip is closer to the marked person than to anyone else. Whitworth's margin is the thin one. Removing the songs did not change the October clear-clip result. They are a poor kind of reference. They are not what left the injury desk at 0.18, and they are not what called the Gonzalez clip Whitworth.

## Two paths

Path A is the table above: the speech detector, the 2-second windows, and the frozen embedding, scored when the window ends.

Path B was not run. Every queue label has empty `speech_start_s` and `speech_end_s`. Feeding the same ECAPA the speech you mark is the test that separates a bad window from a voice the prototype cannot match. The injury desk and the dropped pass are the first two cuts to run that way. Inventing those boundaries from the detector would only repeat path A.

Recall at 1, 2, and 3 seconds after speech begins is waiting on those boundaries. The clock we have is seconds after the mute opens, which is a different zero. Onset recall on the owner's existing 3-second marks is a different set of clips and stays in the voice-identity report.

Commercial windows that already clear 0.25 were sampled at least three minutes apart: 15 clips, `fn0101` through `fn0119` on the development split. Several sit on the line (0.250 to 0.255). The highest is Clarissa Thompson at 0.44. Who is speaking in those ads is unlabeled, so they are not yet counted as false matches. The earlier finding still stands beside them: on labeled other-show voices, Joe Buck clears 0.25 against this Thursday prototype often enough that one line cannot keep him out and still keep Michaels.

Failure rates by music, crowd, and clean speech are empty on purpose. The label fields are blank so the model's guess cannot become the label.

## What to label

The queue is 144 playable clips in `queue.jsonl`, with the wav next to each row. Fill `label` and leave `why_queued` alone. The question is who is talking, not whether OHush should mute.

- `speaker`: Al Michaels, Kirk Herbstreit, Andrew Whitworth, Clarissa Thompson, Tony Gonzalez, Ryan Fitzpatrick, or other / unknown
- `background`: clean, music, crowd, or other mixed
- `overlap`: yes or no
- `certainty`: certain or uncertain
- `speech_start_s` and `speech_end_s`: session time for that speaker. A second person gets a note, or a second pass, with their own bounds.

Label the development misses first. In order: fn0001, fn0006, fn0008, fn0009, fn0010, fn0011, fn0025, then the dropped pass fn0054, then the two silent commentary spans fn0007 (5554–5566) and fn0023 (9803–9822). The exact windows the embedder saw for those cuts are under `windows/`. The 16 `eval` rows stay out of the next comparison.

## The one correction the seconds support

The 32 wide-margin ignores are 262 seconds. Seven of those seconds are Andrew Whitworth. The Michaels, Herbstreit, and Thompson share is 31 episodes and 255.3 seconds. That figure is a retrospective opportunity, not a confirmed identity and not a measured saving. OHUSH_VOICE_TRUTH_002 replays the three-name rule and does not install it.

Leave Whitworth and Gonzalez out of that rule until the reference can separate them. Leave the 40 seconds of full-speech misses alone until you say who is speaking. Do not move 0.25. A lower line accepts both names on the dropped pass, and a higher line still calls the labeled Gonzalez clip Whitworth.
