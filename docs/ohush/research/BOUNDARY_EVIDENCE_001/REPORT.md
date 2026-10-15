# Broadcast-boundary evidence

The 53 blinded clips are labeled. This file is the reading of those listens. Gold was not edited. No detector threshold was moved. The separate 20-clip return page is still empty.

The latest save for each clip is the one that counts. There are 248 appended rows and 53 clips. The keyword tag on a row is not the coding. "Commerical" would have been missed, and "we're back in 30 seconds" is a sign-off, not a return. Each box was coded from the words. The coding is `adjudication_coding.json`. The one-row table is `cue_table.csv`.

The clip is 20 seconds. The gold moment, or the sampled moment, is 10 seconds in.

## Are the DSP misses just a 200 ms label error?

No. Twelve of the thirteen misses are real departures, and they sound like the hits.

A mark counts as on the heard cut when it falls inside the short hole the listener put under it, or within 200 ms of that hole or of the spot. On that rule, 5 of the 12 real misses are on the cut, and 8 of the 11 hits that still contain the program are on the cut. Two more misses are just outside it: the spot starts 240 ms early on one and 380 ms early on the other. The rest of the misses have the spot 1.1 to 3.4 seconds away, while the mark is still in outro music, crowd, or a mixed music-and-ad box. Hits do the same thing. The spot on a hit is often 0.5 to 1.5 seconds after the mark, because the mark is the hole and the advertisement starts after the hole. One hit is on a short lag, then the outro music comes back and the spot starts 3 seconds later. One hit and one miss never leave the advertisements: the 20 seconds are a Chevy spot with a lag in it, and a cable break that is already underway. Those two are not throws a detector failed to hear.

Moving the gold mark onto the first frame of the spot would slide hits and misses together. It would not explain why DSP fired within 3 seconds on one group and not the other.

| Clip | Network | DSP | Where the mark sits | Spot, vs the mark | Hole, vs the mark |
| --- | --- | --- | --- | ---: | ---: |
| q003 | NBC | miss | between the sign-off and the dead air | +0.92 s | +0.02 s |
| q005 | Prime | miss | in the hole | +0.85 s | −0.20 s |
| q006 | Prime | miss | in the hole | +1.16 s | −0.23 s |
| q007 | Prime Video | miss | in the hole | +1.00 s | −0.06 s |
| q012 | Cable | miss | at the Nick Saban spot | −0.07 s | — |
| q004 | NBC | miss | just inside the spot | −0.24 s | — |
| q010 | ESPN | miss | just inside the spot | −0.38 s | — |
| q001 | NBC | miss | in music with the Siri ad already in it | −1.08 s | — |
| q011 | Cable | miss | in the crowd outro | +2.02 s | — |
| q009 | ESPN | miss | in outro music | +2.51 s | — |
| q002 | NBC | miss | in crowd and outro music | +2.88 s | +2.31 s |
| q008 | Prime Video | miss | in filler after "back in 30 seconds" | +3.39 s | — |
| q013 | Cable | miss | inside a Chevy spot that never shows the game | −0.04 s | — |
| q014 | NBC | hit | in the hole | +0.01 s | −0.38 s |
| q016 | NBC | hit | in the hole | +0.70 s | −0.03 s |
| q018 | Prime | hit | between the hole and the spot | +0.08 s | −1.07 s |
| q015 | NBC | hit | in the hole | +0.69 s | −0.18 s |
| q017 | Prime | hit | in the hole | +1.08 s | −0.12 s |
| q020 | Prime Video | hit | in the hole | +1.45 s | −0.11 s |
| q019 | Prime Video | hit | in the hole | +0.51 s | −0.67 s |
| q021 | ESPN | hit | just inside the DealDash spot | −0.37 s | — |
| q024 | Cable | hit | inside the Google spot | −0.73 s | — |
| q025 | Cable | hit | still in Berman's outro | +2.52 s | +1.29 s |
| q022 | ESPN | hit | in a short lag; the outro then resumes | +3.00 s | — |
| q023 | Cable | hit | in a lag between two pieces of an ad | +2.18 s | — |

## Did a program control turn out to be a commercial?

One did. Eight did not. All five RedZone controls are the show.

The NBC probe at 240 seconds (`q034`, `hush_20260909_213047`) is 98 seconds after the gold pod that ends at 141.5 seconds, and the next gold pod starts at 623 seconds. The listen is Mike Tirico saying the broadcast will be back in 30 seconds, then an AWS commercial. That commercial is not in the gold. The gold row was left as it is.

The other eight far-from-pod clips are the game: Collinsworth, Herbstreit, Tirico, Buck, Fowler, Michaels, a referee, crowd, whistles, and one stretch of streaming lag inside Herbstreit. None of them is an advertisement.

The five RedZone clips are Scott Hanson, a game announcer under him, crowd, and streaming lag. The lag at 2,800 seconds sits on the sampled moment, between two stretches of Hanson. Lag by itself is not a commercial. RedZone, in this sample, has no advertisement.

## Is the middle of a long break a new commercial or the same break?

The same break. All six interior clips, taken 40 seconds after a gold start, are still advertisements. None of them returns to the game.

| Clip | What is in the middle of the pod |
| --- | --- |
| q048 | One USAA spot across the whole clip |
| q049 | One spot, and the listener was unsure whether it was a trailer |
| q050 | A Peacock outro spot, then an HSS spot |
| q051 | Stadium noise, then a T-Mobile spot. The pod still has a production edge 40 seconds in |
| q052 | One unnamed spot across the whole clip |
| q053 | Two stretches called a commercial, split by about half a second. No second brand was named |

One interior is an explicit change of sponsor. The rest are one spot, or a spot the listener did not split. That does not make the interior a return.

## What a person can hear, and when

On the 23 departures that still contain the program, the order is stable. A named announcer is still talking, often over a music bed. The words are sometimes an explicit handoff: "back in 30 seconds" (two clips), the Toyota halftime sign-off, an injury timeout. Then the announcer stops and the music or the crowd continues. Then there is often a hole of a few tenths of a second, which the listener also calls stream lag. Then the spot. Eleven of the 23 have the announcer in the clip before the spot, 14 have music before it, 5 have crowd before it, and 13 have a hole immediately in front of the spot.

The spot is a poor stand-in for the gold start. On the hits, it arrives from about 0.4 seconds early to 1.5 seconds late, and once 3 seconds late. The thing that sits on the gold start is the hole, or the last of the outro.

On the eight returns that were in this queue, the order is the spot, a hole, then intro music or crowd, then the announcer. The announcer is 1.9 and 8.7 seconds after the mark on the two NBC returns, 2.4 seconds after on Prime Video, 0.6 seconds before on one cable return, and 0.8 seconds after on the other. ESPN is the awkward pair: one gold end is still inside the ShipStation ad for 5.0 seconds, with Joe Buck at 7.7 seconds; the other ad ends 0.3 seconds after the mark and Troy Aikman is in at 3.2 seconds. The Prime return after Miller Lite is Al Michaels reading a promo for a network show, not the game.

Streaming lag shows up in the breaks, in the game, and in RedZone. It is common and it is not specific.

## What this does not do

These 53 listens do not retune DSP, CNN14, the fingerprint counts, or Universal v1. They do not fill the 20-clip return page. They do not change the gold, including the NBC break at 240 seconds that this listen found. A later action policy still has to clear the same gate on earlier games. October stays an inspected set. The sealed holdouts stay sealed.
