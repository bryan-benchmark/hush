# Atomic misses

Every missed start now has a four-second receipt on each side of the labeled cut. 133 of 134 could be read. One Prime cut sits on the start of the file and the read was short. The rows are `atomic_receipts.jsonl`. No threshold was fit. Nothing was muted.

There is no play clock in the ledger. The misses are spread through the recordings: 49 in the first quarter of the file, 64 in the middle, 20 in the last quarter.

## What is on each side

| | Four seconds before the cut | Four seconds after the cut |
| --- | ---: | ---: |
| Loudness, median | −29.0 dB | −29.1 dB |
| Pitch, median | 163 Hz | 170 Hz |
| Brightness, median | 832 Hz | 692 Hz |
| Speech | 0.44 | 0.82 |
| Music | 0.92 | 0.73 |
| Crowd | 0.01 | 0.01 |
| Jingle head | 0.00 | 0.00 |
| Singing head | 0.00 | 0.00 |
| Envelope pulse | 0.38 s, strength 0.26 | 0.32 s, strength 0.32 |

Loudness does not move. Pitch stays in a speaking voice. The jingle and singing heads do not fire on either side. The pulse in the loudness envelope is weak on both sides. A different tune is not visible as a new pitch or a new beat at the cut.

Music is already high before the label on **112 of 133** misses. It rises from under 0.30 to at least 0.70 across the cut on **6**. On 42 it falls by 0.30 or more after the cut. The song the fingerprint missed is already playing when the gold start arrives. The earlier scan put that arrival between 20 and 10 seconds before the label.

## Who is speaking

The booth is scored only against that show's own roster, at the published cosine 0.25.

On 28 misses the booth is present in the last four seconds. On all 28 that match is gone in the first four seconds of the commercial. On 54 misses the speaker tracker has no speech window in those last four seconds, so there is no name to give. Cable and antenna breaks have no national booth assigned, so they are not given Tirico's or Hanson's name.

The words, where the tracker or Whisper caught them, change job. One NBC miss at 6,357 seconds is Tirico at cosine 0.73, music already 0.91, saying "Seattle's ability to get the ball back if the Patriots scored." The next four seconds are "They approve the project update," music 0.06, speech still high, Tirico gone. Another, at 1,547 seconds, is already "by YouTube TV" before the label and "Once you've been to the moon" after it. The cut is often a new reader over a bed that started earlier, not the first note of a song.

## Where a fingerprint would have to sit

The labeled instant is a bad place to hear the game's rhythm break, because for these misses the break has already happened. What does change at the cut, when it changes, is the person: the enrolled booth leaves, and a voice we do not have enrolled starts a different sentence. What changed earlier is the music bed arriving under the booth. Those are two different atoms, and the receipts keep them apart.

Script: `experiments/measurement/atomic_miss_001.py` and `experiments/measurement/atomic_miss_audioset.py`.
