# Walk-forward AST mute

Verdict: **FAIL**. No step raises the football corpus above 25.0 commercial seconds while leaving the game on. The live mute was not changed. `NEED.json` was not rewritten. The sealed holdouts were not opened.

The encoder is the cached `MIT/ast-finetuned-audioset-10-10-0.4593` 10-second window, already computed on this machine's GPU. The head is a new logistic regression at each step, fit only on earlier football games. The cutoff sits one step above the highest score that touches program audio in those earlier games. October does not move that cutoff. The reader is `experiments/measurement/walkforward_ast_001.py`.

Dasheng-base and Dasheng-1.2B were already ranked on these same tapes. The larger encoder did not lift every later game to the pre-October ranking floor. Sunday night stays the weak tape. A bigger open model was not started again.

| Game scored | Games in the fit | Commercial seconds held | Program seconds cut | RedZone program seconds |
| --- | ---: | ---: | ---: | ---: |
| Sept 13 NBC | 1 | 1,091.484 | 834.516 | 50.0 |
| Sept 14 ESPN | 2 | 20.0 | 0.0 | 0.0 |
| Sept 24 Prime | 3 | 113.889 | 10.111 | 0.0 |
| Oct 8 Prime Video | 4 | 169.744 | 8.256 | 0.0 |
| Oct 10 cable | 4 | 54.0 | 32.0 | 0.0 |
| Oct 11 afternoon | 4 | 21.0 | 0.0 | 0.0 |
| Oct 11 night | 4 | 51.0 | 224.0 | 0.0 |
| Oct 12 MNF | 4 | 154.0 | 3.0 | 0.0 |

The first transfer is the one that matters for a scalable rule. A head fit on Sept 9 NBC, with a cutoff that leaves that game on, hides 834.5 seconds of the next NBC game and 50 seconds of RedZone. That run has no accuracy.

ESPN is the only later September game the growing fit leaves untouched, and it holds 20 commercial seconds there. The same style of cutoff then hides 10.1 seconds of Sept 24 Prime. October, scored with the four September games frozen, hides program audio on four of the five tapes. The worst is Oct 11 night, 224 seconds. One clean October tape does not make the rule a corpus result.

A run that mutes the game has no accuracy. Universal v1 remains the corpus line that holds commercial audio and leaves the game on: 25.0 seconds, 0 program seconds.
