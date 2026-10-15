# Signal access 001 — 14 October 2026

No live auto-output was enabled. No detector was added. Frozen WAV recordings were not scanned. Verance example code was not downloaded.

The question for this pass is whether a published, authorized signal already says when a commercial is playing, and whether that signal can reach the audio OHush actually captures.

## Verdict

Two checks were completed. Five others from the proposed list were not.

| Check | Result |
| --- | --- |
| Google DAI live sample, session playlist | The player-facing playlist contains `#EXT-X-CUE-OUT:30` and `#EXT-X-CUE-IN`. One fully visible break lasted 30.000 s on the playlist clock. The three segments inside it lasted 10.01, 10.01, and 9.98 s. Session metadata reports the same three durations and calls the break a midroll. |
| DVB targeted-advertising watermark test timeline, plus A/334:2026-04 | The official timeline puts an audio watermark on program and on commercials, and removes it when the test mutes the audio. A/334 puts that watermark in PCM, in the band 2.5–5 kHz, in 1.5-second cells, and does not require the marked interval to line up with an advertisement. No extractor was available to run. |

A cue in a playlist is not a mute. A watermark payload is not a mute. Neither check was played through a television or an optical capture.

## 1. What the DAI sample actually exposed

Google publishes a Big Buck Bunny live HLS sample for testing client apps, Ad Manager network `21775744923`, asset key `c-rArva4ShKVIAkNfy6HUQ`. Opening a session returned HTTP 201 at 2026-10-15 02:20:18 UTC. The media playlist is specific to that session.

Two fetches of the 257 kbps variant:

| Playlist clock (−07:00) | Tag | What followed |
| --- | --- | --- |
| 2026-10-14 19:19:39.558 | `#EXT-X-CUE-IN` | 29.958 s of Big Buck Bunny segments on `storage.googleapis.com` |
| 2026-10-14 19:20:09.516 | `#EXT-X-CUE-OUT:30` | Ad-pod segments on `dai.google.com`. The closing cue was not yet in this live window. |
| 2026-10-14 19:22:09.475 | `#EXT-X-CUE-OUT:30` | Pod segments of 10.01, 10.01, and 9.98 s. Sum 30.00 s. |
| 2026-10-14 19:22:39.475 | `#EXT-X-CUE-IN` | Content segments. The cue is 30.000 s after the cue-out on the same playlist clock. |

The metadata poll for the same session listed break `0003193634` as type `mid`, duration 30 s, three ads of 10.01, 10.01, and 9.98 s. Those durations match the second playlist's pod segments. The same poll listed break `0003193632` as slate: duration 0, expected duration 30, one 30 s slate. A rule that muted every metadata break would mute that slate.

`#EXT-X-DISCONTINUITY` occurred inside the program segments as well as at the pod boundaries. The discontinuity tag did not distinguish the commercial. The cue tags did, on this playlist.

The media playlist contained no `#EXT-X-DATERANGE` and no SCTE-35 binary. SCTE 35-1's own scope says section 12.2 specifies carriage in HLS manifests. This sample used the plain cue tags instead. Google's live-stream encoding note describes `#EXT-X-CUE-OUT` as the splice start and `#EXT-X-CUE-IN` as the splice end, and says an early cue-in ends the break before the planned duration. On the second snapshot the cue-in arrived at the planned 30 s. An early cue-in was not observed.

The ad-pod URLs contain the session id. The program URLs are shared public files. On this sample, the commercial segments are session-specific and the program segments are not.

Timing error against a played waveform was not measured. The segments were not decoded and were not recorded. The 30.000 s figure is the playlist clock agreeing with itself and with the session metadata.

Receipt: `dai_sample_receipt.json`, sha256 `f6edfa45a0fdf25856126dc3a67239df0a9f236af353f34324ccf93b94e0b93c`.

## 2. What the watermark standards actually specify

A/334:2026-04, approved 14 April 2026, specifies the VP1 audio watermark as data residing in a PCM audio signal. Emission is optional. Embedding is specified on PCM before emission encoding. Extraction is specified after the received audio has been decoded back to PCM. The marked energy is in 2.5–5 kHz. A cell is 159 symbols and occupies 1.5 seconds. The symbol interval in Table 5.2 is 1/106 second, which is 1.5/159 second.

The same section says the standard sets no requirement that a marked interval line up with a show segment or an advertisement. A/336:2026-04 is the document that gives those payloads a meaning. Its scope is a receiver that has uncompressed audio and video, including over HDMI, and does not have the original broadcast tables. The payload carries a server code and an interval code. A change in the query flag means a dynamic event is available to fetch. A/336 also defines inverse signaling as a display-override state: the receiver is told to suspend changes it is making to the presentation. That state is not an advertisement flag.

A 48 kHz PCM stream can represent 2.5–5 kHz. A/334 does not name 48 kHz. It says the continuous-time specification corresponds to a sampled signal at whatever rate is in use, and that the same symbol is embedded in every channel of a marked presentation so that a mix of those channels still carries it. Whether a television's optical output preserves the band, the level, and that mix was not measured.

Local copy of the public PDF, not stored in this repo: sha256 `b4a18a8e09528ef4351ad31fc772fe9fb2b43ea0fac8a7121c2749d297ecc64f`.

### Decoder availability

Verance's FAQ says Aspect is currently the only commercial implementation, with detection in LG and Hisense televisions and MediaTek reference designs, and embedding in equipment from Telos/Linear Acoustic, Ross, and Ateme. The same FAQ says Verance has released an example implementation of embedding and detection. The access terms on Verance's request page say that reviewing the example is allowed and that no license is granted to use, copy, modify, distribute, or make commercial use of it. Use requires a current executed agreement with Verance. ATSC's patent statements for the watermark are RAND. The Via Licensing Alliance ATSC 3.0 patent pool lists A/334 and A/335 among the documents excluded from that pool. No separate public VP1 extractor was found. The example code was not requested and was not run.

### The official test timeline

DVB published seven test streams on 13 October 2023 for receivers that detect these watermarks. DVB's news post says they can be freely downloaded. The page lists them as `DVB178-1r1-WM-1.mp4` through `WM-7.mp4`, 260–607 MB, at `https://fetch.dvb.org/?filename=DVB178-1r1-WM-1.mp4` and the six siblings. A plain GET of that URL returned the text `the form must be submit` and did not return the file. The MP4s were not retrieved. Container sample rate, channel count, and codec were therefore not measured.

The accompanying timeline, TM-TA0086r3, was read. For `DVB178-1r1-WM-1`, 1080p25, server code 262144:

| Timeline | Length | Content | Audio watermark | Listed event |
| --- | --- | --- | --- | --- |
| 0:00:00 | 60 s | Program | present | Query-flag toggle from 0:05:00 through 0:59:24, during the program |
| 1:01:00 | 30 s | Ad 1, replaceable | present | none on this row |
| 1:31:01 | 30 s | Ad 2, non-replaceable | present | Query-flag toggle and compact SCTE-35 message 2, from 1:31:01 to 1:41:00 |
| 2:01:02 | 30 s | Ad 3, replaceable | present | none on this row |
| 2:31:03 | 30 s | Ad 4, non-replaceable | present | Query-flag toggle and compact SCTE-35 message 3, from 2:31:03 to 2:41:02 |
| 3:01:04 | 30 s | Ad 5, replaceable | present | none on this row |
| 3:32:04 | 60 s | Program | present | none on this row |

The compact-message window on ad 2 is about 10 s of a 30 s ad. The published message field `duration` is the integer 30000. This pass did not read the compact-message time base in DVB BlueBook A178-1, so that integer was not converted to seconds.

`WM-6` includes stretches labeled as the same advertisement with the audio muted. On those rows the audio-watermark column is empty and the video-watermark column is marked. An optical input has no path to the video watermark. The test design already contains the case where the audio mark is gone because the audio was muted, covered, or replaced by silence. `WM-6` also includes a pause, a channel change to an unmarked program, and fast-forward with the audio muted.

Watermark present, on this timeline, includes the program. The compact SCTE-35 rows are placement messages, and on `WM-1` they are attached to the non-replaceable ads rather than to the replaceable ones. Decoding the mark would still leave the mute decision dependent on whatever the dynamic event means, and on the audio still containing the mark.

## 3. Where the rest of the map stands

Blank cells were not checked. A blank is not a finding that the signal is absent.

| Source | What this pass established | Still required before it can authorize a mute |
| --- | --- | --- |
| Google DAI live sample | Session playlist cues and metadata agree on a 30.000 s midroll for one observed break. | Playback through the optical path, on a clock shared with the playlist. |
| SCTE 35-1, as described by SCTE's catalog | A cue announces a splice opportunity. The catalog lists advertising breaks, advertising content, programs, chapters, and blackouts as uses. SCTE 35-2 is listed as event-based signaling that SCTE says can replace 35-1 integrations. The 35-2 document was not read. | A feed OHush is allowed to read, at a point before the television has discarded the transport. |
| HLS / DASH on the services already recorded | Not checked. The frozen sessions are PCM. | A manifest captured with the optical audio. |
| ATSC A/334 on DVB test media | Specified path and official timeline, above. | An extractor that can be used, then the MP4, then a 48 kHz stereo PCM conversion of that file. |
| ATSC A/334 on existing OHush recordings | Not checked. | The same extractor. Absence of a decoder is not evidence the marks are absent, and it is not evidence they are present. |
| YouTube IFrame API, IMA SDK events, Triton `BREAK` / `ENDBREAK`, RDS, Nielsen | Not re-checked against the current documents. | A player or feed the product is allowed to integrate with. Nielsen was not treated as an open commercial-break decoder. |
| Acoustic alignment of a reference feed to an optical capture | Not run. | A new paired capture. `MEASUREMENT_STOPPING_POINT_002.md` already rejected the Thursday `run19` join: the duration gap is 0.299 s, and the best feature offset is about one second with no sample lock. |

SCTE-104, SCTE-224, VAST, VMAP, and IAB identifiers were not opened. They describe upstream scheduling and creative identity. They do not, by themselves, describe the waveform on the optical output.

## 4. How this splits the work

These are separate measurements. A result from one is not a result for another.

**Explicit signals.** Read cues the viewer-facing player or manifest already carries, on streams the project is allowed to open. The DAI sample is the first receipt. The next one needs a manifest and an optical recording on one clock. Old ESPN, Prime, and Hulu WAVs cannot supply the manifest half.

**Embedded identifiers.** VP1 is specified for the PCM path OHush already uses, and the official test timeline shows why a successful decode is still not a mute. The branch waits on an extractor Verance's terms allow this project to run. Building one from the standard was not started.

**Inference.** Microgap, known-ad fingerprint, and program-identity work stay on the frozen recordings. Those recordings remain the Universal set. A future session that also has a manifest is an explicit-signal session, and its score is not a Universal score.

A shared national cue plus acoustic alignment is a fourth experiment, not a shortcut around the first three. It needs a feed the project is allowed to hold, a measured offset to each viewer's optical clock, and a demonstrated match between that feed's commercials and the viewer's commercials. Personalized pod URLs on the DAI sample are a concrete form of the mismatch. The Thursday alignment attempt is a concrete form of the clock problem.

## Uncertainties

- The DAI session is a loop of a published test film with inserted sample ads. The 30 s agreement can be different on a sports broadcast, a FAST channel, or a stream that omits the cue tags after personalization.
- The second playlist fetch did not re-poll metadata, so the 10.01 / 10.01 / 9.98 s metadata row was tied to the first poll's break ids. The segment durations on the second fetch match those numbers. They were not matched by break id.
- The DVB timeline was read from the project's PDF text extraction. Column assignment for `WM-1` and `WM-6` is consistent across the extracted tables. The MP4s themselves were not opened.
- A/334's resilience claim is the standard's claim about lossy compression and mixing. It is not a measurement of an optical output.
- SCTE 35-2's reseller listing shows 16 April 2026. That date was not confirmed from an SCTE PDF.

## Files this pass added

| File | sha256 |
| --- | --- |
| `docs/ohush/research/SIGNAL_ACCESS_001/dai_sample_receipt.json` | `f6edfa45a0fdf25856126dc3a67239df0a9f236af353f34324ccf93b94e0b93c` |
| `docs/ohush/research/SIGNAL_ACCESS_001/REPORT.md` | this file |
