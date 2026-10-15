# Dataset inventory

Closed development material only. Sealed holdouts `hush_20260917_205513` and `hush_20260920_200635` are not listed and were not opened. WAV files stay under `recordings/` and are not in Git. This inventory does not hash the PCM. It records that each session directory was found once, the `session.json` SHA-256 prefix, the chunk count, and the byte size of the WAV chunks.

Every row is 48 kHz, 2 channels. Gold commercials are `event_class=commercial`, `desired_action=mute`, confidence not `unsure`, inside a fully annotated span. Count: 166.

| Session | Source | Program | Annotated span (s) | Ads | WAV chunks | WAV bytes | session.json |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| hush_20260827_135935 | Hulu | scripted | 300–7200 | 11 | 15 | 2,537,476,756 | 0c75aa16d9345f2f |
| hush_20260909_213047 | NBC | sports | 0–9373 | 20 | 11 | 1,799,651,812 | ab4d51bca38d7dc4 |
| hush_20260913_150934 | FOX | RedZone | 0–7200 | 0 | 13 | 2,210,345,532 | 725aa2147b5948f1 |
| hush_20260913_210542 | NBC | sports | 0–12600 | 21 | 14 | 2,419,200,616 | c3602ce07eb7012b |
| hush_20260914_212529 | ESPN | sports | 0–6899 | 15 | 11 | 1,853,170,148 | fc41a679e113e594 |
| hush_20260924_220624 | Prime | sports | 0–7600 | 13 | 9 | 1,520,619,916 | 0c2003e2e412dc0d |
| hush_20261007_220650 | Hulu | scripted | 20–11751 | 19 | 14 | 2,311,557,736 | 86b115b315ea96c3 |
| hush_20261008_205100 | Prime Video | sports | 0–10440.364 | 23 | 33 | 2,004,559,276 | c77488ab4a3ca681 |
| hush_20261010_222400 | Cable / antenna | sports | 0–6064.768 | 6 | 8 | 1,164,435,808 | eccb77d8e48aae8c |
| hush_20261011_135700 | Cable / antenna | sports | 0–4896.768 | 8 | 6 | 940,179,720 | 108567c813591662 |
| hush_20261011_204300 | Cable / antenna | sports | 0–14405.376 | 6 | 17 | 2,765,832,940 | c1be2c06fb60c1ce |
| hush_20261012_204200 | Cable / antenna | sports | 0–13111.808 | 24 | 15 | 2,517,467,796 | ad810903079c9ad3 |

Football, for scoring, is sports excluding RedZone: 136 commercials, 17,648.4 ad seconds, published program time 18.73 h (67,428 s). Corpus length used for the per-second budget: 85,076.4 s.

## Clock notes

- Thursday `hush_20261008_205100` is usable on the capture-order clock. Its engine-clock decision log is not gold and is not joined to these spans.
- That recording has a hole of about 417 seconds. Silence was not invented to fill it.
- RedZone gold coverage stops at 7200 s. Audio after that is not annotated and is not scored.
- Catalog text for the RedZone session still names a game. The gold note is RedZone, and the ad count in the span is zero. Scoring uses the gold note.
- Program and play marks can contain commercials. They are context. They are not a claim that every second outside a gold commercial is commercial-free.

## Partitions

Development, calibration, and evaluation stay at whole-broadcast granularity. ESPN `hush_20260914_212529` was the development broadcast for the fingerprint operating count and must not be reused as the confirmation set for that count. Leave-one-recording-out is the default when a later model is fit. Adjacent seconds of the same advertisement are not independent test samples. Repeated advertisements across recordings need an identity check before a match is called generalization.

Unexamined future recordings are prospective evaluation. Thresholds are not developed on them.
