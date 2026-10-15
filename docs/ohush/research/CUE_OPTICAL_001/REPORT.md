# CUE-OPTICAL-001

Enhanced only. This is not a Universal score, and it is not a mute. Playback stays play. A paired manifest and optical recording that meets the bar below is evidence the cue describes that one playback. It is not authorization to mute.

The bar was written before any optical score: no program seconds covered, no slate seconds covered, the return within one second of the audible end, and the start latency reported on its own. Commercial seconds covered are reported even when they are far from complete coverage.

One manifest, one playback session, one optical recording. A newly opened session is a different advertisement pod. Google's sample is the first source. A second authorized player with a different insertion implementation is a replication, not a substitute for the first pairing. A browser-to-television path does not extend to native television apps that were not in the capture.

## The five questions

1. **Same manifest.** Not met. `SIGNAL_ACCESS_001` opened one Google DAI session, `cd75a709-fd44-4ab3-bedc-7ec2858d1153:CHS`, and fetched that session's media playlist twice. Nothing played those segments through a television, so there is no player whose manifest can be compared with heard audio.

2. **Alignment with the optical audio.** Not measured. Start error, end error, drift, and discontinuities against a waveform do not exist. The 30.000 seconds in the receipt is the playlist clock agreeing with itself.

3. **Early enough to act.** On the playlist clock only. In the first snapshot, `#EXT-X-CUE-OUT:30` was already in the live window at 19:20:09.516−07:00, and the closing `#EXT-X-CUE-IN` was not yet in that window. The cue-out was visible before the break ended on the playlist. Whether it was visible before the corresponding sound came out of a television was not measured. A marker read after the segment has played does not count.

4. **Ads versus slates.** Metadata only, and the metadata is not the ground truth. The same session poll lists midroll breaks `0003193633` and `0003193634`, each 30 seconds with three ads of 10.01, 10.01, and 9.98 seconds. It also lists break `0003193632` as a slate: duration 0, expected duration 30, slate duration 30. The second playlist's pod segments sum to 30.00 seconds and match the midroll durations. No optical annotation says which of those sounds were advertisements and which were slate. A rule that muted every metadata break would treat the slate as a commercial.

5. **Seconds improved.** Not measured. Commercial seconds, program seconds, slate seconds, and delayed returns require the optical truth this capture does not have.

## What stays in the other tracks

Universal work stays on the frozen recordings. The count-10 reference pods and the missing speaker embeddings are that track. Watermark decoding stays blocked until a VP1 extractor can be used under license. DVB test videos are not part of this experiment. The rejected Thursday acoustic join is not being reopened.

Receipt for the playlist half: `docs/ohush/research/SIGNAL_ACCESS_001/dai_sample_receipt.json`.
