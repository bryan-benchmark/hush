# Show roster

Each broadcast has its own booth. The booths are not compared with each other.

Sunday Night Football is Mike Tirico and Cris Collinsworth. Monday Night Football is Joe Buck and Troy Aikman. Thursday Night Football is Al Michaels and Kirk Herbstreit. Saturday college is Kirk Herbstreit and Chris Fowler. RedZone is Scott Hanson. A voice is a candidate only for the show that is on.

Membership is 1 when that booth was just heard. It falls to 0 after five minutes without them. While RedZone membership is above 0, commercial rules are off. A game keeps its own commercial rules on, because those shows have breaks. Five quiet minutes means this show has let go. It does not mute. The live gate was not changed. Playback stays play. The published cosine stays 0.25.

On the labeled RedZone span, Hanson alone never goes quiet for five minutes. 2,437 hits. The longest gap is 241.9 seconds. Commercial seconds inside that rule: 0. He was not scored on NBC, ESPN, or Prime.

| Show | Booth used | Five-minute gaps | Commercial rules while the booth is present |
| --- | --- | ---: | --- |
| RedZone | Scott Hanson | 0 | off |
| Sunday Night Football, Sept 9 | Tirico, Collinsworth | 0 | on |
| Sunday Night Football, Sept 13 | Tirico, Collinsworth | 4, longest 1,126.6 s | on |
| Monday Night Football, Sept 14 | Buck, Aikman | 1, longest 304.2 s | on |
| Thursday Night Football, Sept 24 | Al Michaels only | 4, longest 1,122.6 s | on |
| Thursday Night Football, Oct 8 | Al Michaels only | 4, longest 708.1 s | on |

Kirk Herbstreit was named and then cleared, so Thursday Night Football is Michaels alone until Herbstreit is enrolled again. Chris Fowler has no enrollment, so Saturday college has no booth to score. Cable and antenna recordings were not given a national booth.

Football accuracy stays 79.26%. This rule does not mute a game commercial. The earlier 12,318 seconds were Hanson applied to other shows. That comparison is not this algorithm.

Script: `experiments/measurement/show_roster_001.py`. Rule: `src/hush/show_roster.py`. Counts: `results.json`.
