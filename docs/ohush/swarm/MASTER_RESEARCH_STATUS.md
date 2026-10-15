# Master research status

Date: 2026-10-14. Champion: no authorized mute. Research baseline: Universal v1. No live change was made.

The three lanes stay closed. The first complete causal timeline is `docs/ohush/research/UNIVERSAL_V1/`. It does not retune CNN14, the fingerprint count, or the 18 dB dip.

## 1. Best causal end-to-end result

Universal v2 failed its development gate and was not promoted. The selected policy stays play. See `docs/ohush/research/UNIVERSAL_V2_CONTENT_STATE_001/REPORT.md`. Scorable football commercials are 17,555.7 s, not the gross 17,648.4 s.

Universal v3 embeddings also failed. Frozen CNN14 penultimate vectors, with thresholds chosen on the same earlier games, have no calibration point that covers commercial audio inside 10 program seconds. On October the rule covers 0 new commercial seconds and loses v1's 25.0 s. See `docs/ohush/research/UNIVERSAL_V3_EMBEDDINGS_001/REPORT.md`. October was already inspected, so that number is not a blind test.

Universal v4 asked a different question: separate causal heads for leaving the game and for returning, with subsecond features, one-to-two second context, a 30-second delay line, and the frozen CNN14 probability as an input. No feature set covered any commercial audio inside 10 program seconds on the calibration games. The playback rule stays play. On October it covers 0 new commercial seconds and loses v1's 25.0 s. See `docs/ohush/research/UNIVERSAL_V4_BROADCAST_SEQUENCE_001/REPORT.md`.

Universal v1 is the first play/cover timeline. On football it hears 17,530.7 commercial seconds, covers 25.0, and covers 0 program seconds. It touches 2 of 136 pods and lets go of both while the commercial is still playing. Receipts are in `receipts.jsonl`. The full ledger is the v1 report.

That is a research baseline, not a promoted mute. The references are gold commercials from earlier recordings. Enhanced was not run: no feed was aligned, and it has no accuracy number.

The DSP ceiling remains the accounting of the candidate stream, not a timeline:

- Within 3 seconds, pretending the gold end is known: 86 of 136 pods muted, 6,479.6 ad seconds still heard, 6,406.8 s of that in 50 missed pods.
- Within 30 seconds, same pretend return: 1,116.9 ad seconds heard.
- Applying this stream's 1.12 s median delay to every pod leaves 152.3 ad seconds. That is a benchmark for this scan, not a proof that every reactive detector is at least that slow. A faster detector could beat it. It would still have to do so without hiding the game. The 99.99% budget for a three-hour game is 1.08 seconds, and for this corpus it is 8.51 seconds.

## 2. Ten largest remaining sources of user-visible error

Ranked by seconds or by the fact that the seconds were never measured:

1. Missed fast starts: 6,406.8 ad seconds (50 pods with no DSP hit inside 3 s).
2. False mutes if a DSP episode were the mute: 5,862 s of football program, 3,993 incidents.
3. The same policy on RedZone: 1,369 s hidden in a zero-commercial control.
4. Late detection under a 30 s wait and a perfect return: 582 s.
5. Program return: unmeasured. The ceiling pretends the gold end is known.
6. The 73 s of delay on pods already caught inside 3 s. Real, and the wrong next investment.
7. Fingerprints at the published count of 200 add almost no coverage inside 5 s.
8. Sign-off phrases mark 12 of 133 starts and are concentrated in one broadcast. They do not mark the return.
9. A recoverable 40 ms dip marks 4 of 136 starts inside 1 s and still fires 134 times an hour in football.
10. Television-timeout context: not measured. It would be Enhanced, and it is not in the audio.

## 3. Which independent signal removed the most error

None has been promoted, so none has removed listener error. As a *candidate*, the only signal that touches the 50 DSP-missed starts without being fit as a new threshold is the chronological fingerprint at count 10: 13 of 41 evaluation misses inside 5 s, plus 5 of 9 ESPN misses. It misses its false-identification budget (about 2.08 per probed program hour). Count 200 stays inside that budget and recovers 0 of 121 evaluation openings inside 5 s. The spoken sign-off is specific in the sampled windows (0 of 135 controls) and rare.

## 4. Starts and returns

Starts, DSP, football: 86/136 within 3 s, 131/136 within 30 s, median delay on hits 1.12 s. Five starts have no alarm inside 30 s.

Returns: not measured causally. A fixed 120/135 s timer already failed as an unmute. Median football pod 132.8 s, maximum 417.9 s. Sign-off phrases are start cues. Matching the previous advertisement does not show that the game has returned.

## 5. False alarms that remain hard to reject

Ordinary football edits. The DSP stream produces about 215 episodes an hour in football and about 474 in RedZone. A 40 ms recoverable dip is quieter on RedZone (4/h) and still far above the gate on football (134/h). Replay packages, crowd swells, and booth-to-booth cuts sit in that pile. CNN14 distance did not separate them once the threshold left ESPN. A landmark match against a future recording is leakage; a match against an earlier commercial can still be a program passage that also aired inside an ad.

## 6. What generalizes

The level drop near many boundaries is real on more than one network (descriptive median drop about 42 dB at football starts versus about 6.6 dB in distant program audio). The *recoverable short dip* does not generalize as a detector. The ESPN-fit CNN14 threshold does not generalize. Fingerprint count 10 does not keep the false-identification rate on later games. Sign-off wording showed up on cable and NBC and not on the ESPN or Prime windows that were transcribed; six of twelve hits are one Monday cable game. Scripted Hulu had 0 of 29 strong phrases in those windows. RedZone is the negative control that keeps rejecting "anything unusual is an ad."

## 7. What depends on context the device does not have

- A television-timeout feed. Documented, not purchased, not aligned.
- Oracle fingerprint libraries that include later games.
- The gold end time, which the ceiling uses and a device does not.
- Official play-by-play with `timeout` but no `tv_timeout` (nflverse 2026 header). That is not a commercial boundary.
- Video.

## 8. Human adjudication that can change a conclusion

Fifty-three blinded clips are at `http://localhost:3010/adjudicate`. The public queue has no gold label and no model score. The key used to build the queue is `docs/ohush/swarm/adjudication/queue_key.json` and is not served to the page.

Review them only to decide questions the files cannot:

- Is a DSP-missed "start" actually a late or early label by more than the 200 ms collar?
- Is a program-control clip actually a commercial the gold missed?
- Is an interior clip a change of commercial or still the same break?

Do not relabel all 166 commercials. If the mark is uncertain, choose Uncertain and leave the slider off. Judgments append to `judgments.jsonl` and do not alter gold.

Speaker enrollment is not in this queue. `.booth.json` is not an identity list.

## 9. What each feature contributes

| Feature | Starts it adds | Program risk | Status |
| --- | --- | --- | --- |
| DSP episode | 86/136 within 3 s, many already alarming | 215 episodes/h football, 474/h RedZone | Candidate generator only |
| CNN14 distance | Did not verify the fresh candidates | Threshold failed off ESPN | Retired as a gate |
| Landmark count 10 | 13/41 eval DSP misses within 5 s | ~2.08 false IDs per probed hour | Not promoted |
| Landmark count 200 | 0/121 eval openings within 5 s | 0 on the probed grid | Specific, sparse |
| 40 ms recoverable dip | 4/136 within 1 s | 134 episodes/h | Gate not met |
| Sign-off phrase | 12/133, including 5 DSP misses | 0/135 sampled controls | Not a continuous scan, not a policy |
| Game clock / tv timeout | Not measured | — | Enhanced, waiting on an approved feed |

## 10. Next investment

The comparison target remains Universal v1. CNN14 penultimate embeddings were measured as a direct challenger and did not beat it inside the program cap. Do not retune that logistic, the mel logistic, the fingerprint count, the anomaly distance, or the DSP thresholds on these recordings.

Full-stream announcer speech was measured separately and is not a mute. On 136 football pods, 12 have a strong phrase spoken in the 30 seconds before the start. The recognizer knew 3 of those before the start. The same phrases also occur in ads and once on RedZone while that show continues. See `docs/ohush/research/UNIVERSAL_V3_SPEECH_001/REPORT.md`.

Verified program-speaker enrollment is not measured. The count is 0. Booth files were not read. The two Hulu recordings are scripted shows, not football booths, so they are not in the broadcaster list and actress names are not being collected.

The v4 failure is accepted. No feature set covered any commercial audio inside 10 program seconds on the calibration games, and the selected rule never fires. That retires the lagged-feature action policy. It does not show that a temporal approach cannot work. Game clock, television-timeout events, verified announcers, and verified replay-versus-commercial classes were not in the model. Each cut head had 32 positive training seconds.

Do not start Universal v5. The next measurement is which cues a person can hear at a departure or a return. See `docs/ohush/research/BOUNDARY_EVIDENCE_001/REPORT.md`. That table is empty until the reviews are saved. A later action policy still has to clear the same gate on earlier games. October has already been inspected, so it is not a blind validation set. Do not retune the measured failures, and do not add an external television-timeout feed to Universal.

## Human queue

1. The recordings are already on this machine. Nothing needs to be uploaded into the chat.
2. Review the 53 clips at `/adjudicate`. Drag a box around each stretch, name what it is, and name who is speaking. Saved words do not change the frozen labels.
3. Review the 20 return clips at `/returns` the same way.
4. Keep recording games the closed set does not represent: overtime, halftime, a studio show, ad-free RedZone beyond the two hours already scored. Log the sample index and the capture timestamp when each WAV chunk opens. Leave those files out of threshold fitting.
