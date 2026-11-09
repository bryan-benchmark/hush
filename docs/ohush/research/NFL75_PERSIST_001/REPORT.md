# NFL75_PERSIST_001

October 8 Prime, development tape `hush_20261008_205100`. The two NBC games set both lines. October did not. Nothing muted. The sealed sessions were not opened.

## Lines

The logistic head, refit on the same two NBC caches, matches the published receipt: 21,400 rows, train accuracy 0.9273. The start line is the published value `12.155325889587404`. The return line is the highest clear-program second on those NBC games, `8.284611701965332`, at Sept 13 NBC session time 11412. That is the second the clear-ceiling report already named.

A cover requires the score to stay at or above the start line for 10 seconds, or for 20 seconds. A return requires the score to stay at or below the return line for 3 seconds. Scores between the lines hold the current state. A hole longer than 2 seconds does not count as sustained evidence.

## Result

| Setting | Ads covered | Coverage | False-mute episodes | Longest | Hidden program / hour | Pods that never hold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 s | 0 of 2,642.141 s | 0.0% | 0 | 0 s | 0 | 23 of 23 |
| 20 s | 0 of 2,642.141 s | 0.0% | 0 | 0 s | 0 | 23 of 23 |

Acceptance fails on coverage. The false-mute caps are idle because there is no cover.

Across all 10,435 scores on this tape there are 40 runs at or above the start line. The longest is 6 seconds. None last 10 seconds, on a commercial or on the game. The longest run inside any of the 23 pods is also 6 seconds.

The 1.5-second return fade is not in this score. There is no return to charge it to.

## What this decides

Waiting 10 or 20 seconds at the line that leaves the NBC fit games untouched covers none of this game. The score does not stay there. Further persistence at this line will not reach 75%.

Cache sha256 `795ceabab9d8d760226a72b0c2ed5b49131d965c58a3ecba1c3219d1a1f0a9cb`. Window 5 seconds, past audio only, as stored. Speakers were not moved.

## Commands

```
python -m unittest tests.test_nfl75_persist -v
python -m experiments.nfl75.persist_main
```
