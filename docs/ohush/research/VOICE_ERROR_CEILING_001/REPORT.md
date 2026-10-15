# Voice error ceiling

This is a diagnostic of the published count-10 fingerprint, not a new mute and not a live result. Playback stays PLAY. Universal v1 is unchanged. The match line stays the published ECAPA cosine 0.25. It was not fit.

The 72 football incidents were rebuilt from `docs/ohush/research/UNIVERSAL_V1/decisions.jsonl` and the closed gold spans, with the same read holes the fingerprint scorer skips. The rebuilt football total is 72 incidents and 432.163 seconds. The published figure is 432.1 seconds. RedZone and scripted Hulu are separate rows.

A second is `embedded_speech` when an existing speaker-embedding window overlaps the wrong mute. That means the speaker model already found voiced audio there. It does not mean a known announcer was talking. Nobody has labeled these 72 incidents by ear. The column `oracle_known_announcer` is `not_labeled` on every row.

A second is `causal_named_match` when the existing voice guard would force PLAY. The name is available only after that person's own labeled span has ended, and only from the end of the embedding window. Absence of a voice never creates a mute. This is the same rule already scored in `docs/ohush/research/VOICE_GUARD_001`. It was not retuned.

## Football

| Question | Seconds | Incidents |
| --- | ---: | ---: |
| Count-10 wrongly covers program | 432.2 | 72 |
| On a recording that has speaker embeddings | 159.1 | 21 |
| Of those, an embedding window overlaps the mute | 131.0 | — |
| Current ECAPA 0.25 guard would give back | 27.5 | — |
| No speaker embeddings, so voice cannot be tested | 273.1 | 51 |

The exploratory rescue target was 86.4 seconds, 20% of 432.1. The current guard returns 27.5. That is 6.4% of the football error. It does not meet the target.

The same guard, already scored, gives back 88.9 commercial seconds. The proposed sacrifice cap was 390.3 seconds, 10% of the 3,903.2 count-10 commercial seconds. 88.9 is inside that cap. Count-10 still covers 3,814.3 commercial seconds after the giveback, against Universal v1's 25.0.

The 131.0 seconds are the largest speech-shaped slice we can see without a new model and without inventing names. On NBC `hush_20260913_210542`, 109.9 of 122.8 wrong-mute seconds overlap an embedding window, and the named guard returns 11.9. On ESPN, 13.3 of 16.6 overlap speech and the guard returns 5.5. On the September 24 Prime recording, the guard returns 10.1 seconds, a little more than the 7.8 seconds that sit inside an embedding window, because protection lasts until the next window ends.

## Where the other 273 seconds are

These five recordings have no speaker-embedding file, so the ceiling there is unknown.

| Recording | Wrong-mute seconds | Incidents |
| --- | ---: | ---: |
| Prime Video `hush_20261008_205100` | 57.2 | 12 |
| Cable `hush_20261010_222400` | 57.6 | 9 |
| Cable `hush_20261011_135700` | 79.6 | 15 |
| Cable `hush_20261011_204300` | 20.0 | 4 |
| Cable `hush_20261012_204200` | 58.6 | 11 |

These October recordings were already inspected. They are not a blind holdout. They also must not be used to pick a new threshold.

## Kept separate

RedZone `hush_20260913_150934`: 10.0 program seconds, 2 incidents, 0 commercial seconds. The guard returns all 10.0. The matching name in the existing guard report is Mike Tirico, enrolled from an earlier NBC span, not Scott Hanson. RedZone has no gold commercials, so this does not test an ad.

Scripted Hulu: 61.5 program seconds, 11 incidents. No speaker embeddings. None of it is in the 432.1.

## What this does not say

27.5 is not an upper bound on what a better voice model could save. 131.0 is not a count of recognizable announcers. 273.1 is not proof that those seconds are silent. The per-incident times are in `per_incident.csv`.
