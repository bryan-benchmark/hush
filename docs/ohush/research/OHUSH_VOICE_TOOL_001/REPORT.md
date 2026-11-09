# OHUSH_VOICE_TOOL_001

Verdict: the frozen AudioSet class names do not separate the FanDuel box from the Fitzpatrick box. Speech leads both. Music is only a mild tilt on the ad. Crowd and Jingle stay near zero. The commercial mean still ties at the box median. The speaker cosine is still not a mute instruction.

Premise correction: that pair was a commercial-score and tag test. It was not a same-person identity test. The owner named fn0009 as Ryan Fitzpatrick and fn0110 as an unknown male on FanDuel. Those are different people on this tape. Commercial takes must not be used as negative speaker examples. When an enrolled announcer does read an ad, as on DraftKings, the mute decision still belongs to commercial recognition.

## Experiment B — AudioSet tags on the owner boxes

Same boxes as OHUSH_VOICE_TRUTH_002 Path B. Same 5-second CLS vectors that feed the commercial logistic (`MIT/ast-finetuned-audioset-10-10-0.4593`). The AudioSet head is the frozen AST classifier, LayerNorm then Linear, extracted to `C:\OHushData\gpu_lab\models\ast_audioset_classifier.npz`. Checked against `torch.nn.LayerNorm` + Linear on the FanDuel stamp at 575.0: max absolute probability difference `8.9e-8`.

Stamp contract: a row stamped at `t` uses audio `[t−5, t)`. A box includes stamps with `start < t ≤ end`. `lookback_inside_box` is how much of that five-second window overlaps the owner box. Short boxes can be dominated by audio outside the mark. That is written on every second.

Raw files:

| File | Contents |
| --- | --- |
| `tags_meta.json` | Model, stamp rule, fit receipt, watch list |
| `tags_seconds.jsonl` | 281 per-stamp rows: top-5, watch classes, commercial raw and mean10, Path B |
| `tags_boxes.jsonl` | 39 box summaries |
| `FOCUS_FANDUEL_FITZPATRICK.md` | Every stamp on the test pair |

No speaker line moved. No mute rule changed. Realtime false.

## Focus pair

| Box | Speech | Music | Bg music | Jingle | Crowd | mean10 | hot |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FanDuel (fn0110) | 0.280 | 0.260 | 0.004 | 0.001 | 0.000 | 2.384 | 5/5 |
| Fitzpatrick (fn0009) | 0.301 | 0.167 | 0.000 | 0.000 | 0.000 | 2.570 | 15/20 |

Path B still names FanDuel as Herbstreit at 0.321 and rejects Fitzpatrick as Whitworth at 0.090. The tags do not reverse that. Music is higher on FanDuel. It is not a clean cut. Fitzpatrick's mean10 rises and falls inside the box. FanDuel stays hot. That is logistic shape, not an AudioSet name.

## Group medians on the same boxes

| Group | Boxes with stamps | Speech | Music | Bg music | Jingle | Crowd | mean10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Commercial | 19 | 0.245 | 0.210 | 0.0007 | 0.0005 | 0.0003 | 3.418 |
| Named booth | 11 | 0.268 | 0.167 | 0.0006 | 0.0004 | 0.0098 | 0.511 |
| Other program | 7 | 0.277 | 0.171 | 0.0005 | 0.0005 | 0.0006 | 1.298 |

Crowd is higher on booth boxes than on ads, and the absolute values are tiny. Jingle does not move. Music is only slightly higher on ads. Speech is common to every group.

## Ads that still clear the speaker guard

Owner Who labels are in. Full table: `COMMERCIAL_ROOT_CAUSE.md`.

| Box | Who (owner) | Path B | Speech | Music | mean10 | Root cause |
| --- | --- | --- | ---: | ---: | ---: | --- |
| DraftKings (fn0109) | Clarissa Thompson doing the ad | Thompson 0.493 | 0.216 | 0.362 | 5.429 | Same voice |
| Wendy's (fn0118) | unknown female | Thompson 0.373 | 0.338 | 0.134 | 3.418 | False accept |
| FanDuel (fn0110) | unknown male | Herbstreit 0.321 | 0.280 | 0.260 | 2.384 | False accept |

DraftKings is the enrolled announcer reading an ad. The speaker name can be right and the mute still has to come from commercial evidence. Wendy's and FanDuel are other people. FanDuel is not Fitzpatrick on this tape.

## Audit notes

1. **Lookback contamination.** FanDuel's median stamp has only 0.588 of its five seconds inside the box. The first FanDuel stamp is 0.19 inside. DraftKings is 0.544. Wendy's is 0.528. Fitzpatrick is 1.0 because the box is twenty seconds long. Comparing a short ad box to a long desk box mixes window size with content.
2. **Zero-stamp and one-stamp boxes.** One Michaels box (`67.34–67.98`) has no stamp under the `start < t ≤ end` rule. Several ad fragments have a single stamp with lookback inside 0.02–0.20. Those rows are weak.
3. **Top-1 oddities.** Some commercial stamps top as `Snort`, `Door`, or `Explosion`. The frozen head is a weak name. Median Speech or Music probability on these boxes sits near 0.2–0.3, matching earlier NBC name-score work.
4. **Fit rows.** The commercial head was refit on 21,400 successive seconds from two NBC games. That is the same head as before. Those seconds are not independent examples. These Prime boxes were not in that fit.
5. **Classifier extract.** Weights came from the local HuggingFace snapshot. Probabilities match a torch LayerNorm+Linear path to `1e-7`. Transformers 5.x on this machine refused the installed torch 2.5.1, so the check used torch layers directly on the same tensors.

## Decision

Experiment B fails the useful-result test written before the run: the tags do not separate these two boxes while the commercial mean stays tied. A small environment head on Music/Jingle/Crowd is not justified by that pair. That failure is about advertising cues, not about whether the two speakers are the same person.

The ledger is split. Speaker recognition may name Thompson on DraftKings. Commercial recognition still decides the mute. Do not treat a commercial take as a negative for that person's voice. The mute still does not read the 0.25 name.
